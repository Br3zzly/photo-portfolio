/* ---------------------------------------------------------------------------
   Gallery + deep-zoom lightbox. No framework, no build step.

   The manifest lives in the R2 bucket alongside the tiles, so publishing a
   photo never touches this repository.
   --------------------------------------------------------------------------- */

const BUCKET = "https://pub-9775c4eec7a34ee9bedf8364e574d557.r2.dev";

const el = (id) => document.getElementById(id);

const grid        = el("grid");
const status      = el("status");
const lightbox    = el("lightbox");
const stage       = el("stage");
const placeholder = el("placeholder");
const viewerEl    = el("viewer");
const card        = el("card");
const plate       = el("plate");
const prevBtn     = el("prev");
const nextBtn     = el("next");

let photos = [];     // every published photo, newest first
let albums = [];     // one entry per folder under photos/
let shown = [];      // the photos the current view is showing, in order
let album = null;    // album name when viewing one, otherwise null
let index = -1;      // index into `shown`; -1 means no photo is open
let viewer = null;   // the OpenSeadragon instance, created once and reused
let idleTimer = null;


/* --- theme ---------------------------------------------------------------
   Follows the system until the visitor chooses, then remembers the choice.
   The <head> script has already applied any saved value.
   ------------------------------------------------------------------------- */

function currentTheme() {
  const explicit = document.documentElement.getAttribute("data-theme");
  if (explicit) return explicit;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

el("theme-toggle").addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("theme", next); } catch (e) { /* private mode */ }
});

// enable colour transitions only after first paint
requestAnimationFrame(() =>
  document.documentElement.classList.add("theme-ready")
);


/* --- boot ---------------------------------------------------------------- */

init();

async function init() {
  try {
    const res = await fetch(`${BUCKET}/photos.json`, { cache: "no-cache" });
    if (!res.ok) throw new Error(`manifest returned ${res.status}`);
    const data = await res.json();
    photos = Array.isArray(data) ? data : data.photos || [];
    albums = (Array.isArray(data) ? [] : data.albums) || [];
  } catch (err) {
    status.textContent =
      "Could not load the gallery. If this keeps happening the image host may be unreachable.";
    status.classList.add("error");
    console.error(err);
    return;
  }

  if (!photos.length) {
    status.textContent = "No photographs published yet.";
    return;
  }

  status.hidden = true;
  window.addEventListener("popstate", route);
  route({ replace: true });
}


/* --- routing -------------------------------------------------------------
   Three states, all expressible as a URL so any of them can be shared:
     /                -> everything
     ?album=Kyoto     -> one album
     ?id=Kyoto/temple -> a photo, opened over whichever view it belongs to
   ------------------------------------------------------------------------- */

function route() {
  const params = new URLSearchParams(location.search);
  const wantedId = params.get("id");
  const wantedAlbum = params.get("album") ||
    (wantedId && wantedId.includes("/") ? wantedId.split("/")[0] : null);

  showView(wantedAlbum);

  if (wantedId) {
    const i = shown.findIndex((p) => p.id === wantedId);
    if (i >= 0) { openAt(i); return; }
  }
  closeLightbox();
}

let renderedFor = undefined;   // which album the grid currently shows

function showView(name) {
  album = name && albums.some((a) => a.name === name) ? name : null;

  // Re-rendering on every route change would reset the scroll position every
  // time a photo is closed. Only rebuild when the view actually changed.
  if (renderedFor === album) return;
  renderedFor = album;

  shown = album
    ? photos.filter((p) => p.album === album)
    : photos.filter((p) => !p.album);

  // the only chrome on the page: a way back out of an album
  el("back").hidden = !album;

  renderGrid();
}

function go(url) {
  history.pushState({}, "", url);
  route();
}


/* --- gallery ------------------------------------------------------------- */

