/* Entry point: loads the manifest, owns the view state, and keeps it in step
   with the URL.

   Three states, all expressible as a URL so any of them can be shared:
     /                  -> everything loose in the collection
     ?album=Kyoto       -> one album
     ?id=Kyoto/temple   -> a photograph, over whichever view it belongs to */

import { loadManifest } from "app/manifest";
import { initTheme } from "app/theme";
import { renderGrid, tileImageFor } from "app/grid";
import { initLightbox, showPhoto, hidePhoto, isOpen } from "app/lightbox";

const grid     = document.getElementById("grid");
const statusEl = document.getElementById("status");
const backBtn  = document.getElementById("back");

let photos = [];        // every published photograph, newest first
let albums = [];        // one entry per folder under photos/
let shown  = [];        // the photographs the current view shows, in order
let album  = null;      // album name while viewing one, otherwise null
let index  = -1;        // index into shown; -1 means nothing is open
let renderedFor;        // which view the grid currently holds
let booted = false;     // suppresses the morph on the very first route

initTheme(document.getElementById("theme-toggle"));
initLightbox({ onClose: closeToGallery, onStep: step });
backBtn.addEventListener("click", () => go(location.pathname));

boot();

async function boot() {
  try {
    ({ photos, albums } = await loadManifest());
  } catch (err) {
    statusEl.textContent =
      "Could not load the gallery. If this keeps happening the image host may be unreachable.";
    statusEl.classList.add("error");
    console.error(err);
    return;
  }

  if (!photos.length) {
    statusEl.textContent = "No photographs published yet.";
    return;
  }

  statusEl.hidden = true;
  window.addEventListener("popstate", route);
  route();
  booted = true;
}


/* --- routing ------------------------------------------------------------- */

function route() {
  const params = new URLSearchParams(location.search);
  const wantedId = params.get("id");
  const wantedAlbum = params.get("album") ||
    (wantedId && wantedId.includes("/") ? wantedId.split("/")[0] : null);

  const leaving = index;          // the tile to morph back into, if we close
  showView(wantedAlbum);

  if (wantedId) {
    const i = shown.findIndex((p) => p.id === wantedId);
    if (i >= 0) {
      open(i, booted ? tileFor(i) : null);
      return;
    }
  }

  if (isOpen()) hidePhoto({ toTile: tileFor(leaving) });
  index = -1;
}

function showView(name) {
  album = name && albums.some((a) => a.name === name) ? name : null;

  // Re-rendering on every route change would reset the scroll position each
  // time a photograph is closed. Only rebuild when the view actually changed.
  if (renderedFor === album) return;
  renderedFor = album;

  shown = album
    ? photos.filter((p) => p.album === album)
    : photos.filter((p) => !p.album);

  // the only chrome on the page: a way back out of an album
  backBtn.hidden = !album;

  renderGrid(grid, {
    photos: shown,
    albums: album ? [] : albums,
    onPhoto: (photo, i, img) => {
      open(i, img);
      history.pushState({}, "", photoUrl(photo.id));
    },
    onAlbum: (a) => go(`${location.pathname}?album=${encodeURIComponent(a.name)}`),
  });
}

function go(url) {
  history.pushState({}, "", url);
  route();
}

const photoUrl = (id) => `${location.pathname}?id=${encodeURIComponent(id)}`;

/* Albums are rendered before photographs in the same grid, so a photograph's
   tile sits that many children further along. */
const tileFor = (i) =>
  i < 0 ? null : tileImageFor(grid, i, album ? 0 : albums.length);


/* --- the open photograph -------------------------------------------------
   Opens from the current view, so prev/next walk the album you are in rather
   than the whole collection.
   ------------------------------------------------------------------------- */

function open(i, fromTile) {
  if (i < 0 || i >= shown.length) return;
  index = i;
  showPhoto(shown[i], {
    hasPrev: i > 0,
    hasNext: i < shown.length - 1,
    fromTile,
  });
}

function step(delta) {
  const next = index + delta;
  if (next < 0 || next >= shown.length) return;
  // no morph when stepping: the card animates between the two shapes instead
  open(next, null);
  history.replaceState({}, "", photoUrl(shown[next].id));
}

/* The close button goes back to whichever view the photograph came from. */
function closeToGallery() {
  go(album
    ? `${location.pathname}?album=${encodeURIComponent(album)}`
    : location.pathname);
}
