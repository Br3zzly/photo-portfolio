# Portfolio

Deep-zoom photography site. Photographs are served as tile pyramids so a
66 megapixel image opens in a few tens of kilobytes and sharpens as you zoom,
instead of downloading 35 MB up front.

Site is static and hosted on GitHub Pages. Tiles, thumbnails and the photo
manifest live in a Cloudflare R2 bucket, which has no egress fees.

## The admin console

Everything is done from one place:

```bash
python tools/admin.py
```

That opens your published gallery in a browser with the two controls the live
site must never have: a delete button on every photograph, and a way to add
more. It runs entirely on this machine, which is the point -- tiling needs
vips, and the credentials that write to the bucket are yours and stay here.
An admin panel on the published site would need both, and anyone could read
the second one out of it.

**Adding.** *Add photos…* opens a file picker; *Add folder as album…* picks a
whole folder and its name becomes the album. Dragging either onto the page
does the same. Then you walk what you picked: rotate anything the camera
tagged wrongly, fill in whatever it did not record, skip the frames you do not
want, and publish the rest.

Your originals are read, not taken. They are copied into `.staging/` for as
long as it takes to read the EXIF, build the pyramid and push it, and the copy
is deleted afterwards. Where you keep the originals is your business, and the
repository never holds one.

**Deleting.** The button on a tile removes that photograph's tiles and
thumbnail from the bucket, drops it from the manifest, and that is all. It
deletes every revision, not just the one the manifest names, so a photograph
re-tiled at some point leaves nothing behind. Nothing on this machine is
touched and your original is wherever you keep it -- but there is no undo, and
the metadata you typed is gone with it.

## Albums

An album is a folder you picked, named after the folder. Nothing to configure.
Albums appear as tiles in the same grid as loose photographs, with the album
name in the corner. Clicking one opens that album; prev/next then walk that
album rather than the whole collection. The cover is its newest photograph.

Only one level deep: a folder inside a picked folder is flattened into the
same album, because an id carries one folder name and no more.

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
this repository          the site, and the tools that publish to it
  index.html             the gallery
  assets/                its stylesheet and modules
  tools/admin.py         the console: pick, review, publish, delete
  tools/pipeline.py      EXIF, tiles, thumbnails, placeholders
  tools/store.py         the manifest, and the bucket

.staging/                a picked original, only while it is being worked on
tiles/  thumbs/          generated, uploaded, then deleted

R2 bucket/
  photos.json            the manifest, and the only record of a photograph
  name.dzi               tile pyramid descriptor
  name_files/            ~370 WebP tiles for a 66 MP photo, about 3 MB
  thumbs/name__rev.webp
```

Nothing here is a copy of anything. The originals live wherever you keep them,
the generated files are deleted once they are in the bucket, and the manifest
is the only record that a photograph exists.

That last part is worth being plain about: **the metadata you type by hand
exists only in `photos.json` in the bucket.** There is no sidecar beside the
original any more and no copy in git, so nothing can regenerate it. Delete a
photograph and its title, caption and settings go with it; publish it again and
you type them again. That was the deliberate trade for not keeping a source
folder.

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
- Export sRGB. The review step warns if a photo is not sRGB.
- GPS is never published. The review step warns if a source file has any.
- The console reads and writes the manifest through rclone rather than the
  public URL, so it uses the same credentials that write the bucket and never
  sees a stale CDN copy.