function renderGrid() {
  grid.replaceChildren();
  const frag = document.createDocumentFragment();

  // On the home view, albums sit in the same grid as loose photographs.
  if (!album) {
    albums.forEach((a) => frag.appendChild(albumTile(a)));
  }

  shown.forEach((photo, i) => frag.appendChild(photoTile(photo, i)));
  grid.appendChild(frag);
  window.scrollTo({ top: 0 });
}

function tileShell(ar, label) {
  const tile = document.createElement("button");
  tile.className = "tile";
  tile.style.setProperty("--ar", ar.toFixed(4));
  tile.setAttribute("role", "listitem");
  tile.setAttribute("aria-label", label);
  return tile;
}

function thumbImg(id, rev, w, h, lqip, alt) {
  const img = document.createElement("img");
  img.loading = "lazy";
  img.decoding = "async";
  img.width = w || 0;
  img.height = h || 0;
  img.alt = alt || "";
  // the inlined placeholder paints immediately, so tiles are never empty
  if (lqip) img.style.backgroundImage = `url("${lqip}")`;
  img.src = `${BUCKET}/thumbs/${rev ? `${id}__${rev}` : id}.webp`;

  const reveal = () => img.classList.add("ready");
  if (img.complete) reveal();
  else img.addEventListener("load", reveal, { once: true });
  return img;
}

function photoTile(photo, i) {
  const ar = (photo.width || 3) / (photo.height || 2);
  const tile = tileShell(ar, photo.title || photo.id);
  tile.appendChild(
    thumbImg(photo.id, photo.rev, photo.width, photo.height, photo.lqip, photo.title)
  );
  tile.addEventListener("click", () => {
    openAt(i);
    history.pushState({}, "", `${location.pathname}?id=${encodeURIComponent(photo.id)}`);
  });
  return tile;
}

function albumTile(a) {
  const ar = (a.coverWidth || 3) / (a.coverHeight || 2);
  const tile = tileShell(ar, `Album: ${a.name}`);
  tile.classList.add("album");
  tile.appendChild(
    thumbImg(a.cover, a.coverRev, a.coverWidth, a.coverHeight, a.coverLqip, "")
  );

  const label = document.createElement("span");
  label.className = "album-label";
  const name = document.createElement("span");
  name.className = "album-name";
  name.textContent = a.name;
  const count = document.createElement("span");
  count.className = "album-count";
  count.textContent = a.count;
  label.append(name, count);
  tile.appendChild(label);

  tile.addEventListener("click", () =>
    go(`${location.pathname}?album=${encodeURIComponent(a.name)}`)
  );
  return tile;
}


/* --- lightbox ------------------------------------------------------------ */

/* Opens a photo from the current view. Prev/next therefore walk the album you
   are in, not the whole collection. */
function openAt(i) {
  if (i < 0 || i >= shown.length) return;
  const photo = shown[i];
  index = i;

  lightbox.hidden = false;
  document.body.classList.add("lightbox-open");
  requestAnimationFrame(() => lightbox.classList.add("open"));

  placeholder.src = photo.lqip || "";
  placeholder.classList.remove("hidden");
  viewerEl.classList.remove("ready");

  fillMeta(photo);
  prevBtn.disabled = i === 0;
  nextBtn.disabled = i === shown.length - 1;

  sizeCard();
  showTiles(photo);
}

/* Tears the lightbox down without touching history. */
function closeLightbox() {
  if (index < 0) return;
  index = -1;
  lightbox.classList.remove("open", "interacting");
  document.body.classList.remove("lightbox-open");
  setTimeout(() => {
    lightbox.hidden = true;
    if (viewer) viewer.close();
  }, 280);
}

/* The close button goes back to whichever view the photo came from. */
function close() {
  go(album
    ? `${location.pathname}?album=${encodeURIComponent(album)}`
    : location.pathname);
}

function step(delta) {
  const next = index + delta;
  if (next < 0 || next >= shown.length) return;
  openAt(next);
  history.replaceState({}, "", `${location.pathname}?id=${encodeURIComponent(shown[next].id)}`);
}

