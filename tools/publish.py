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

    return sorted(
        p for p in PHOTOS_DIR.iterdir()
        if p.suffix.lower() in SOURCE_TYPES and p.is_file()
    )


def process_one(src, args):
    """Returns the sidecar dict, or None if the user cancelled."""
    photo_id = src.stem
    print(f"\n  {src.name}")

    existing = pipeline.load_sidecar(photo_id)
    tiles_exist = (TILES_DIR / f"{photo_id}.dzi").exists()

    if existing and tiles_exist and not args.force:
        print("    already published - skipping (use --force to redo)")
        return existing

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

    print("    building preview...")
    thumb = pipeline.make_thumb(src, photo_id, force=True)

    print("    waiting for you to confirm metadata in the browser...")
    edited = review.review(data, thumb, warnings, open_browser=not args.no_browser)
    if edited is None:
        print("    cancelled - nothing published for this photo")
        return None

    edited["id"] = photo_id
    edited["width"], edited["height"] = data["width"], data["height"]

    print("    tiling...")
    t0 = time.time()
    (count, total), cached = pipeline.make_tiles(src, photo_id, force=args.force)
    verb = "reused" if cached else "built"
    print(f"    {verb} {count} tiles, {human(total)} in {time.time()-t0:.1f}s")

    edited["lqip"] = pipeline.make_lqip(src)
    pipeline.save_sidecar(photo_id, edited)
    print(f"    saved photos/{photo_id}.json")
    return edited


def build_manifest():
    """The manifest is generated from the sidecars, which are the real source."""
    photos = []
    for sidecar in sorted(PHOTOS_DIR.glob("*.json")):
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        if not (TILES_DIR / f"{data['id']}.dzi").exists():
            continue
        photos.append(data)

    # newest first; photos without a date sort last
    photos.sort(key=lambda d: d.get("date") or "", reverse=True)
    return {"photos": photos, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def upload(ids):
    rclone = find_tool("rclone")
    dest = f"{config.R2_REMOTE}:{config.R2_BUCKET}"

    for photo_id in ids:
        print(f"    uploading tiles for {photo_id}...")
        run([
            rclone, "copy",
            str(TILES_DIR / f"{photo_id}_files"), f"{dest}/{photo_id}_files/",
            "--transfers", "32", "--checkers", "32", "--s3-no-check-bucket",
            "--header-upload", f"Cache-Control: {config.TILE_CACHE_CONTROL}",
        ])
        run([
            rclone, "copyto",
            str(TILES_DIR / f"{photo_id}.dzi"), f"{dest}/{photo_id}.dzi",
            "--s3-no-check-bucket",
            "--header-upload", f"Cache-Control: {config.TILE_CACHE_CONTROL}",
        ])
        run([
            rclone, "copyto",
            str(THUMBS_DIR / f"{photo_id}.webp"), f"{dest}/thumbs/{photo_id}.webp",
            "--s3-no-check-bucket",
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

    print(f"  {len(sources)} photo{'s' if len(sources) != 1 else ''} to consider")

    published = []
    for src in sources:
        try:
            result = process_one(src, args)
        except RuntimeError as e:
            print(f"    FAILED: {e}")
            continue
        if result:
            published.append(result["id"])

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
