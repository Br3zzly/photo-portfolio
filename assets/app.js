/* ---------------------------------------------------------------------------
   Gallery + deep-zoom lightbox. No framework, no build step.

   The manifest lives in the R2 bucket alongside the tiles, so publishing a
   photo never touches this repository.
   --------------------------------------------------------------------------- */

const BUCKET = "https://pub-9775c4eec7a34ee9bedf8364e574d557.r2.dev";

const el = (id) => document.getElementById(id);

const grid        = el("grid");
const status      = el("status");
const countEl     = el("count");
const lightbox    = el("lightbox");
const stage       = el("stage");
const placeholder = el("placeholder");
const viewerEl    = el("viewer");
const hint        = el("hint");
const prevBtn     = el("prev");
const nextBtn     = el("next");

let photos = [];
let index = -1;      // which photo is open; -1 means the gallery
let viewer = null;   // the OpenSeadragon instance, created once and reused
let idleTimer = null;


/* --- boot ---------------------------------------------------------------- */

init();

async function init() {
  try {
    const res = await fetch(`${BUCKET}/photos.json`, { cache: "no-cache" });
    if (!res.ok) throw new Error(`manifest returned ${res.status}`);
    const data = await res.json();
    photos = Array.isArray(data) ? data : data.photos || [];
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
  renderGrid();
  countEl.textContent =
    `${photos.length} photograph${photos.length === 1 ? "" : "s"}`;

  // a deep link like ?id=test must work pasted cold
  const wanted = new URLSearchParams(location.search).get("id");
  if (wanted) {
    const i = photos.findIndex((p) => p.id === wanted);
    if (i >= 0) open(i, { replace: true });
  }

  window.addEventListener("popstate", onPopState);
}


/* --- gallery ------------------------------------------------------------- */

function renderGrid() {
  const frag = document.createDocumentFragment();

  photos.forEach((photo, i) => {
    const ar = (photo.width || 3) / (photo.height || 2);

    const tile = document.createElement("button");
    tile.className = "tile";
    tile.style.setProperty("--ar", ar.toFixed(4));
    tile.setAttribute("role", "listitem");
    tile.setAttribute("aria-label", photo.title || photo.id);

    const img = document.createElement("img");
    img.loading = "lazy";
    img.decoding = "async";
    img.width = photo.width || 0;
    img.height = photo.height || 0;
    img.alt = photo.title || "";
    // the inlined placeholder paints immediately, so tiles are never empty
    if (photo.lqip) img.style.backgroundImage = `url("${photo.lqip}")`;
    img.src = `${BUCKET}/thumbs/${photo.id}.webp`;

    const reveal = () => img.classList.add("ready");
    if (img.complete) reveal();
    else img.addEventListener("load", reveal, { once: true });

    tile.appendChild(img);
    tile.addEventListener("click", () => open(i));
    frag.appendChild(tile);
  });

  grid.appendChild(frag);
}


/* --- lightbox ------------------------------------------------------------ */

function open(i, { replace = false } = {}) {
  if (i < 0 || i >= photos.length) return;
  const photo = photos[i];
  index = i;

  lightbox.hidden = false;
  document.body.classList.add("lightbox-open");
  requestAnimationFrame(() => lightbox.classList.add("open"));

  placeholder.src = photo.lqip || "";
  placeholder.classList.remove("hidden");
  viewerEl.classList.remove("ready");
  lightbox.classList.remove("zoomed");

  fillMeta(photo);
  prevBtn.disabled = i === 0;
  nextBtn.disabled = i === photos.length - 1;

  hint.classList.remove("gone");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => hint.classList.add("gone"), 3200);

  showTiles(photo);

  const url = `${location.pathname}?id=${encodeURIComponent(photo.id)}`;
  if (replace) history.replaceState({ id: photo.id }, "", url);
  else history.pushState({ id: photo.id }, "", url);
}

function close() {
  index = -1;
  lightbox.classList.remove("open", "zoomed", "interacting");
  document.body.classList.remove("lightbox-open");
  setTimeout(() => {
    lightbox.hidden = true;
    if (viewer) viewer.close();
  }, 280);

  if (new URLSearchParams(location.search).get("id")) {
    history.pushState({}, "", location.pathname);
  }
}

