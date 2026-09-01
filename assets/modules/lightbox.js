/* The lightbox: one card holding the photograph and its plate.

   Image and plate are sized together as a single object, so the plate is
   always exactly as wide as the photograph above it. */

import { aspect, tileUrl } from "app/manifest";
import {
  showTiles, refit, goHome, closeTiles, isZoomedIn, toggleZoom,
} from "app/viewer";

const el = (id) => document.getElementById(id);

const lightbox    = el("lightbox");
const stage       = el("stage");
const card        = el("card");
const frame       = el("frame");
const plate       = el("plate");
const placeholder = el("placeholder");
const viewerEl    = el("viewer");
const prevBtn     = el("prev");
const nextBtn     = el("next");

const MORPH = "photo";          // the view-transition name shared by tile and card
const reduced = matchMedia("(prefers-reduced-motion: reduce)");

let current    = null;          // the photo on screen, or null
let hideTimer  = null;
let refitTimer = null;
let plateToken = 0;             // guards the async logo probe against fast stepping
let generation = 0;             // bumped by every open and close, so a deferred
                                // teardown can tell it has been superseded

export const isOpen = () => current !== null;
export { isZoomedIn };


/* --- open and close ------------------------------------------------------ */

export function showPhoto(photo, { hasPrev, hasNext, fromTile }) {
  // A close that has not finished must not tear down the photograph we are
  // about to show. Both ways a close can still be pending are cancelled here:
  // the timer on the plain fade, and the generation the deferred teardown
  // checks -- a view transition's callback does not run until the next
  // rendering opportunity, so that teardown can otherwise land after this.
  clearTimeout(hideTimer);
  generation++;

  const opening = lightbox.hidden;

  /* Filling and tiling stay together, and always run once the card is on
     screen at its final size. OpenSeadragon measures its container the moment
     it is created, so starting it while the lightbox is still hidden gives a
     1x1 canvas -- which is exactly what happens if this is left outside the
     view transition's callback, since that callback is not synchronous. */
  const enter = (animateSize) => {
    present(photo, hasPrev, hasNext, { animateSize });
    loadTiles(photo);
  };

  if (opening && canMorph()) {
    // No rAF: display and opacity change in the same frame, so the fade never
    // runs and the view transition owns the whole animation.
    morph(fromTile, frame, () => {
      reveal();
      enter(false);
    });
  } else if (opening) {
    reveal();
    enter(false);
    requestAnimationFrame(() => lightbox.classList.add("open"));
  } else {
    // stepping along: the card animates between the two photographs' shapes
    enter(true);
  }
}

export function hidePhoto({ toTile } = {}) {
  if (!isOpen()) return;

  // whichever way this finishes, it is abandoned if a photograph is opened
  // in the meantime
  const gen = ++generation;
  const finish = () => { if (gen === generation) teardown(); };

  if (canMorph()) {
    morph(frame, toTile, finish);
    return;
  }

  lightbox.classList.remove("open", "interacting");
  document.body.classList.remove("lightbox-open");
  clearTimeout(hideTimer);
  hideTimer = setTimeout(finish, 280);
}

function reveal() {
  lightbox.hidden = false;
  lightbox.classList.add("open");
  document.body.classList.add("lightbox-open");
}

function teardown() {
  clearTimeout(hideTimer);
  clearTimeout(refitTimer);
  lightbox.hidden = true;
  lightbox.classList.remove("open", "interacting", "swapping");
  document.body.classList.remove("lightbox-open");
  closeTiles();
  current = null;
}

function present(photo, hasPrev, hasNext, { animateSize }) {
  current = photo;

  // the outgoing canvas still holds the previous photograph
  lightbox.classList.add("swapping");
  placeholder.src = photo.lqip || "";
  placeholder.classList.remove("hidden");
  viewerEl.classList.remove("ready");

  fillPlate(photo);
  prevBtn.disabled = !hasPrev;
  nextBtn.disabled = !hasNext;

  card.classList.toggle("instant", !animateSize);
  sizeCard();
  if (!animateSize) requestAnimationFrame(() => card.classList.remove("instant"));
  scheduleRefit(420);
}

