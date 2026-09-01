"""
The manifest in the bucket, and the bucket itself.

photos.json is the only record of a photograph. There is no copy beside the
source file any more, and no copy in this repository: what the bucket holds is
what exists. Every change here therefore reads the current manifest, edits it,
and writes it back -- never assembles one from local state, which would quietly
drop anything this machine happens not to have.
"""

import json
import subprocess
import time
from pathlib import Path

import config
from pipeline import ROOT, TILES_DIR, THUMBS_DIR, find_tool, run, tile_base

DEST = f"{config.R2_REMOTE}:{config.R2_BUCKET}"


# --- the manifest -----------------------------------------------------------

def load():
    """
    The published manifest, straight from the bucket.

    Read through rclone rather than the public URL: the same credentials that
    write it, no CDN copy to be a minute stale, and it keeps working if the
    bucket ever stops being publicly readable.
    """
    try:
        raw = run([find_tool("rclone"), "cat",
                   f"{DEST}/{config.MANIFEST_NAME}", "--s3-no-check-bucket"])
    except RuntimeError:
        return {"photos": [], "albums": [], "generated": ""}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"photos": [], "albums": [], "generated": ""}
    data.setdefault("photos", [])
    data.setdefault("albums", [])
    return data


def save(manifest):
    """Write the manifest back, albums and ordering brought up to date."""
    manifest["photos"] = _sorted(manifest["photos"])
    manifest["albums"] = _albums(manifest["photos"])
    manifest["generated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    tmp = ROOT / ".manifest.tmp.json"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    try:
        run([find_tool("rclone"), "copyto", str(tmp),
             f"{DEST}/{config.MANIFEST_NAME}", "--s3-no-check-bucket",
             "--header-upload", f"Cache-Control: {config.MANIFEST_CACHE_CONTROL}"])
    finally:
        tmp.unlink(missing_ok=True)
    return manifest


def put(manifest, entry):
    """Add a photograph, or replace it if that id is already published."""
    photos = [p for p in manifest["photos"] if p.get("id") != entry["id"]]
    photos.append(entry)
    manifest["photos"] = photos
    return manifest


def drop(manifest, ids):
    ids = set(ids)
    manifest["photos"] = [p for p in manifest["photos"] if p.get("id") not in ids]
    return manifest


def _sorted(photos):
    """Newest first. Photographs with no date sort last."""
    return sorted(photos, key=lambda d: d.get("date") or "", reverse=True)


def _albums(photos):
    """
    One entry per album folder, its cover the newest photograph in it -- which,
    the list already being sorted, is simply the first one seen.
    """
    albums = []
    for photo in photos:
        name = photo.get("album")
        if not name:
            continue
        found = next((a for a in albums if a["name"] == name), None)
        if found:
            found["count"] += 1
            continue
        albums.append({
            "name": name,
            "cover": photo["id"],
            "coverRev": photo.get("rev", ""),
            "coverWidth": photo.get("width"),
            "coverHeight": photo.get("height"),
            "coverLqip": photo.get("lqip", ""),
            "count": 1,
            "date": photo.get("date", ""),
        })
    albums.sort(key=lambda a: a.get("date") or "", reverse=True)
    return albums


# --- the bucket -------------------------------------------------------------

def upload(photo_id, rev, log=print):
    """
    Push one photograph's pyramid and thumbnail.

    Only this photograph's files, not a sync of the whole directory: they are
    deleted once they are up, so there is never anything else there to sync.
    """
    rclone = find_tool("rclone")
    base = tile_base(photo_id, rev)
    parent = str(Path(base).parent).replace("\\", "/")
    prefix = "" if parent == "." else parent + "/"
    stem = Path(base).name

    log("    uploading tiles")
    run([rclone, "copy", str((TILES_DIR / base).parent), f"{DEST}/{prefix}",
         "--include", f"{stem}_files/**", "--include", f"{stem}.dzi",
         "--transfers", "48", "--checkers", "48", "--s3-no-check-bucket",
         "--header-upload", f"Cache-Control: {config.TILE_CACHE_CONTROL}"])

    log("    uploading thumbnail")
    run([rclone, "copyto", str(THUMBS_DIR / f"{base}.webp"),
         f"{DEST}/thumbs/{base}.webp", "--s3-no-check-bucket",
         "--header-upload", f"Cache-Control: {config.TILE_CACHE_CONTROL}"])


def purge(photo_id, log=print):
    """
    Delete every revision of a photograph from the bucket.

    Matched by prefix rather than by the revision the manifest happens to name,
    so a photograph re-tiled at some point does not leave its earlier pyramids
    behind, unreferenced and unreachable but still paid for.
    """
    rclone = find_tool("rclone")
    parent = str(Path(photo_id).parent).replace("\\", "/")
    prefix = "" if parent == "." else parent + "/"
    stem = Path(photo_id).name

    log(f"    removing {photo_id} from the bucket")
    try:
        run([rclone, "delete", f"{DEST}/{prefix}",
             "--include", f"{stem}__*_files/**",
             "--include", f"{stem}__*.dzi",
             "--transfers", "48", "--checkers", "48",
             "--rmdirs", "--s3-no-check-bucket"])
    except RuntimeError:
        pass                    # already gone

    # Fingerprinted, like the tiles. The old code deleted thumbs/<id>.webp,
    # a name nothing has been written under since thumbnails started carrying
    # a revision, so every removed photograph left its thumbnail behind.
    try:
        run([rclone, "delete", f"{DEST}/thumbs/{prefix}",
             "--include", f"{stem}__*.webp",
             "--include", f"{stem}.webp",
             "--rmdirs", "--s3-no-check-bucket"])
    except RuntimeError:
        pass


def discard_local(photo_id, rev=None):
    """
    Drop the generated files once they are safely uploaded.

    They are a build artefact of the original, not a copy of it: everything
    needed to serve the photograph is in the bucket, and re-tiling would mean
    picking the original again in any case.
    """
    for root in (TILES_DIR, THUMBS_DIR):
        parent = (root / photo_id).parent
        if not parent.is_dir():
            continue
        stem = Path(photo_id).name
        pattern = f"{stem}__{rev}*" if rev else f"{stem}__*"
        for p in list(parent.glob(pattern)) + list(parent.glob(f"{stem}.webp")):
            if p.is_dir():
                _rmtree(p)
            else:
                p.unlink(missing_ok=True)
        _prune_empty(parent, root)


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def _prune_empty(start, stop):
    """Remove album folders left empty, up to but not including the root."""
    path = start
    while path != stop and path.is_dir() and not any(path.iterdir()):
        path.rmdir()
        path = path.parent
