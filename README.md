# Portfolio

Deep-zoom photography site. Photographs are served as tile pyramids so a
66 megapixel image opens in a few tens of kilobytes and sharpens as you zoom,
instead of downloading 35 MB up front.

Site is static and hosted on GitHub Pages. Tiles, thumbnails and the photo
manifest live in a Cloudflare R2 bucket, which has no egress fees.

## Publishing a photo

Drop a full-resolution JPEG into `photos/`, then:

```bash
python tools/publish.py
```

That reads the EXIF, opens a form in your browser so you can check and correct
the metadata, then tiles the photo, uploads everything to R2, and refreshes the
manifest. The photo is live as soon as it finishes. No commit required.

Useful flags:

| Flag | What it does |
|---|---|
| `--force` | Redo tiles and metadata that already exist |
| `--no-upload` | Process locally, upload later |
| `--no-browser` | Print the review URL instead of opening a browser |

You can also name a single file: `python tools/publish.py photos/whatever.jpg`

## Requirements

```bash
winget install libvips.libvips
winget install Rclone.Rclone
winget install OliverBetz.ExifTool
```

Then `rclone config` once, to create a remote named `r2` pointing at the
bucket. Settings live in `tools/config.py`.

## How it fits together

```
photos/name.jpg          your original, never committed
photos/name.json         metadata you confirmed -- committed, this is the backup
tiles/name_files/        generated pyramid, uploaded to R2, never committed
thumbs/name.webp         gallery thumbnail, uploaded to R2, never committed

R2 bucket/
  photos.json            the manifest the site reads at runtime
  name.dzi               tile pyramid descriptor
  name_files/            ~370 WebP tiles for a 66 MP photo, about 3 MB
  thumbs/name.webp
```

The site fetches `photos.json` from the bucket on load, so publishing never
touches this repository. The sidecar JSON files are committed purely as a
backup of metadata you typed by hand.

## Notes

- Tiles are WebP quality 90 at 512 px with 1 px overlap. Quality 90 was chosen
  after comparing 80/90/lossless on real files: on detailed content 90 costs
  only 8-31% more than 80, while lossless costs 26x for no visible gain.
- Tiles are immutable and cached for a year. The manifest is cached for a
  minute so new photos appear quickly.
- Export sRGB. The publish script warns if a photo is not sRGB.
- GPS is never published. The script warns if a source file contains it.