function loadTiles(photo) {
  showTiles(viewerEl, tileUrl(photo.id, photo.rev), {
    onOpen: () => {
      sizeCard();
      refit();
      lightbox.classList.remove("swapping");
      viewerEl.classList.add("ready");
      setTimeout(() => placeholder.classList.add("hidden"), 220);
    },
    // leave the blurred placeholder up rather than showing a broken frame
    onOpenFailed: () => viewerEl.classList.remove("ready"),
    onInteract: () => lightbox.classList.add("interacting"),
    onSettle:   () => lightbox.classList.remove("interacting"),
    onToggleZoom: toggleZoom,
  });
}


/* --- the morph -----------------------------------------------------------
   The thumbnail and the card's frame take turns holding one view-transition
   name, so the browser treats them as a single object moving between two
   places. Only one element may carry the name at a time, which is why it is
   handed over inside the callback that defines the new state.
   ------------------------------------------------------------------------- */

const canMorph = () =>
  typeof document.startViewTransition === "function" && !reduced.matches;

let morphGen = 0;

function morph(fromEl, toEl, mutate) {
  if (!canMorph()) { mutate(); return; }

  // Starting a transition skips any one still running, and the skipped one
  // settles afterwards. Without this guard that late settlement would strip
  // the name off the element the newer transition is currently animating.
  const gen = ++morphGen;

  const clear = () => {
    if (gen !== morphGen) return;
    if (fromEl) fromEl.style.viewTransitionName = "";
    if (toEl) toEl.style.viewTransitionName = "";
  };

  if (fromEl) fromEl.style.viewTransitionName = MORPH;

  let transition;
  try {
    transition = document.startViewTransition(() => {
      if (fromEl) fromEl.style.viewTransitionName = "";
      if (toEl) toEl.style.viewTransitionName = MORPH;
      mutate();
    });
  } catch {
    clear();
    mutate();
    return;
  }

  // A transition that gets skipped -- by the next one starting, or by the page
  // not being in a state it can animate in -- rejects `ready`. That is normal
  // and already handled by falling back to the plain state change, but an
  // unobserved rejection still reaches the console, so both are claimed here.
  transition.ready.catch(() => {});
  transition.updateCallbackDone.catch(() => {});
  transition.finished.then(clear, clear);
}


/* --- the plate ------------------------------------------------------------
   Camera maker and model in bold, then lens, focal length, aperture, shutter
   and ISO in grey, with the maker's mark on the right. Everything is built
   from what exists, so a stacked frame carrying no EXIF at all leaves the
   plate empty rather than rendering blank slots.
   ------------------------------------------------------------------------- */

function fillPlate(photo) {
  const token = ++plateToken;

  el("m-camera").textContent = photo.camera || "";

  const parts = [
    photo.lens,
    photo.focal,
    photo.aperture,
    photo.shutter ? `${photo.shutter}s` : "",
    photo.iso ? `ISO ${photo.iso}` : "",
    ...Object.values(photo.extra || {}).filter(Boolean),
  ].filter(Boolean);

  // separate elements rather than a joined string: HTML collapses runs of
  // spaces, so the gaps have to come from CSS
  el("m-spec").replaceChildren(
    ...parts.map((text) => {
      const span = document.createElement("span");
      span.textContent = text;
      return span;
    })
  );

  const mark = el("m-mark");
  mark.replaceChildren();

  const slug = makerSlug(photo);
  if (!slug) return;

  logoExists(slug).then((exists) => {
    // a fast step through the gallery can land a stale probe here
    if (!exists || token !== plateToken) return;
    const img = document.createElement("img");
    img.alt = photo.make || "";
    img.src = logoUrl(slug);
    mark.replaceChildren(img);
  });
}

const makerSlug = (photo) =>
  (photo.make || (photo.camera || "").split(/\s+/)[0] || "")
    .trim().toLowerCase().replace(/[^a-z0-9]+/g, "");

const logoUrl = (slug) => `assets/logos/${slug}.svg`;

/* A static site cannot list a directory, so whether a logo exists is settled
   by asking for it once. The answer is cached per maker rather than per photo:
   a maker with no logo costs one failed request for the whole session instead
   of one for every photograph viewed. Drop an SVG in and it simply appears;
   leave the folder empty and the mark stays blank. */
const logoCache = new Map();

function logoExists(slug) {
  if (!logoCache.has(slug)) {
    logoCache.set(slug, new Promise((resolve) => {
      const probe = new Image();
      probe.onload = () => resolve(true);
      probe.onerror = () => resolve(false);
      probe.src = logoUrl(slug);
    }));
  }
  return logoCache.get(slug);
}