/* The plate under the photograph:
     left, bold  -- camera maker + model
     left, grey  -- lens, focal length, aperture, shutter, ISO
     right       -- the maker's mark
   Everything is built from what exists, so a stacked frame with no lens or
   shutter collapses to what it has rather than rendering empty slots. */
function fillMeta(photo) {
  el("m-camera").textContent = photo.camera || "";

  const parts = [
    photo.lens,
    photo.focal,
    photo.aperture,
    photo.shutter ? `${photo.shutter}s` : "",
    photo.iso ? `ISO ${photo.iso}` : "",
    ...Object.values(photo.extra || {}).filter(Boolean),
  ].filter(Boolean);

  // separate elements, not a joined string -- HTML collapses runs of spaces,
  // so the gaps have to come from CSS
  el("m-spec").replaceChildren(
    ...parts.map((p) => {
      const s = document.createElement("span");
      s.textContent = p;
      return s;
    })
  );

  el("m-mark").replaceChildren(makerMark(photo));
}

/* Uses assets/logos/<maker>.svg when you have supplied one, otherwise sets the
   maker's name as a wordmark. No manufacturer artwork ships with this repo. */
function makerMark(photo) {
  const make = (photo.make || (photo.camera || "").split(/\s+/)[0] || "").trim();
  if (!make) return document.createDocumentFragment();

  const word = document.createElement("span");
  word.className = "wordmark";
  word.textContent = make;

  const slug = make.toLowerCase().replace(/[^a-z0-9]+/g, "");
  const img = document.createElement("img");
  img.alt = make;
  img.addEventListener("error", () => img.replaceWith(word), { once: true });
  img.src = `assets/logos/${slug}.svg`;
  return img;
}


/* --- sizing --------------------------------------------------------------
   The card is laid out from the photograph's aspect ratio rather than left to
   the browser, because the plate's height is only known after it is filled.
   ------------------------------------------------------------------------- */

function sizeCard() {
  if (index < 0) return;
  const photo = shown[index];
  if (!photo) return;

  const ar = (photo.width || 3) / (photo.height || 2);
  const cs = getComputedStyle(stage);

  // Measured from the lightbox, never from the stage. The stage is sized by
  // its own content, so measuring it would feed the card's current size back
  // into the calculation and let it grow without bound.
  const availW = lightbox.clientWidth
    - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
  const availH = lightbox.clientHeight
    - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);

  // two passes: the plate can wrap, so its height depends on the width we pick
  let w = availW;
  for (let pass = 0; pass < 2; pass++) {
    card.style.width = `${Math.round(w)}px`;
    const plateH = plate.offsetHeight;
    let frameH = w / ar;
    if (frameH > availH - plateH) {
      frameH = availH - plateH;
      w = Math.min(availW, frameH * ar);
    }
    card.style.width = `${Math.round(w)}px`;
    card.style.height = `${Math.round(w / ar + plateH)}px`;
  }
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(sizeCard, 120);
});

// the stage's padding animates when entering and leaving full-bleed; the card
// can only be measured accurately once it has finished
stage.addEventListener("transitionend", (e) => {
  if (e.target === stage && e.propertyName.startsWith("padding")) {
    clearTimeout(resizeTimer);
    sizeCard();
  }
});


/* --- deep zoom ----------------------------------------------------------- */

function showTiles(photo) {
  // the tile path carries a fingerprint of the source, so re-tiling a photo
  // produces a new URL rather than quietly colliding with a cached copy
  const source = photo.rev
    ? `${BUCKET}/${photo.id}__${photo.rev}.dzi`
    : `${BUCKET}/${photo.id}.dzi`;

  if (!viewer) {
    viewer = makeViewer(source);
    wireViewer();
  } else {
    viewer.open(source);
  }
}