function step(delta) {
  const next = index + delta;
  if (next >= 0 && next < photos.length) open(next);
}

function fillMeta(photo) {
  el("m-title").textContent = photo.title || "";
  el("m-caption").textContent = photo.caption || "";

  // Built from whatever exists. A stacked astro frame has no lens or shutter,
  // so the strip collapses to what it has rather than rendering empty slots.
  el("m-gear").textContent =
    [photo.camera, photo.lens].filter(Boolean).join(" · ");

  // separate elements, not a joined string -- HTML collapses runs of spaces,
  // so the gaps have to come from CSS
  const parts = [
    photo.focal,
    photo.aperture,
    photo.shutter ? `${photo.shutter}s` : "",
    photo.iso ? `ISO ${photo.iso}` : "",
    ...Object.values(photo.extra || {}).filter(Boolean),
  ].filter(Boolean);

  const exposure = el("m-exposure");
  exposure.replaceChildren(
    ...parts.map((p) => {
      const s = document.createElement("span");
      s.textContent = p;
      return s;
    })
  );

  el("m-date").textContent = photo.date ? formatDate(photo.date) : "";
}

function formatDate(iso) {
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d)) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });
}


/* --- deep zoom ----------------------------------------------------------- */

function showTiles(photo) {
  const source = `${BUCKET}/${photo.id}.dzi`;

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

  viewer.addHandler("animation-finish", () => {
    syncZoomState();
    lightbox.classList.remove("interacting");
  });
}

function markInteracting() {
  lightbox.classList.add("interacting");
  hint.classList.add("gone");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    lightbox.classList.remove("interacting");
    syncZoomState();
  }, 1400);
}

function toggleZoom(point) {
  const item = viewer.world.getItemAt(0);
  if (!item) return;

  const full = item.imageToViewportZoom(1);
  const home = viewer.viewport.getHomeZoom();
  const target = full > home * 1.05 ? full : home * 2;

  if (viewer.viewport.getZoom() < target * 0.95) {
    viewer.viewport.zoomTo(target, point ? viewer.viewport.pointFromPixel(point) : null);
  } else {
    viewer.viewport.goHome();
  }
  setTimeout(syncZoomState, 60);
}

/* Zooming past "fit" promotes the photo to full-bleed and pulls the chrome
   back; returning to fit restores the framed view. */
function syncZoomState() {
  if (!viewer || !viewer.world.getItemCount()) return;
  const zoomed =
    viewer.viewport.getZoom() > viewer.viewport.getHomeZoom() * 1.08;
  lightbox.classList.toggle("zoomed", zoomed);
}


/* --- input --------------------------------------------------------------- */

el("close").addEventListener("click", close);
prevBtn.addEventListener("click", () => step(-1));
nextBtn.addEventListener("click", () => step(1));

document.addEventListener("keydown", (e) => {
  if (index < 0) return;

  if (e.key === "Escape") {
    // first Escape leaves a zoom, second closes the photo
    if (lightbox.classList.contains("zoomed")) {
      viewer.viewport.goHome();
      setTimeout(syncZoomState, 80);
    } else {
      close();
    }
  } else if (e.key === "ArrowLeft" && !lightbox.classList.contains("zoomed")) {
    step(-1);
  } else if (e.key === "ArrowRight" && !lightbox.classList.contains("zoomed")) {
    step(1);
  }
});

/* swipe between photos on touch, but only when not zoomed in -- otherwise a
   swipe means panning the photograph */
let touchStart = null;

stage.addEventListener("touchstart", (e) => {
  if (e.touches.length !== 1 || lightbox.classList.contains("zoomed")) return;
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

function onPopState() {
  const id = new URLSearchParams(location.search).get("id");
  if (!id) {
    if (index >= 0) {
      index = -1;
      lightbox.classList.remove("open", "zoomed", "interacting");
      document.body.classList.remove("lightbox-open");
      setTimeout(() => { lightbox.hidden = true; if (viewer) viewer.close(); }, 280);
    }
    return;
  }
  const i = photos.findIndex((p) => p.id === id);
  if (i >= 0 && i !== index) open(i, { replace: true });
}