/* --- sizing --------------------------------------------------------------
   The card is laid out from the photograph's aspect ratio rather than left to
   the browser, because the plate's height is only known once it is filled.
   ------------------------------------------------------------------------- */

function sizeCard() {
  if (!current) return;

  const ar = aspect(current.width, current.height);
  const sp = getComputedStyle(stage);

  // Measured from the lightbox, never from the stage. The stage is sized by
  // its own content, so measuring it would feed the card's current size back
  // into the calculation and let it grow without bound.
  const availW = lightbox.clientWidth
    - parseFloat(sp.paddingLeft) - parseFloat(sp.paddingRight);
  const availH = lightbox.clientHeight
    - parseFloat(sp.paddingTop) - parseFloat(sp.paddingBottom);

  // The card is border-box, so its width includes the mat around the
  // photograph. Fit the frame to the aspect ratio, then add the mat and the
  // plate back on to get the card's outer size.
  const cc = getComputedStyle(card);
  const matX = parseFloat(cc.paddingLeft) + parseFloat(cc.paddingRight);
  const matY = parseFloat(cc.paddingTop) + parseFloat(cc.paddingBottom);

  // two passes: the plate can wrap, so its height depends on the width chosen
  let w = availW;
  for (let pass = 0; pass < 2; pass++) {
    card.style.width = `${Math.round(w)}px`;
    const plateH = plate.offsetHeight;

    let frameW = w - matX;
    let frameH = frameW / ar;
    const roomForFrame = availH - matY - plateH;
    if (frameH > roomForFrame) {
      frameH = roomForFrame;
      frameW = frameH * ar;
      w = Math.min(availW, frameW + matX);
    }
    card.style.width = `${Math.round(w)}px`;
    card.style.height = `${Math.round(frameH + matY + plateH)}px`;
  }
}

/* One scheduler for re-fitting. transitionend fires separately for width and
   height, and does not fire at all when the size did not change, so both feed
   the same timer and the photograph is fitted exactly once. */
function scheduleRefit(delay) {
  clearTimeout(refitTimer);
  refitTimer = setTimeout(refit, delay);
}


/* --- input --------------------------------------------------------------- */

export function initLightbox({ onClose, onStep }) {
  el("close").addEventListener("click", onClose);
  prevBtn.addEventListener("click", () => onStep(-1));
  nextBtn.addEventListener("click", () => onStep(1));

  /* Clicking the space around the card closes it, the same as the way out in
     the corner. Both ends of the click have to have landed outside: panning a
     zoomed photograph regularly releases the mouse beyond the card, and that
     is a drag, not a click on the backdrop. Buttons are left alone so the
     chevrons either side do not close the photograph out from under
     themselves. */
  let pressedOutside = false;
  const outside = (target) => !card.contains(target) && !target.closest("button");

  lightbox.addEventListener("pointerdown", (e) => {
    pressedOutside = outside(e.target);
  });

  lightbox.addEventListener("click", (e) => {
    if (pressedOutside && outside(e.target)) onClose();
  });

  card.addEventListener("transitionend", (e) => {
    if (e.target === card && (e.propertyName === "width" || e.propertyName === "height")) {
      scheduleRefit(0);
    }
  });

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    if (!isOpen()) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(sizeCard, 120);
  });

  document.addEventListener("keydown", (e) => {
    if (!isOpen()) return;

    if (e.key === "Escape") {
      // first Escape leaves a zoom, second closes the photograph
      if (isZoomedIn()) goHome();
      else onClose();
    } else if (e.key === "ArrowLeft" && !isZoomedIn()) {
      onStep(-1);
    } else if (e.key === "ArrowRight" && !isZoomedIn()) {
      onStep(1);
    }
  });

  // swipe between photographs, but only when not zoomed in -- otherwise a
  // swipe means panning the photograph
  let touchStart = null;

  stage.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1 || isZoomedIn()) return;
    touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() };
  }, { passive: true });

  stage.addEventListener("touchend", (e) => {
    if (!touchStart) return;
    const touch = e.changedTouches[0];
    const dx = touch.clientX - touchStart.x;
    const dy = touch.clientY - touchStart.y;
    const quick = Date.now() - touchStart.t < 600;
    touchStart = null;

    if (quick && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.6) {
      onStep(dx < 0 ? 1 : -1);
    }
  }, { passive: true });
}
