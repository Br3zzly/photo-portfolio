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

It reads the EXIF from every new photo, then opens **one page in one tab**
where you walk the whole batch: arrow keys to move, `S` to skip a frame you do
not want published, `Ctrl+Enter` when you are done. After that it tiles
everything you kept, uploads to R2 and refreshes the manifest without further
input. No commit required.

Re-running is always safe. Already-published photos are skipped, and the
upload syncs everything the manifest references -- so an interrupted run is
fixed simply by running it again.

Useful flags:

| Flag | What it does |
|---|---|
| `--force` | Redo tiles and metadata that already exist |
| `--no-upload` | Process locally, upload later |
| `--no-browser` | Print the review URL instead of opening a browser |

You can also name a single file: `python tools/publish.py photos/whatever.jpg`

## Albums

A subfolder of `photos/` is an album, named after the folder. Nothing to
configure.

```
photos/
  sunset.jpg          loose -- appears on the home page
  Kyoto/
    temple.jpg        album "Kyoto"
    garden.jpg
  Hong Kong/
    tram.jpg          album "Hong Kong"
```

Albums appear as tiles in the same grid as loose photographs, with the album
name in the corner. Clicking one opens that album; clicking a photo opens the
viewer, and prev/next then walk that album rather than the whole collection.

The album cover is its newest photo. Rename the folder to rename the album --
though the old tiles stay in the bucket under the old name until you delete
them, since the folder name is part of each photo's id.

## The plate

Under each photograph: camera maker and model in bold, then lens, focal
length, aperture, shutter and ISO in grey, with the maker's mark on the right.
Anything the camera did not record is simply left out rather than shown blank.

The mark is the maker's name as a wordmark by default. Drop an SVG into
`assets/logos/` (see the README there) to use real artwork instead.

## Editing the site

`index.html` loads the CSS and JS with a `?v=` query. Bump it whenever you
change either file, otherwise GitHub Pages will keep serving the cached copy
for about ten minutes and your change will look like it did not work.

## Theme

Dark by default if that is your system setting, light otherwise. The toggle in
the corner overrides it and the choice is remembered per browser.

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
