"""
Publish photos to the site.

    python tools/publish.py                  # every new photo in photos/
    python tools/publish.py photos/test.jpg  # just this one
    python tools/publish.py --force          # redo work that already exists
    python tools/publish.py --no-upload      # process locally, upload later

For each photo: read EXIF, show a review form, then tile, upload, and refresh
the manifest. Safe to re-run -- nothing is duplicated or redone unnecessarily.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import config
import pipeline
import review
from pipeline import ROOT, PHOTOS_DIR, TILES_DIR, THUMBS_DIR, find_tool, run

SOURCE_TYPES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def photo_id_for(src):
    """
    A subfolder of photos/ is an album, and its name becomes part of the id:

        photos/sunset.jpg        -> "sunset"          (no album)
        photos/Kyoto/temple.jpg  -> "Kyoto/temple"    (album "Kyoto")

    Keeping the album in the id means two albums can both hold a DSC01234.jpg
    without colliding, in the manifest or in the bucket.
    """
    src = Path(src).resolve()
    try:
        rel = src.relative_to(PHOTOS_DIR.resolve())
    except ValueError:
        return src.stem, ""          # a file from outside photos/

    if len(rel.parts) == 1:
        return rel.stem, ""
    album = rel.parts[0]
    return f"{album}/{rel.stem}", album


def find_sources(args):
    if args.paths:
        out = []
        for raw in args.paths:
            p = Path(raw)
            if not p.exists():
                sys.exit(f"  no such file: {raw}")
            out.append(p)
        return out

    if not PHOTOS_DIR.is_dir():
        sys.exit(f"  no photos/ directory at {PHOTOS_DIR}")

    # loose photos first, then each album folder in name order
    loose = sorted(
        p for p in PHOTOS_DIR.iterdir()
        if p.suffix.lower() in SOURCE_TYPES and p.is_file()
    )
    grouped = []
    for folder in sorted(d for d in PHOTOS_DIR.iterdir() if d.is_dir()):
        grouped.extend(sorted(
            p for p in folder.iterdir()
            if p.suffix.lower() in SOURCE_TYPES and p.is_file()
        ))
    return loose + grouped


def prepare(src, args):
    """
    Everything that must happen before you can review a photo: work out its
    id, read the EXIF, build the preview. Returns None if it is already
    published and does not need looking at again.
    """
    photo_id, album = photo_id_for(src)

    existing = pipeline.load_sidecar(photo_id)
    tiles_exist = (TILES_DIR / f"{photo_id}.dzi").exists()
    if existing and tiles_exist and not args.force:
        return None

    warnings = []
    profile = pipeline.colour_profile(src)
    if profile and not pipeline.is_srgb(src):
        warnings.append(
            f"Colour profile is '{profile}', not sRGB. Colours may render wrong "
            f"in some browsers — re-export as sRGB if this photo looks off."
        )
    if pipeline.has_gps(src):
        warnings.append(
            "This file contains GPS coordinates. They will NOT be published, "
            "but consider stripping them from your export too."
        )

    data = existing or pipeline.init_sidecar(src, photo_id)
    if existing:
        # refresh dimensions in case the source was re-exported
        data["width"], data["height"] = pipeline.dimensions(src)

    labels = {k: label for k, label, _ in config.METADATA_FIELDS}
    missing = [labels[k] for k in config.EXIF_FIELDS if not data.get(k)]
    if missing:
        warnings.append(
            "The camera did not record: " + ", ".join(missing) +
            ". Stacked or heavily edited exports often lose this — fill in "
            "whatever you know, or leave blank to hide those fields."
        )

    thumb = pipeline.make_thumb(src, photo_id, force=True)

    return {
        "id": photo_id, "album": album, "src": src,
        "data": data, "thumb": thumb, "warnings": warnings,
    }


def finish(item, edited, args):
    """Tile, place the metadata, and write the sidecar. No interaction."""
    photo_id, src, album = item["id"], item["src"], item["album"]

    edited["id"] = photo_id
    edited["width"] = item["data"]["width"]
    edited["height"] = item["data"]["height"]
    if album:
        edited["album"] = album
    else:
        edited.pop("album", None)   # a photo moved out of a folder loses it

    t0 = time.time()
    (count, total), cached = pipeline.make_tiles(src, photo_id, force=args.force)
    verb = "reused" if cached else "built"
    print(f"    {photo_id}: {verb} {count} tiles, {human(total)} "
          f"in {time.time()-t0:.1f}s")

    edited["lqip"] = pipeline.make_lqip(src)
    pipeline.save_sidecar(photo_id, edited)
    return edited


def build_manifest():
    """The manifest is generated from the sidecars, which are the real source."""
    photos = []
    for sidecar in sorted(PHOTOS_DIR.rglob("*.json")):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        if not (TILES_DIR / f"{data['id']}.dzi").exists():
            continue
        photos.append(data)

    # newest first; photos without a date sort last
    photos.sort(key=lambda d: d.get("date") or "", reverse=True)

    # One entry per album folder. The cover is the album's newest photo, which
    # is simply the first one to appear after the sort above.
    albums = []
    for photo in photos:
        name = photo.get("album")
        if not name:
            continue
        existing = next((a for a in albums if a["name"] == name), None)
        if existing:
            existing["count"] += 1
        else:
            albums.append({
                "name": name,
                "cover": photo["id"],
                "coverWidth": photo.get("width"),
                "coverHeight": photo.get("height"),
                "coverLqip": photo.get("lqip", ""),
                "count": 1,
                "date": photo.get("date", ""),
            })

    albums.sort(key=lambda a: a.get("date") or "", reverse=True)

    return {
        "photos": photos,
        "albums": albums,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def upload(ids):
    """
    Push everything the manifest will reference, not just this run's photos.

    The manifest is built from every sidecar on disk, so uploading only what
    was just published would leave earlier photos listed but missing from the
    bucket -- which is exactly what an interrupted run produces. Syncing the
    whole tiles and thumbs directories is also far quicker than per-photo
    calls, and rclone skips anything already there.
    """
    rclone = find_tool("rclone")
    dest = f"{config.R2_REMOTE}:{config.R2_BUCKET}"

    print("    syncing tiles (already-uploaded files are skipped)...")
    run([
        rclone, "copy", str(TILES_DIR), f"{dest}/",
        "--transfers", "48", "--checkers", "48", "--s3-no-check-bucket",
        "--exclude", "*.tmp", "--exclude", ".*",
        "--header-upload", f"Cache-Control: {config.TILE_CACHE_CONTROL}",
        "--stats-one-line", "--stats", "15s",
    ])

    print("    syncing thumbnails...")
    run([
        rclone, "copy", str(THUMBS_DIR), f"{dest}/thumbs/",
        "--transfers", "48", "--checkers", "48", "--s3-no-check-bucket",
        "--header-upload", f"Cache-Control: {config.TILE_CACHE_CONTROL}",
    ])

    manifest = build_manifest()
    tmp = ROOT / ".manifest.tmp.json"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    print(f"    uploading manifest ({len(manifest['photos'])} photos)...")
    run([
        rclone, "copyto", str(tmp), f"{dest}/{config.MANIFEST_NAME}",
        "--s3-no-check-bucket",
        "--header-upload", f"Cache-Control: {config.MANIFEST_CACHE_CONTROL}",
    ])
    tmp.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description="Publish photos to the portfolio.")
    ap.add_argument("paths", nargs="*", help="specific photos; default is all new ones")
    ap.add_argument("--force", action="store_true", help="redo tiles and metadata that already exist")
    ap.add_argument("--no-upload", action="store_true", help="process locally, skip Cloudflare")
    ap.add_argument("--no-browser", action="store_true", help="print the review URL instead of opening a browser")
    args = ap.parse_args()

    sources = find_sources(args)
    if not sources:
        print("  no photos found in photos/")
        return

    print(f"  {len(sources)} photo{'s' if len(sources) != 1 else ''} in photos/")

    # 1. read metadata and build previews for everything that is new
    items = []
    for src in sources:
        try:
            item = prepare(src, args)
        except RuntimeError as e:
            print(f"    {src.name} FAILED: {e}")
            continue
        if item:
            items.append(item)
            print(f"    ready: {item['id']}"
                  + (f"   [album: {item['album']}]" if item["album"] else ""))

    if not items:
        print("\n  nothing new - everything here is already published")
        return

    # 2. review them all in one page, in one tab
    edits = review.review_all(items, open_browser=not args.no_browser)
    if edits is None:
        print("\n  cancelled - nothing published")
        return

    skipped = len(items) - len(edits)
    if skipped:
        print(f"\n  skipped {skipped} photo{'s' if skipped != 1 else ''}")
    if not edits:
        print("  nothing left to publish")
        return

    # 3. tile everything you kept, unattended
    print(f"\n  tiling {len(edits)} photo(s)...")
    published = []
    for item in items:
        if item["id"] not in edits:
            continue
        try:
            finish(item, edits[item["id"]], args)
            published.append(item["id"])
        except RuntimeError as e:
            print(f"    {item['id']} FAILED: {e}")

    if not published:
        print("\n  nothing to publish")
        return

    if args.no_upload:
        print(f"\n  processed {len(published)} photo(s); skipped upload as asked")
        print("  run again without --no-upload to push to Cloudflare")
        return

    print("\n  uploading to Cloudflare...")
    upload(published)
    print(f"\n  done - {len(published)} photo(s) live")
    print(f"  manifest: {config.R2_PUBLIC_URL}/{config.MANIFEST_NAME}")


if __name__ == "__main__":
    main()
