/* The justified grid.

   Every tile grows in proportion to its aspect ratio, so a row fills the width
   exactly and each photograph keeps its true shape. The proportional part is
   load-bearing: with an equal flex-grow the leftover space in a row is split
   evenly instead of by shape, which stretches narrow photographs far more than
   wide ones and leaves object-fit to crop away the difference. */

import { aspect, thumbUrl } from "app/manifest";

export function renderGrid(grid, { photos, albums, onPhoto, onAlbum }) {
  const frag = document.createDocumentFragment();

  // on the home view, albums sit in the same grid as loose photographs
  albums.forEach((a) => frag.appendChild(albumTile(a, onAlbum)));
  photos.forEach((p, i) => frag.appendChild(photoTile(p, i, onPhoto)));

  grid.replaceChildren(frag);
  window.scrollTo({ top: 0 });
}

function tileShell(ar, label) {
  const tile = document.createElement("button");
  tile.className = "tile";
  tile.type = "button";
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
  // the inlined placeholder paints immediately, so a tile is never empty
  if (lqip) img.style.backgroundImage = `url("${lqip}")`;
  img.src = thumbUrl(id, rev);

  const reveal = () => img.classList.add("ready");
  if (img.complete) reveal();
  else img.addEventListener("load", reveal, { once: true });
  return img;
}

function photoTile(photo, i, onPhoto) {
  const tile = tileShell(aspect(photo.width, photo.height), photo.title || photo.id);
  const img = thumbImg(photo.id, photo.rev, photo.width, photo.height, photo.lqip, photo.title);
  tile.appendChild(img);
  // The tile itself is handed back, not the image inside it: the tile is what
  // carries the rounded corners, so it is what the open animation should morph
  // into the card. Snapshotting the square image instead loses them.
  tile.addEventListener("click", () => onPhoto(photo, i, tile));
  return tile;
}

function albumTile(a, onAlbum) {
  const tile = tileShell(aspect(a.coverWidth, a.coverHeight), `Album: ${a.name}`);
  tile.classList.add("album");
  tile.appendChild(thumbImg(a.cover, a.coverRev, a.coverWidth, a.coverHeight, a.coverLqip, ""));

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

  tile.addEventListener("click", () => onAlbum(a));
  return tile;
}

/* The tile showing a given photo, so closing can morph the card back into it. */
export function tileAt(grid, indexInPhotos, albumCount) {
  return grid.children[albumCount + indexInPhotos] || null;
}
