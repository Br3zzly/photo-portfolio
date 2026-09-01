/* OpenSeadragon wrapper.

   The library is a classic script that puts itself on window. Nothing here
   touches it until a photograph is actually opened, which is long after load,
   so there is no ordering dependency between it and the module graph. */

let viewer = null;

/* Creates the viewer on first use and reuses it afterwards: tearing one down
   per photograph would drop the tile cache and re-upload textures every time. */
export function showTiles(element, source, handlers) {
  if (viewer) {
    viewer.open(source);
    return;
  }
  viewer = create(element, source);
  wire(handlers);
  watchContainer(element);
}

function create(element, tileSources) {
  const options = {
    element,
    tileSources,
    prefixUrl: "",              // no default UI images; the page supplies its own
    showNavigationControl: false,
    showNavigator: false,
    crossOriginPolicy: "Anonymous",
    gestureSettingsMouse: { clickToZoom: false, dblClickToZoom: false },
    gestureSettingsTouch: { pinchRotate: false, clickToZoom: false, dblClickToZoom: false },
    maxZoomPixelRatio: 2,
    // 1, not the default 0.9: the photograph fills the frame exactly, so any
    // zooming out past the fit just opens gaps around it
    minZoomImageRatio: 1,
    visibilityRatio: 1,
    constrainDuringPan: true,
    springStiffness: 7.5,
    animationTime: 0.9,
    immediateRender: false,
    /* preserveImageSizeOnResize is deliberately off. It keeps the photograph at
       a constant pixel size when the container changes, which is the opposite
       of what this viewer wants: the photograph is meant to fit the frame, and
       every size change here is followed by a re-fit. Left on, a container that
       grows after the viewer opened leaves the photograph drawn at its older,
       smaller size, sitting in the middle of the frame. */
    maxImageCacheCount: 220,    // keep memory bounded on phones
  };

  // The WebGL drawer holds 1:1 zoom far better on iOS. Fall back silently.
  try {
    return OpenSeadragon({ ...options, drawer: "webgl" });
  } catch (err) {
    console.warn("WebGL drawer unavailable, using canvas", err);
    return OpenSeadragon(options);
  }
}

function wire({ onOpen, onOpenFailed, onInteract, onSettle, onToggleZoom }) {
  viewer.addHandler("open", onOpen);
  viewer.addHandler("open-failed", onOpenFailed);

  viewer.addHandler("canvas-double-click", (ev) => {
    ev.preventDefaultAction = true;
    onToggleZoom(ev.position);
  });

  // the chrome fades while the photograph is actually being moved around
  ["canvas-drag", "canvas-scroll", "canvas-pinch"].forEach((evt) =>
    viewer.addHandler(evt, onInteract)
  );
  viewer.addHandler("animation-finish", onSettle);
}

const loaded = () => Boolean(viewer && viewer.world.getItemCount());

/* The frame can still change size after the photograph has been fitted to it:
   a web font swapping in, the maker's mark arriving, the plate reflowing --
   all of which happen on a first visit and not on a cached one. Rather than
   trying to name every such moment, watch the container and re-fit whenever it
   actually changes. A visitor who has zoomed in is left alone. */
function watchContainer(element) {
  if (typeof ResizeObserver !== "function") return;
  let settle = null;
  new ResizeObserver(() => {
    clearTimeout(settle);
    settle = setTimeout(() => {
      if (loaded() && !isZoomedIn()) refit();
    }, 80);
  }).observe(element);
}

/* Fit the photograph to the frame.
 *
 * The container size is handed over explicitly rather than left to
 * OpenSeadragon to notice. It refreshes that figure inside its own animation
 * loop, so goHome() on its own fits to whatever size the loop last saw -- and
 * when the frame has just changed, that is the old one. The result is a
 * photograph drawn at its previous scale, sitting small in the middle of a
 * larger frame, with nothing afterwards to correct it. forceResize() is not
 * enough either: it only raises a flag for that same loop.
 *
 * Still only meaningful once the card has finished changing size, since fitting
 * mid-animation fits to a shape the card is on its way out of.
 */
export function refit() {
  if (!loaded()) return;
  const box = viewer.container;
  viewer.viewport.resize(
    new OpenSeadragon.Point(box.clientWidth, box.clientHeight), false
  );
  viewer.viewport.goHome(true);
  viewer.forceRedraw();
}

export function goHome() {
  if (loaded()) viewer.viewport.goHome();
}

export function closeTiles() {
  if (viewer) viewer.close();
}

export function isZoomedIn() {
  if (!loaded()) return false;
  return viewer.viewport.getZoom(true) > viewer.viewport.getHomeZoom() * 1.05;
}

/* Double-click toggles between fit and 1:1, inside the card. */
export function toggleZoom(point) {
  if (!loaded()) return;
  if (isZoomedIn()) {
    viewer.viewport.goHome();
    return;
  }
  const item = viewer.world.getItemAt(0);
  const full = item.imageToViewportZoom(1);
  const home = viewer.viewport.getHomeZoom();
  const target = full > home * 1.05 ? full : home * 2;
  viewer.viewport.zoomTo(target, point ? viewer.viewport.pointFromPixel(point) : null);
}
