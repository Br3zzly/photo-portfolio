"""
The manifest in the bucket, and the bucket itself.

photos.json is the only record of a photograph. There is no copy beside the
source file any more, and no copy in this repository: what the bucket holds is
what exists. Every change here therefore reads the current manifest, edits it,
and writes it back -- never assembles one from local state, which would quietly
drop anything this machine happens not to have.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
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
    # --no-traverse: without it rclone lists the whole destination to work out
    # what it can skip, which means reading every object in the bucket to
    # upload one photograph -- a cost that grows with the collection. Nothing
    # can be there to skip anyway: the path carries a fingerprint, so a photo
    # being uploaded has by definition never been at this address before.
    run([rclone, "copy", str((TILES_DIR / base).parent), f"{DEST}/{prefix}",
         "--include", f"{stem}_files/**", "--include", f"{stem}.dzi",
         "--transfers", "48", "--checkers", "48", "--s3-no-check-bucket",
         "--no-traverse",
         "--header-upload", f"Cache-Control: {config.TILE_CACHE_CONTROL}"])

    log("    uploading thumbnail")
    run([rclone, "copyto", str(THUMBS_DIR / f"{base}.webp"),
         f"{DEST}/thumbs/{base}.webp", "--s3-no-check-bucket",
         "--header-upload", f"Cache-Control: {config.TILE_CACHE_CONTROL}"])


def _list(where, kind):
    """One shallow listing of a prefix. Cheap: a single request, no recursion."""
    try:
        out = run([find_tool("rclone"), "lsf", where, kind, "--s3-no-check-bucket"])
    except RuntimeError:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _split(photo_id):
    parent = str(Path(photo_id).parent).replace("\\", "/")
    prefix = "" if parent == "." else parent + "/"
    return prefix, Path(photo_id).name


def purge(photo_id, log=print):
    """
    Delete every trace of a photograph from the bucket.

    Scoped to prefixes rather than expressed as a filter over the bucket. A
    filter reads every object there is before it can tell which few to remove,
    so removing one photograph cost a full listing of the collection and
    removing ten cost ten of them -- time that grew with how much was
    published rather than with how much was being deleted. Listing the one
    folder the photograph lives in, then purging its own pyramid by prefix,
    touches only that photograph.

    Every revision goes, including the un-fingerprinted names from before tiles
    carried one, which the old filter could not match and therefore left behind.
    """
    rclone = find_tool("rclone")
    prefix, stem = _split(photo_id)

    log(f"    removing {photo_id} from the bucket")

    def mine(name):
        """`LL_06590`, or any revision of it, and nothing that merely starts
        the same way -- LL_065 must not claim LL_06590."""
        return name == stem or name.startswith(f"{stem}__")

    def quiet(args):
        try:
            run(args)
        except RuntimeError:
            pass            # already gone

    # the pyramids: one purge each, reading only its own prefix
    for entry in _list(f"{DEST}/{prefix}", "--dirs-only"):
        folder = entry.rstrip("/")
        if not folder.endswith("_files"):
            continue
        if mine(folder[: -len("_files")]):
            quiet([rclone, "purge", f"{DEST}/{prefix}{folder}",
                   "--transfers", "64", "--checkers", "64", "--s3-no-check-bucket"])

    # the descriptors beside them, and the thumbnails
    for where, suffix in ((f"{DEST}/{prefix}", ".dzi"),
                          (f"{DEST}/thumbs/{prefix}", ".webp")):
        for name in _list(where, "--files-only"):
            if name.endswith(suffix) and mine(name[: -len(suffix)]):
                quiet([rclone, "deletefile", f"{where}{name}", "--s3-no-check-bucket"])


def purge_many(ids, log=print, done=None, workers=6):
    """
    Several at once. Each photograph is a separate prefix, so they do not
    contend, and the time is dominated by round trips rather than by anything
    this machine is doing.
    """
    with ThreadPoolExecutor(max_workers=min(workers, max(len(ids), 1))) as pool:
        for _ in pool.map(lambda pid: (purge(pid, log=log), done and done(pid)), ids):
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
