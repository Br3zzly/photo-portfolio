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
const logEl     = $("log");
const logBody   = $("log-body");
const dropEl    = $("drop");

let bucket = "";
let fields = [];
let photos = [];
let staged = [];        // what the review sheet is showing

const api = async (path, opts) => {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status}`);
  return data;
};


/* --- the gallery ---------------------------------------------------------- */

async function loadManifest(refresh) {
  try {
    const data = await api("/api/manifest" + (refresh ? "?refresh=1" : ""));
    bucket = data.bucket;
    fields = data.fields;
    photos = data.manifest.photos || [];
    render();
  } catch (err) {
    statusEl.hidden = false;
    statusEl.className = "status error";
    statusEl.textContent = "Could not read the manifest: " + err.message;
  }
}

function render() {
  countEl.textContent = photos.length
    ? `${photos.length} published` : "";

  if (!photos.length) {
    statusEl.hidden = false;
    statusEl.className = "status";
    statusEl.textContent = "Nothing published yet. Add some photographs.";
    grid.replaceChildren();
    return;
  }

  statusEl.hidden = true;
  grid.replaceChildren(...photos.map(card));
}

function card(photo) {
  const el = document.createElement("div");
  el.className = "card";
  el.style.setProperty("--ar", ((photo.width || 3) / (photo.height || 2)).toFixed(4));

  const img = document.createElement("img");
  img.loading = "lazy";
  img.decoding = "async";
  img.alt = photo.id;
  img.src = `${bucket}/thumbs/${photo.rev ? `${photo.id}__${photo.rev}` : photo.id}.webp`;
  el.appendChild(img);

  const meta = document.createElement("div");
  meta.className = "card-meta";
  const id = document.createElement("span");
  id.className = "card-id";
  id.textContent = photo.id;
  meta.appendChild(id);
  if (photo.album) {
    const album = document.createElement("span");
    album.className = "card-album";
    album.textContent = photo.album;
    meta.appendChild(album);
  }
  el.appendChild(meta);

  const del = document.createElement("button");
  del.className = "card-del";
  del.type = "button";
  del.title = `Delete ${photo.id}`;
  del.setAttribute("aria-label", `Delete ${photo.id}`);
  del.innerHTML = `<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
    <path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a1 1 0 001 1h8a1 1 0 001-1l1-12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2"
      fill="none" stroke="currentColor" stroke-width="1.5"
      stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  del.addEventListener("click", () => askDelete(photo));
  el.appendChild(del);

  return el;
}


/* --- deleting ------------------------------------------------------------- */

function askDelete(photo) {
  $("confirm-title").textContent = `Delete ${photo.id}?`;
  $("confirm-body").textContent =
    "Its tiles and thumbnail are removed from Cloudflare and it is dropped " +
    "from the manifest. Nothing on this machine is touched, and your original " +
    "is wherever you keep it. This cannot be undone from here.";
  $("confirm").hidden = false;

  $("confirm-yes").onclick = async () => {
    $("confirm").hidden = true;
    const { job } = await api("/api/delete", {
      method: "POST",
      body: JSON.stringify({ ids: [photo.id] }),
    });
    await follow(job, `Deleting ${photo.id}`);
    await loadManifest(true);
  };
  $("confirm-no").onclick = () => { $("confirm").hidden = true; };
}


/* --- picking -------------------------------------------------------------- */

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

/* Dropping is the same thing by another route. A dropped folder arrives as a
   directory entry, which has to be walked to reach the files inside it. */
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

  const picked = [];
  const entries = [...e.dataTransfer.items]
    .map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null))
    .filter(Boolean);

  if (entries.length) {
    for (const entry of entries) await walk(entry, "", picked);
  } else {
    for (const file of e.dataTransfer.files) picked.push({ file, folder: "" });
  }
  takeFiles(picked);
});

/* A dropped folder becomes an album; folders inside it are flattened into the
   same album, since an id carries one level of folder and no more. */
async function walk(entry, album, out) {
  if (entry.isFile) {
    const file = await new Promise((res, rej) => entry.file(res, rej));
    out.push({ file, folder: album });
    return;
  }
  if (!entry.isDirectory) return;
  const name = album || entry.name;
  const reader = entry.createReader();
  for (;;) {
    const batch = await new Promise((res, rej) => reader.readEntries(res, rej));
    if (!batch.length) break;
    for (const child of batch) await walk(child, name, out);
  }
}

const IMAGE = /\.(jpe?g|png|tiff?|webp)$/i;

async function takeFiles(picked) {
  const files = picked.filter((p) => IMAGE.test(p.file.name));
  if (!files.length) return;

  openLog("Reading photographs");
  staged = [];
  for (let i = 0; i < files.length; i++) {
    const { file, folder } = files[i];
    say(`  [${i + 1}/${files.length}] ${file.name}`);
    try {
      const item = await api(
        `/api/stage?name=${encodeURIComponent(file.name)}&folder=${encodeURIComponent(folder)}`,
        { method: "POST", body: file }
      );
      staged.push(item);
    } catch (err) {
      say(`      failed: ${err.message}`, "bad");
    }
  }
  closeLog();
  if (staged.length) showReview();
}


/* --- the review sheet ----------------------------------------------------- */

function showReview() {
  $("review-title").textContent =
    `Review ${staged.length} photograph${staged.length === 1 ? "" : "s"}`;
  const albums = [...new Set(staged.map((s) => s.album).filter(Boolean))];
  $("review-sub").textContent = albums.length
    ? `album: ${albums.join(", ")}`
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

  // preview, rotation, and a way to drop this one
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

  // the metadata, prefilled with whatever the camera recorded
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
  await follow(job, `Publishing ${kept} photograph${kept === 1 ? "" : "s"}`);
  await loadManifest(true);
});


/* --- the log -------------------------------------------------------------- */

function openLog(title) {
  $("log-title").textContent = title;
  $("log-close").hidden = true;
  logBody.textContent = "";
  logEl.hidden = false;
}

function say(line, cls) {
  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = line + "\n";
  logBody.appendChild(span);
  logBody.scrollTop = logBody.scrollHeight;
}

function closeLog() { logEl.hidden = true; }

/* Poll the job until it finishes. The work happens in a thread on the server,
   so this is only ever reading a growing list of lines. */
async function follow(jobId, title) {
  openLog(title);
  let shown = 0;
  for (;;) {
    const job = await api(`/api/job?id=${encodeURIComponent(jobId)}`);
    job.lines.slice(shown).forEach((l) => say(l));
    shown = job.lines.length;
    if (job.done) {
      if (job.error) say("\n" + job.error, "bad");
      else say("\nfinished", "ok");
      $("log-title").textContent = job.error ? "Failed" : "Done";
      $("log-close").hidden = false;
      return;
    }
    await new Promise((r) => setTimeout(r, 400));
  }
}

$("log-close").addEventListener("click", closeLog);

loadManifest();
