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
    preserveImageSizeOnResize: true,
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

/* Fit the photograph to the frame. Only meaningful once the card has finished
   changing size: OpenSeadragon computes the fit from the container it sees at
   that instant, so fitting mid-animation leaves the photograph at the previous
   shape's scale. */
export function refit() {
  if (loaded()) viewer.viewport.goHome(true);
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
