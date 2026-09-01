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

A white bar under each photograph. Camera maker and model on the left
with the lens beneath it, then on the right the maker's mark, the focal
length, aperture, shutter and ISO, and the date below those. Anything the
camera did not record is simply left out rather than shown blank, so a stacked
frame with no EXIF at all gets an empty bar.

The aperture is set with the hooked f. A shutter already written as a fraction
is left alone, since `1/100` needs no unit, while a bare `30` keeps its `s` so
it cannot be read as a thirtieth.

The mark is empty unless you have supplied artwork. Drop an SVG into
`assets/logos/` named after the maker -- `sony_logo_black.svg` -- and it
appears; see the README there. Nothing to rebuild, and no manufacturer artwork
ships with this repo.

The plate wraps rather than switching at a screen width, because the space it
has is the card's width and a portrait photograph makes a narrow card even on
a wide screen.

## Editing the site

The site is plain ES modules -- no build step, no dependencies to install.

```
index.html
assets/style.css
assets/app.js              entry point: view state and routing
assets/modules/manifest.js loading the manifest, and where the bucket URL lives
assets/modules/grid.js     the justified gallery
assets/modules/lightbox.js the card, the plate, and sizing
assets/modules/viewer.js   OpenSeadragon
```

Every URL the page loads carries a `?v=` query, and they are all set in
`index.html` -- the stylesheet link, the import map that names the modules, and
`app.js`. Bump that number whenever you change the CSS or any of the JS:

```bash
sed -i 's/?v=35/?v=36/g' index.html
```

A browser caches a file under its whole URL, query string and all, so
`style.css?v=28` is a file it has never seen and has to fetch. The server
ignores the query -- it hands back `assets/style.css` either way. Changing the
URL is the entire point.

What this does *not* do is get your change out any faster. Pages serves
everything, `index.html` included, with `Cache-Control: max-age=600`, and for
those ten minutes a browser does not even ask whether the file changed. Since
the version numbers live inside `index.html`, someone holding a cached copy of
it cannot see that you bumped them.

What it prevents is a mismatched pair. Left alone, `index.html` and
`style.css` are cached separately and fall out of date at different moments, so
a visitor can end up running new markup against an old stylesheet -- which
looks far worse than simply being ten minutes behind. Bumping guarantees that
new HTML can only ever point at assets the browser must go and fetch, so the
two always arrive as a set.

Tiles and thumbnails need none of this. Their paths carry a fingerprint of the
file's contents, so re-tiling a photo changes the URL by itself and they are
served `immutable` for a year. `?v=` is the same idea worked by hand, which is
the right trade when there is no build step to compute hashes.

Editing only `index.html` needs no bump; the browser re-checks that on its own.
And when you are testing your own changes, Ctrl+Shift+R ignores the cache
entirely -- which is why a change can look live to you and stale to everyone
else.

## Removing photographs

```bash
python tools/unpublish.py LL_06601
python tools/unpublish.py "LL_066*"        # patterns work
python tools/unpublish.py "LL_066*" --yes  # skip the confirmation
```

Deletes the tiles and thumbnail locally and from the bucket, drops the
sidecar, refreshes the manifest, and moves your original into `archive/` --
otherwise the next publish run would simply put it back. Nothing you shot is
ever deleted. Move the file back into `photos/` and publish again to undo.

Removing a lot at once is slow: each photo is a few hundred objects in the
bucket, so expect a minute or two per few thousand. It prints progress as it
goes.

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
- Tile paths carry a short fingerprint of the source file, its rotation and
  the encoder settings: `LL_06592__a1b2c3d4_files/`. Re-tiling a photo changes
  the fingerprint, so it becomes a new URL. That is what makes it safe to
  serve tiles as `immutable` for a year -- an edited photo can never collide
  with a cached copy of its old self. Thumbnails work the same way.
- The manifest is cached for a minute, so new photos appear quickly.
- Export sRGB. The publish script warns if a photo is not sRGB.
- GPS is never published. The script warns if a source file contains it.
