"""
Take photographs off the site.

    python tools/unpublish.py LL_06601
    python tools/unpublish.py "LL_066*"          # patterns work
    python tools/unpublish.py Moon/muun          # album photos by full id
    python tools/unpublish.py "LL_066*" --yes    # skip the confirmation

For each one this removes the tiles and thumbnail, locally and from the
bucket, deletes the sidecar, and moves your original into archive/ so the next
publish run does not simply put it back. Then it refreshes the manifest.

Your original photograph is never deleted -- only moved. Move it back into
photos/ and publish again to undo.
"""

import argparse
import fnmatch
import json
import shutil
import sys
from pathlib import Path

import config
import pipeline
import publish
from pipeline import ROOT, PHOTOS_DIR, TILES_DIR, THUMBS_DIR, find_tool, run

ARCHIVE_DIR = ROOT / "archive"


def published_ids():
    """Every photo currently backed by a sidecar."""
    out = []
    for sidecar in sorted(PHOTOS_DIR.rglob("*.json")):
        try:
            out.append(json.loads(sidecar.read_text(encoding="utf-8"))["id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return out


def resolve(patterns):
    known = published_ids()
    matched, unmatched = [], []
    for pat in patterns:
        hits = [i for i in known if i == pat or fnmatch.fnmatch(i, pat)]
        if hits:
            matched.extend(hits)
        else:
            unmatched.append(pat)
    # de-duplicate, keep order
    seen = set()
    return [i for i in matched if not (i in seen or seen.add(i))], unmatched


def source_for(photo_id):
    """Find the original file a sidecar refers to."""
    stem = Path(photo_id).name
    folder = PHOTOS_DIR / Path(photo_id).parent
    for p in folder.glob(f"{stem}.*"):
        if p.suffix.lower() in publish.SOURCE_TYPES:
            return p
    return None


def remove(photo_id, keep_original):
    freed = 0

    # tiles live under a content-versioned stem, and there may be more than
    # one revision lying around
    parent = (TILES_DIR / photo_id).parent
    stem = Path(photo_id).name
    if parent.is_dir():
        for p in list(parent.glob(f"{stem}__*")):
            if p.is_dir():
                freed += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                shutil.rmtree(p, ignore_errors=True)
            else:
                freed += p.stat().st_size
                p.unlink(missing_ok=True)

    thumb = THUMBS_DIR / f"{photo_id}.webp"
    if thumb.exists():
        freed += thumb.stat().st_size
        thumb.unlink()

    pipeline.sidecar_path(photo_id).unlink(missing_ok=True)

    # the original is moved, never deleted
    src = source_for(photo_id)
    if src and not keep_original:
        dest = ARCHIVE_DIR / Path(photo_id).parent
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / src.name
        if target.exists():
            target.unlink()
        shutil.move(str(src), str(target))

    return freed, src


def purge_remote(ids):
    """
    Delete the tiles and thumbnails from R2.

    This is by far the slowest part -- a photo is a few hundred objects, so a
    big removal is thousands of API calls and takes minutes. It reports every
    photo as it goes, because a silent multi-minute pause is indistinguishable
    from a hang.
    """
    rclone = find_tool("rclone")
    dest = f"{config.R2_REMOTE}:{config.R2_BUCKET}"
    total = len(ids)

    for n, photo_id in enumerate(ids, 1):
        print(f"    [{n}/{total}] {photo_id}", flush=True)
        # every revision of this photo, whatever its fingerprint
        parent = str(Path(photo_id).parent).replace("\\", "/")
        prefix = "" if parent == "." else parent + "/"
        stem = Path(photo_id).name
        try:
            run([rclone, "delete", f"{dest}/{prefix}",
                 "--include", f"{stem}__*_files/**",
                 "--include", f"{stem}__*.dzi",
                 "--transfers", "48", "--checkers", "48",
                 "--rmdirs", "--s3-no-check-bucket"])
        except RuntimeError:
            pass          # already gone
        try:
            run([rclone, "deletefile", f"{dest}/thumbs/{photo_id}.webp",
                 "--s3-no-check-bucket"])
        except RuntimeError:
            pass


def main():
    ap = argparse.ArgumentParser(description="Remove photographs from the site.")
    ap.add_argument("patterns", nargs="+", help="photo ids, or patterns like 'LL_066*'")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    ap.add_argument("--keep-original", action="store_true",
                    help="leave the source in photos/ (it will be republished next run)")
    ap.add_argument("--local-only", action="store_true",
                    help="do not touch the bucket, only clean up locally")
    args = ap.parse_args()

    ids, unmatched = resolve(args.patterns)
    for pat in unmatched:
        print(f"  no published photo matches: {pat}")
    if not ids:
        sys.exit("  nothing to remove")

    print(f"\n  about to remove {len(ids)} photo(s) from the site:")
    for i in ids[:20]:
        print(f"    {i}")
    if len(ids) > 20:
        print(f"    ... and {len(ids) - 20} more")

    print("\n  tiles and thumbnails will be deleted locally"
          + ("" if args.local_only else " and from Cloudflare"))
    print("  your original photographs will be moved to archive/"
          if not args.keep_original else "  your originals stay in photos/")

    if not args.yes:
        if input("\n  type 'yes' to continue: ").strip().lower() != "yes":
            sys.exit("  cancelled")

    total = 0
    for photo_id in ids:
        freed, src = remove(photo_id, args.keep_original)
        total += freed
        where = "archived" if src and not args.keep_original else "kept"
        print(f"    removed {photo_id}  ({publish.human(freed)}, original {where})")

    if not args.local_only:
        print("\n  deleting from Cloudflare...")
        purge_remote(ids)

    manifest = publish.build_manifest()
    print(f"\n  manifest now lists {len(manifest['photos'])} photo(s)")

    if not args.local_only:
        tmp = ROOT / ".manifest.tmp.json"
        tmp.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        run([
            find_tool("rclone"), "copyto", str(tmp),
            f"{config.R2_REMOTE}:{config.R2_BUCKET}/{config.MANIFEST_NAME}",
            "--s3-no-check-bucket",
            "--header-upload", f"Cache-Control: {config.MANIFEST_CACHE_CONTROL}",
        ])
        tmp.unlink(missing_ok=True)
        print("  manifest updated - the site reflects this within a minute")

    print(f"\n  freed {publish.human(total)} locally")


if __name__ == "__main__":
    main()
