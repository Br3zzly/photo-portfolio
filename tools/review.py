"""
The metadata review step: one page, one tab, however many photos.

You walk the queue with the arrow keys, correct anything the camera did not
record, mark the frames you do not want, and publish the rest in one go. The
server exists only while the page is open and shuts down as soon as you are
done. Nothing about the published site depends on it.
"""

import http.server
import json
import socket
import threading
import webbrowser
from pathlib import Path

import config

PALETTE = {
    "ground": "#0B0B0B",
    "raised": "#151515",
    "hairline": "#2A2A2A",
    "text": "#F2F0ED",
    "muted": "#8B8B8B",
    "accent": "#C4553D",
    "good": "#6E9E78",
}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def review_all(items, open_browser=True):
    """
    items: [{"id":..., "data": {...}, "thumb": Path, "warnings": [...]}]

    Returns a dict of id -> edited data for the photos you chose to publish.
    Photos you skipped are absent. Returns None if you cancelled outright.
    """
    if not items:
        return {}

    thumbs = [Path(it["thumb"]).read_bytes() for it in items]
    payload = [
        {"id": it["id"], "album": it.get("album", ""),
         "data": it["data"], "warnings": it.get("warnings", [])}
        for it in items
    ]
    page = _render(payload).encode("utf-8")

    result = {"out": None, "done": threading.Event()}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/preview/"):
                try:
                    i = int(self.path.split("/")[-1].split(".")[0])
                    self._send(200, thumbs[i], "image/webp")
                except (ValueError, IndexError):
                    self._send(404, b"", "text/plain")
            elif self.path == "/" or self.path.startswith("/?"):
                self._send(200, page, "text/html; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            if body.get("action") == "publish":
                result["out"] = {
                    row["id"]: row["data"]
                    for row in body.get("rows", []) if not row.get("skip")
                }
            self._send(200, b'{"ok":true}', "application/json")
            result["done"].set()

    port = _free_port()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    print(f"  review {len(items)} photo(s): {url}", flush=True)
    if open_browser:
        webbrowser.open(url)

    try:
        result["done"].wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()

    return result["out"]


def _render(payload):
    p = PALETTE
    fields = config.METADATA_FIELDS
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Review {len(payload)} photos</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; height: 100vh; overflow: hidden;
    background: {p['ground']}; color: {p['text']};
    font: 14px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif;
    display: grid; grid-template-columns: minmax(0,1fr) 420px;
  }}
  @media (max-width: 940px) {{ body {{ grid-template-columns: 1fr; grid-template-rows: 40vh 1fr; }} }}

  .stage {{ position: relative; display: grid; place-items: center; padding: 24px; min-width: 0; }}
  .stage img {{ max-width: 100%; max-height: 100%; object-fit: contain; display: block; }}
  .stage.skipped img {{ opacity: .25; filter: grayscale(1); }}
  .skipbadge {{
    position: absolute; top: 20px; left: 20px; display: none;
    background: {p['accent']}; color: #fff; padding: 4px 10px;
    border-radius: 3px; font-size: 12px; font-weight: 600; letter-spacing: .04em;
  }}
  .stage.skipped .skipbadge {{ display: block; }}

  .panel {{
    border-left: 1px solid {p['hairline']}; background: {p['raised']};
    display: flex; flex-direction: column; min-height: 0;
  }}
  .head {{ padding: 18px 22px 12px; border-bottom: 1px solid {p['hairline']}; }}
  .counter {{ font-size: 12px; color: {p['muted']}; }}
  .fname {{ font-size: 16px; font-weight: 600; margin-top: 2px; word-break: break-all; }}
  .album {{ font-size: 12px; color: {p['muted']}; margin-top: 2px; }}

  .bar {{ height: 3px; background: {p['hairline']}; margin-top: 12px; border-radius: 2px; overflow: hidden; }}
  .bar > i {{ display: block; height: 100%; background: {p['text']}; transition: width .2s ease; }}

  .body {{ padding: 16px 22px; overflow-y: auto; flex: 1; }}
  .warn {{
    border-left: 2px solid {p['accent']}; background: rgba(196,85,61,.1);
    padding: 8px 12px; margin-bottom: 16px; font-size: 12.5px;
  }}
  label.f {{ display: block; margin-bottom: 12px; }}
  label.f span {{ display: block; font-size: 11.5px; color: {p['muted']}; margin-bottom: 4px; }}
  input {{
    width: 100%; padding: 8px 10px; font: inherit; color: {p['text']};
    background: {p['ground']}; border: 1px solid {p['hairline']}; border-radius: 3px;
  }}
  input:focus {{ outline: none; border-color: {p['accent']}; }}

  h2 {{ font-size: 11.5px; color: {p['muted']}; font-weight: 500;
       margin: 22px 0 8px; padding-top: 14px; border-top: 1px solid {p['hairline']}; }}
  .xrow {{ display: grid; grid-template-columns: 1fr 1fr auto; gap: 5px; margin-bottom: 5px; }}
  button {{ font: inherit; cursor: pointer; border-radius: 3px; }}
  .ghost {{ background: none; border: 1px solid {p['hairline']}; color: {p['muted']}; padding: 7px 11px; }}
  .ghost:hover {{ color: {p['text']}; border-color: {p['muted']}; }}

  .foot {{
    border-top: 1px solid {p['hairline']}; padding: 12px 22px;
    display: grid; gap: 8px; background: {p['raised']};
  }}
  .nav {{ display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center; }}
  .nav .mid {{ text-align: center; font-size: 12px; color: {p['muted']}; }}
  .skip {{ border: 1px solid {p['hairline']}; background: none; color: {p['muted']}; padding: 8px; }}
  .skip.on {{ background: {p['accent']}; border-color: {p['accent']}; color: #fff; }}
  .publish {{
    background: {p['text']}; color: {p['ground']}; border: none;
    padding: 11px; font-weight: 600;
  }}
  .publish:hover {{ background: #fff; }}
  .rot {{ display: grid; grid-template-columns: 1fr auto 1fr; gap: 8px; align-items: center; }}
  .rot button {{ font-size: 17px; line-height: 1; padding: 6px 0; }}
  .rotlabel {{ font-size: 12px; color: {p['muted']}; min-width: 34px; text-align: center; }}
  .stage img {{ transition: transform .2s ease; }}
  .keys {{ font-size: 11px; color: {p['muted']}; text-align: center; }}
  .done {{
    grid-column: 1 / -1; display: grid; place-items: center;
    height: 100vh; color: {p['muted']}; font-size: 15px;
  }}
</style></head>
<body>
  <div class="stage" id="stage">
    <span class="skipbadge">SKIPPED</span>
    <img id="preview" alt="">
  </div>

  <div class="panel">
    <div class="head">
      <div class="counter" id="counter"></div>
      <div class="fname" id="fname"></div>
      <div class="album" id="albumline"></div>
      <div class="bar"><i id="bar"></i></div>
    </div>

    <div class="body">
      <div id="warn"></div>
      <form id="form"></form>
      <h2>Extra fields</h2>
      <div id="extras"></div>
      <button type="button" class="ghost" id="addx">+ add field</button>
    </div>

    <div class="foot">
      <div class="nav">
        <button class="ghost" id="prev">&larr;</button>
        <span class="mid" id="mid"></span>
        <button class="ghost" id="next">&rarr;</button>
      </div>
      <div class="rot">
        <button class="ghost" id="rotl" title="Rotate left (Shift+R)">&#8630;</button>
        <span class="rotlabel" id="rotlabel"></span>
        <button class="ghost" id="rotr" title="Rotate right (R)">&#8631;</button>
      </div>
      <button class="skip" id="skip">Skip this photo</button>
      <button class="publish" id="publish"></button>
      <div class="keys">&larr; &rarr; move &nbsp;·&nbsp; R rotate &nbsp;·&nbsp; S skip &nbsp;·&nbsp; Ctrl+Enter publish</div>
    </div>
  </div>

<script>
const ROWS = {json.dumps(payload)};
const FIELDS = {json.dumps([[k, lbl, ph] for k, lbl, ph in fields])};
ROWS.forEach(r => {{ r.skip = false; r.data.extra = r.data.extra || {{}};
                    r.data.rotate = r.data.rotate || 0; }});

let i = 0;
const $ = id => document.getElementById(id);

function buildForm() {{
  $("form").replaceChildren(...FIELDS.map(([key, label, ph]) => {{
    const l = document.createElement("label"); l.className = "f";
    const s = document.createElement("span"); s.textContent = label;
    const inp = document.createElement("input");
    inp.name = key; inp.placeholder = ph; inp.autocomplete = "off";
    inp.addEventListener("input", () => {{ ROWS[i].data[key] = inp.value.trim(); }});
    l.append(s, inp); return l;
  }}));
}}

function renderExtras() {{
  const box = $("extras"); box.replaceChildren();
  Object.entries(ROWS[i].data.extra).forEach(([k, v]) => box.appendChild(xrow(k, v)));
}}

function xrow(k = "", v = "") {{
  const row = document.createElement("div"); row.className = "xrow";
  const ek = document.createElement("input"); ek.value = k; ek.placeholder = "name";
  const ev = document.createElement("input"); ev.value = v; ev.placeholder = "value";
  const rm = document.createElement("button"); rm.className = "ghost"; rm.textContent = "x";
  const sync = () => {{
    const obj = {{}};
    for (const r of document.querySelectorAll(".xrow")) {{
      const a = r.children[0].value.trim(), b = r.children[1].value.trim();
      if (a) obj[a] = b;
    }}
    ROWS[i].data.extra = obj;
  }};
  ek.addEventListener("input", sync); ev.addEventListener("input", sync);
  rm.addEventListener("click", () => {{ row.remove(); sync(); }});
  row.append(ek, ev, rm); return row;
}}

function show(n) {{
  i = Math.max(0, Math.min(ROWS.length - 1, n));
  const row = ROWS[i];

  $("preview").src = "/preview/" + i + ".webp";
  applyRotation();
  // keep the neighbours warm so stepping through feels instant
  [i + 1, i - 1].forEach(j => {{
    if (j >= 0 && j < ROWS.length) new Image().src = "/preview/" + j + ".webp";
  }});

  $("counter").textContent = `Photo ${{i + 1}} of ${{ROWS.length}}`;
  $("fname").textContent = row.id;
  $("albumline").textContent = row.album ? "album: " + row.album : "";
  $("bar").style.width = ((i + 1) / ROWS.length * 100) + "%";

  $("warn").replaceChildren(...row.warnings.map(w => {{
    const d = document.createElement("div"); d.className = "warn"; d.textContent = w; return d;
  }}));

  for (const inp of document.querySelectorAll("#form input")) {{
    inp.value = row.data[inp.name] || "";
  }}
  renderExtras();

  $("skip").classList.toggle("on", row.skip);
  $("skip").textContent = row.skip ? "Skipped - click to include" : "Skip this photo";
  $("stage").classList.toggle("skipped", row.skip);
  $("prev").disabled = i === 0;
  $("next").disabled = i === ROWS.length - 1;
  updateCounts();
}}

function updateCounts() {{
  const keep = ROWS.filter(r => !r.skip).length;
  $("publish").textContent = `Publish ${{keep}} photo${{keep === 1 ? "" : "s"}}`;
  $("publish").disabled = keep === 0;
  const skipped = ROWS.length - keep;
  $("mid").textContent = skipped ? `${{skipped}} skipped` : "";
}}

function applyRotation() {{
  const deg = ROWS[i].data.rotate || 0;
  const img = $("preview");
  img.style.transform = `rotate(${{deg}}deg)`;
  // a quarter turn swaps which axis has to fit the box
  img.style.maxWidth  = (deg % 180) ? "none" : "100%";
  img.style.maxHeight = (deg % 180) ? "none" : "100%";
  if (deg % 180) {{
    const box = $("stage").getBoundingClientRect();
    img.style.maxWidth  = (box.height - 48) + "px";
    img.style.maxHeight = (box.width  - 48) + "px";
  }}
  $("rotlabel").textContent = deg ? deg + "°" : "";
}}

function rotate(delta) {{
  ROWS[i].data.rotate = (((ROWS[i].data.rotate || 0) + delta) % 360 + 360) % 360;
  applyRotation();
}}

$("rotl").onclick = () => rotate(-90);
$("rotr").onclick = () => rotate(90);
$("prev").onclick = () => show(i - 1);
$("next").onclick = () => show(i + 1);
$("addx").onclick = () => $("extras").appendChild(xrow());
$("skip").onclick = () => {{ ROWS[i].skip = !ROWS[i].skip; show(i); }};

$("publish").onclick = async () => {{
  await fetch("/", {{
    method: "POST", headers: {{ "Content-Type": "application/json" }},
    body: JSON.stringify({{ action: "publish",
      rows: ROWS.map(r => ({{ id: r.id, data: r.data, skip: r.skip }})) }})
  }});
  const keep = ROWS.filter(r => !r.skip).length;
  document.body.replaceChildren(Object.assign(document.createElement("div"), {{
    className: "done",
    textContent: `Publishing ${{keep}} photo${{keep === 1 ? "" : "s"}} - back to the terminal.`
  }}));
}};

document.addEventListener("keydown", e => {{
  if (e.target.tagName === "INPUT" && !(e.ctrlKey || e.metaKey)) return;
  if (e.key === "ArrowRight") {{ e.preventDefault(); show(i + 1); }}
  else if (e.key === "ArrowLeft") {{ e.preventDefault(); show(i - 1); }}
  else if (e.key === "s" || e.key === "S") {{ ROWS[i].skip = !ROWS[i].skip; show(i); }}
  else if (e.key === "r") {{ rotate(90); }}
  else if (e.key === "R") {{ rotate(-90); }}
  else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) $("publish").click();
}});

buildForm();
show(0);
</script>
</body></html>"""
