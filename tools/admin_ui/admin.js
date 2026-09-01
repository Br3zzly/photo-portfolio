/* The admin console.
 *
 * Talks to the local Python server and nothing else. The gallery it shows is
 * the published manifest, so what is on screen is what is in the bucket.
 */

const $ = (id) => document.getElementById(id);

const grid      = $("grid");
const statusEl  = $("status");
const countEl   = $("count");
const reviewEl  = $("review");
const reviewList= $("review-list");
const dropEl    = $("drop");

let bucket = "";
let fields = [];
let photos = [];
let albums = [];
let album  = null;        // the album being looked at, or null for the top level
let staged = [];          // what the review sheet is showing

/* What is picked, as "photo:<id>" or "album:<name>". Albums stand for every
   photograph inside them and are expanded only when something is done. */
const picked = new Set();
let lastIndex = -1;       // for shift-click

const api = async (path, opts) => {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status}`);
  return data;
};

const thumb = (id, rev) =>
  `${bucket}/thumbs/${rev ? `${id}__${rev}` : id}.webp`;

const inAlbum = (name) => photos.filter((p) => p.album === name);


/* --- the gallery ---------------------------------------------------------- */

async function loadManifest(refresh) {
  try {
    const data = await api("/api/manifest" + (refresh ? "?refresh=1" : ""));
    bucket = data.bucket;
    fields = data.fields;
    photos = data.manifest.photos || [];
    albums = data.manifest.albums || [];
    if (album && !albums.some((a) => a.name === album)) album = null;
    picked.clear();
    render();
  } catch (err) {
    statusEl.hidden = false;
    statusEl.className = "status error";
    statusEl.textContent = "Could not read the manifest: " + err.message;
  }
}

/* At the top level: albums first, then the loose photographs, exactly as the
   gallery orders them. Inside an album: only its own. */
function shown() {
  if (album) return { albums: [], photos: inAlbum(album) };
  return { albums, photos: photos.filter((p) => !p.album) };
}

function render() {
  const view = shown();
  const total = view.albums.length + view.photos.length;

  $("back").hidden = !album;
  $("where").innerHTML = album
    ? `${escapeHtml(album)} <span class="bar-sub">album</span>`
    : `Portfolio <span class="bar-sub">admin</span>`;
  countEl.textContent = album
    ? `${view.photos.length} in this album`
    : (photos.length ? `${photos.length} published` : "");

  if (!total) {
    statusEl.hidden = false;
    statusEl.className = "status";
    statusEl.textContent = album
      ? "This album is empty."
      : "Nothing published yet. Add some photographs.";
    grid.replaceChildren();
    updateSelBar();
    return;
  }

  statusEl.hidden = true;
  const tiles = [
    ...view.albums.map((a) => albumTile(a)),
    ...view.photos.map((p) => photoTile(p)),
  ];
  tiles.forEach((el, i) => { el.dataset.index = String(i); });
  grid.replaceChildren(...tiles);
  updateSelBar();
}

function shell(ar, key) {
  const el = document.createElement("div");
  el.className = "card";
  el.dataset.key = key;
  el.style.setProperty("--ar", ar.toFixed(4));
  if (picked.has(key)) el.classList.add("picked");

  const tick = document.createElement("span");
  tick.className = "tick";
  tick.innerHTML = `<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
    <path d="M5 13l4 4L19 7" fill="none" stroke="currentColor" stroke-width="2.4"
      stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  el.appendChild(tick);

  el.addEventListener("click", (e) => onPick(el, key, e));
  return el;
}

function image(el, id, rev, alt) {
  const img = document.createElement("img");
  img.loading = "lazy";
  img.decoding = "async";
  img.alt = alt;
  img.src = thumb(id, rev);
  el.appendChild(img);
}

function photoTile(photo) {
  const el = shell((photo.width || 3) / (photo.height || 2), `photo:${photo.id}`);
  image(el, photo.id, photo.rev, photo.id);

  const meta = document.createElement("div");
  meta.className = "card-meta";
  const id = document.createElement("span");
  id.className = "card-id";
  id.textContent = photo.id;
  meta.appendChild(id);
  el.appendChild(meta);

  el.appendChild(deleteButton(`Delete ${photo.id}`, () => askDelete(
    `Delete ${photo.id}?`, [photo.id])));
  return el;
}