function makeViewer(tileSources) {
  const base = {
    element: viewerEl,
    tileSources,
    prefixUrl: "",            // no default UI images; we supply our own chrome
    showNavigationControl: false,
    showNavigator: false,
    crossOriginPolicy: "Anonymous",
    gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: false },
    gestureSettingsTouch: { pinchRotate: false, clickToZoom: false, dblClickToZoom: false },
    maxZoomPixelRatio: 2,
    minZoomImageRatio: 0.9,
    visibilityRatio: 1,
    constrainDuringPan: true,
    springStiffness: 7.5,
    animationTime: 0.9,
    immediateRender: false,
    preserveImageSizeOnResize: true,
    // keep memory bounded on phones
    maxImageCacheCount: 220,
  };

  // The WebGL drawer holds 1:1 zoom far better on iOS. Fall back silently.
  try {
    return OpenSeadragon({ ...base, drawer: "webgl" });
  } catch (err) {
    console.warn("WebGL drawer unavailable, using canvas", err);
    return OpenSeadragon(base);
  }
}

function wireViewer() {
  viewer.addHandler("open", () => {
    viewerEl.classList.add("ready");
    setTimeout(() => placeholder.classList.add("hidden"), 220);
  });

  viewer.addHandler("open-failed", () => {
    // leave the blurred placeholder up rather than showing a broken frame
    viewerEl.classList.remove("ready");
  });

  viewer.addHandler("canvas-double-click", (ev) => {
    ev.preventDefaultAction = true;
    toggleZoom(ev.position);
  });

  // chrome fades while you are actually moving the image around
  ["canvas-drag", "canvas-scroll", "canvas-pinch"].forEach((evt) =>
    viewer.addHandler(evt, markInteracting)
  );

  viewer.addHandler("animation-finish", () =>
    lightbox.classList.remove("interacting")
  );
}

function markInteracting() {
  lightbox.classList.add("interacting");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => lightbox.classList.remove("interacting"), 1400);

}

/* The photograph never leaves the card, so the card never changes size, so
   this can be read straight off the viewer without the feedback loop that
   the old full-bleed mode had. */
function isZoomedIn() {
  if (!viewer || !viewer.world.getItemCount()) return false;
  return viewer.viewport.getZoom(true) > viewer.viewport.getHomeZoom() * 1.05;
}

/* Double-click toggles between fit and 1:1, inside the card. */
function toggleZoom(point) {
  const item = viewer.world.getItemAt(0);
  if (!item) return;

  if (isZoomedIn()) {
    viewer.viewport.goHome();
    return;
  }

  const full = item.imageToViewportZoom(1);
  const home = viewer.viewport.getHomeZoom();
  const target = full > home * 1.05 ? full : home * 2;
  viewer.viewport.zoomTo(
    target, point ? viewer.viewport.pointFromPixel(point) : null
  );
}


/* --- input --------------------------------------------------------------- */

el("close").addEventListener("click", close);
prevBtn.addEventListener("click", () => step(-1));
nextBtn.addEventListener("click", () => step(1));

document.addEventListener("keydown", (e) => {
  if (index < 0) return;

  if (e.key === "Escape") {
    // first Escape leaves a zoom, second closes the photo
    if (isZoomedIn()) {
      viewer.viewport.goHome();
    } else {
      close();
    }
  } else if (e.key === "ArrowLeft" && !isZoomedIn()) {
    step(-1);
  } else if (e.key === "ArrowRight" && !isZoomedIn()) {
    step(1);
  }
});

/* swipe between photos on touch, but only when not zoomed in -- otherwise a
   swipe means panning the photograph */
let touchStart = null;

stage.addEventListener("touchstart", (e) => {
  if (e.touches.length !== 1 || isZoomedIn()) return;
  touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() };
}, { passive: true });

stage.addEventListener("touchend", (e) => {
  if (!touchStart) return;
  const t = e.changedTouches[0];
  const dx = t.clientX - touchStart.x;
  const dy = t.clientY - touchStart.y;
  const quick = Date.now() - touchStart.t < 600;
  touchStart = null;

  if (quick && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.6) {
    step(dx < 0 ? 1 : -1);
  }
}, { passive: true });

el("back").addEventListener("click", () => go(location.pathname));