function albumTile(a) {
  const el = shell((a.coverWidth || 3) / (a.coverHeight || 2), `album:${a.name}`);
  el.classList.add("album");
  image(el, a.cover, a.coverRev, `Album: ${a.name}`);

  const label = document.createElement("span");
  label.className = "album-label";
  const name = document.createElement("span");
  name.className = "album-name";
  name.textContent = a.name;
  const count = document.createElement("span");
  count.className = "album-count";
  count.textContent = a.count === 1 ? "1 photo" : `${a.count} photos`;
  label.append(name, count);
  el.appendChild(label);

  el.appendChild(deleteButton(`Delete the album ${a.name}`, () => {
    const ids = inAlbum(a.name).map((p) => p.id);
    askDelete(`Delete the album ${a.name}?`, ids,
      `All ${ids.length} photograph${ids.length === 1 ? "" : "s"} in it go too.`);
  }));

  // opening an album is a double-click, since a single one picks it
  el.addEventListener("dblclick", () => { album = a.name; picked.clear(); render(); });
  return el;
}

function deleteButton(label, onClick) {
  const b = document.createElement("button");
  b.className = "card-del";
  b.type = "button";
  b.title = label;
  b.setAttribute("aria-label", label);
  b.innerHTML = `<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a1 1 0 001 1h8a1 1 0 001-1l1-12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2"
      fill="none" stroke="currentColor" stroke-width="1.5"
      stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  b.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
  return b;
}

const escapeHtml = (s) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;",
                                  '"': "&quot;", "'": "&#39;" }[c]));


/* --- picking -------------------------------------------------------------- */

function onPick(el, key, e) {
  const index = +el.dataset.index;

  if (e.shiftKey && lastIndex >= 0) {
    const [from, to] = [Math.min(lastIndex, index), Math.max(lastIndex, index)];
    [...grid.children].slice(from, to + 1).forEach((tile) => {
      picked.add(tile.dataset.key);
      tile.classList.add("picked");
    });
  } else {
    if (picked.has(key)) { picked.delete(key); el.classList.remove("picked"); }
    else { picked.add(key); el.classList.add("picked"); }
    lastIndex = index;
  }
  updateSelBar();
}

/* Albums stand for their contents, so a mixed selection still comes out as a
   plain list of photographs with nothing counted twice. */
function pickedIds() {
  const ids = new Set();
  picked.forEach((key) => {
    const [kind, rest] = [key.slice(0, key.indexOf(":")), key.slice(key.indexOf(":") + 1)];
    if (kind === "photo") ids.add(rest);
    else inAlbum(rest).forEach((p) => ids.add(p.id));
  });
  return [...ids];
}

function updateSelBar() {
  const n = picked.size;
  $("selbar").hidden = n === 0;
  if (!n) return;
  const ids = pickedIds();
  const albumsPicked = [...picked].filter((k) => k.startsWith("album:")).length;
  $("selcount").textContent =
    albumsPicked && ids.length !== n
      ? `${n} selected — ${ids.length} photograph${ids.length === 1 ? "" : "s"}`
      : `${n} selected`;
}

$("sel-clear").addEventListener("click", () => {
  picked.clear();
  grid.querySelectorAll(".picked").forEach((el) => el.classList.remove("picked"));
  updateSelBar();
});

$("sel-delete").addEventListener("click", () => {
  const ids = pickedIds();
  if (!ids.length) return;
  askDelete(`Delete ${ids.length} photograph${ids.length === 1 ? "" : "s"}?`, ids);
});

$("back").addEventListener("click", () => { album = null; picked.clear(); render(); });

addEventListener("keydown", (e) => {
  if (!reviewEl.hidden) return;
  if (e.key === "Escape") {
    if (picked.size) $("sel-clear").click();
    else if (album) $("back").click();
  }
  if (e.key === "a" && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    [...grid.children].forEach((el) => {
      picked.add(el.dataset.key);
      el.classList.add("picked");
    });
    updateSelBar();
  }
});


/* --- deleting ------------------------------------------------------------- */

function askDelete(title, ids, extra) {
  $("confirm-title").textContent = title;
  $("confirm-body").textContent =
    (extra ? extra + " " : "") +
    "Tiles and thumbnails are removed from Cloudflare and the photographs are " +
    "dropped from the manifest. Nothing on this machine is touched and your " +
    "originals are wherever you keep them. The metadata you typed is not kept " +
    "anywhere else, so this cannot be undone.";
  $("confirm").hidden = false;

  $("confirm-yes").onclick = async () => {
    $("confirm").hidden = true;
    const { job } = await api("/api/delete", {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
    await follow(job, ids.length === 1 ? "Deleting" : `Deleting ${ids.length}`);
    await loadManifest(true);
  };
  $("confirm-no").onclick = () => { $("confirm").hidden = true; };
}


/* --- adding --------------------------------------------------------------- */

$("add-files").addEventListener("click", () => $("pick-files").click());
$("add-folder").addEventListener("click", () => $("pick-folder").click());

$("pick-files").addEventListener("change", (e) => {
  takeFiles([...e.target.files].map((f) => ({ file: f, folder: "" })));
  e.target.value = "";
});

$("pick-folder").addEventListener("change", (e) => {
  // webkitRelativePath is "Kyoto/temple.jpg"; the first segment is the album
  takeFiles([...e.target.files].map((f) => ({
    file: f,
    folder: (f.webkitRelativePath || "").split("/")[0] || "",
  })));
  e.target.value = "";
});

let dragDepth = 0;

addEventListener("dragenter", (e) => {
  if (![...e.dataTransfer.types].includes("Files")) return;
  e.preventDefault();
  if (++dragDepth === 1) dropEl.classList.add("on");
});

addEventListener("dragover", (e) => {
  if ([...e.dataTransfer.types].includes("Files")) e.preventDefault();
});

addEventListener("dragleave", () => {
  if (--dragDepth <= 0) { dragDepth = 0; dropEl.classList.remove("on"); }
});

addEventListener("drop", async (e) => {
  if (![...e.dataTransfer.types].includes("Files")) return;
  e.preventDefault();
  dragDepth = 0;
  dropEl.classList.remove("on");

  const found = [];
  const entries = [...e.dataTransfer.items]
    .map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null))
    .filter(Boolean);

  if (entries.length) {
    for (const entry of entries) await walk(entry, "", found);
  } else {
    for (const file of e.dataTransfer.files) found.push({ file, folder: "" });
  }
  takeFiles(found);
});

/* A dropped folder becomes an album; folders inside it are flattened into the
   same album, since an id carries one level of folder and no more. */
async function walk(entry, name, out) {
  if (entry.isFile) {
    const file = await new Promise((res, rej) => entry.file(res, rej));
    out.push({ file, folder: name });
    return;
  }
  if (!entry.isDirectory) return;
  const folder = name || entry.name;
  const reader = entry.createReader();
  for (;;) {
    const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
    if (!batch.length) break;
    for (const child of batch) await walk(child, folder, out);
  }
}

const IMAGE = /\.(jpe?g|png|tiff?|webp)$/i;

async function takeFiles(found) {
  const files = found.filter((p) => IMAGE.test(p.file.name));
  if (!files.length) return;

  showProgress("Reading", files.length);
  staged = [];
  for (let i = 0; i < files.length; i++) {
    const { file, folder } = files[i];
    setProgress(i, files.length, file.name);
    try {
      staged.push(await api(
        `/api/stage?name=${encodeURIComponent(file.name)}&folder=${encodeURIComponent(folder)}`,
        { method: "POST", body: file }
      ));
    } catch (err) {
      failProgress(`${file.name}: ${err.message}`);
      return;
    }
  }
  hideProgress();
  if (staged.length) showReview();
}


/* --- the review sheet ----------------------------------------------------- */

function showReview() {
  $("review-title").textContent =
    `Review ${staged.length} photograph${staged.length === 1 ? "" : "s"}`;
  const names = [...new Set(staged.map((s) => s.album).filter(Boolean))];
  $("review-sub").textContent = names.length
    ? `album: ${names.join(", ")}`
    : "no album — these go on the front page";

  reviewList.replaceChildren(...staged.map(reviewItem));
  reviewEl.hidden = false;
}

function reviewItem(item) {
  const row = document.createElement("div");
  row.className = "item";
  row.dataset.id = item.id;
  row.dataset.rotate = "0";
  row.dataset.skip = "";

  const left = document.createElement("div");
  left.className = "item-preview";
  const img = document.createElement("img");
  img.alt = item.id;
  img.src = `/api/preview?id=${encodeURIComponent(item.id)}&rotate=0`;
  left.appendChild(img);

  const tools = document.createElement("div");
  tools.className = "item-tools";

  const rotate = (deg, label) => {
    const b = document.createElement("button");
    b.className = "btn";
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", () => {
      const next = ((+row.dataset.rotate + deg) % 360 + 360) % 360;
      row.dataset.rotate = String(next);
      img.src = `/api/preview?id=${encodeURIComponent(item.id)}&rotate=${next}&t=${Date.now()}`;
    });
    return b;
  };
  tools.append(rotate(-90, "⟲ Left"), rotate(90, "⟳ Right"));

  const skip = document.createElement("button");
  skip.className = "btn";
  skip.type = "button";
  skip.textContent = "Skip";
  skip.addEventListener("click", () => {
    const now = row.dataset.skip ? "" : "1";
    row.dataset.skip = now;
    row.classList.toggle("skipped", Boolean(now));
    skip.textContent = now ? "Include" : "Skip";
  });
  tools.appendChild(skip);
  left.appendChild(tools);

  const name = document.createElement("div");
  name.className = "item-name";
  name.textContent = item.id;
  left.appendChild(name);
  row.appendChild(left);

  const right = document.createElement("div");
  right.className = "fields";

  item.warnings.forEach((text) => {
    const w = document.createElement("div");
    w.className = "warn";
    w.textContent = text;
    right.appendChild(w);
  });

  fields.forEach(([key, label, placeholder]) => {
    const wrap = document.createElement("div");
    wrap.className = "field" + (key === "caption" || key === "title" ? " wide" : "");
    const l = document.createElement("label");
    l.textContent = label;
    l.htmlFor = `${item.id}-${key}`;
    const input = document.createElement("input");
    input.id = `${item.id}-${key}`;
    input.dataset.key = key;
    input.placeholder = placeholder;
    input.value = item.data[key] || "";
    wrap.append(l, input);
    right.appendChild(wrap);
  });

  row.appendChild(right);
  return row;
}

$("review-cancel").addEventListener("click", async () => {
  reviewEl.hidden = true;
  staged = [];
  await api("/api/discard", { method: "POST" });
});

$("review-publish").addEventListener("click", async () => {
  const edits = {};
  let kept = 0;
  reviewList.querySelectorAll(".item").forEach((row) => {
    if (row.dataset.skip) return;
    const data = { rotate: +row.dataset.rotate };
    row.querySelectorAll("input[data-key]").forEach((i) => {
      data[i.dataset.key] = i.value.trim();
    });
    edits[row.dataset.id] = data;
    kept++;
  });

  if (!kept) {
    await api("/api/discard", { method: "POST" });
    reviewEl.hidden = true;
    return;
  }

  reviewEl.hidden = true;
  const { job } = await api("/api/publish", {
    method: "POST",
    body: JSON.stringify(edits),
  });
  await follow(job, `Publishing ${kept}`);
  await loadManifest(true);
});


/* --- progress ------------------------------------------------------------- */

const progress = $("progress");

function showProgress(title, total) {
  // both sit bottom centre, and only one of them can be the thing to look at
  $("selbar").hidden = true;
  $("progress-title").textContent = title;
  $("progress-label").textContent = "";
  $("progress-close").hidden = true;
  progress.classList.remove("failed");
  progress.classList.toggle("indeterminate", !total);
  $("progress-fill").style.width = total ? "0%" : "";
  progress.hidden = false;
}

function setProgress(step, total, label) {
  if (total) {
    progress.classList.remove("indeterminate");
    $("progress-fill").style.width =
      `${Math.round((Math.min(step, total) / total) * 100)}%`;
  }
  if (label !== undefined) $("progress-label").textContent = label;
}

function failProgress(message) {
  progress.classList.add("failed");
  progress.classList.remove("indeterminate");
  $("progress-title").textContent = "Failed";
  $("progress-label").textContent = message;
  $("progress-close").hidden = false;
}

function hideProgress() {
  progress.hidden = true;
  updateSelBar();          // whatever is still picked comes back
}

$("progress-close").addEventListener("click", hideProgress);

/* Watch a server job. The work runs on a thread over there; this only reads
   how far it has got. */
async function follow(jobId, title) {
  showProgress(title, 0);
  for (;;) {
    const job = await api(`/api/job?id=${encodeURIComponent(jobId)}`);
    setProgress(job.step, job.total, job.label);
    if (job.done) {
      if (job.error) { failProgress(job.error); return; }
      setProgress(1, 1, "done");
      setTimeout(hideProgress, 900);
      return;
    }
    await new Promise((r) => setTimeout(r, 350));
  }
}

loadManifest();
