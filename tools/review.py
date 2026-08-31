"""
The metadata review step: opens a local page showing the photo alongside its
metadata, lets you correct or fill anything, and waits for you to confirm.

The server exists only while you have the form open and shuts itself down the
moment you press Confirm or Cancel. Nothing about the published site depends
on it.
"""

import http.server
import json
import socket
import threading
import webbrowser
from pathlib import Path

import config

PALETTE = {
    "ground": "#131211",
    "raised": "#1C1A18",
    "hairline": "#2E2A26",
    "text": "#EDE9E3",
    "muted": "#9A928A",
    "accent": "#C4553D",
}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def review(data, thumb_path, warnings=None, open_browser=True):
    """
    Show the form. Returns the edited dict, or None if the user cancelled.
    """
    warnings = warnings or []
    result = {"data": None, "done": threading.Event()}
    thumb_bytes = Path(thumb_path).read_bytes()
    page = _render(data, warnings).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass  # keep the terminal clean

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path.startswith("/preview"):
                self._send(200, thumb_bytes, "image/webp")
            elif self.path == "/" or self.path.startswith("/?"):
                self._send(200, page, "text/html; charset=utf-8")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if payload.get("action") == "confirm":
                result["data"] = payload.get("data")
            self._send(200, b'{"ok":true}', "application/json")
            result["done"].set()

    port = _free_port()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = f"http://127.0.0.1:{port}/"
    print(f"  review form: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)

    try:
        result["done"].wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()

    return result["data"]


def _render(data, warnings):
    p = PALETTE
    fields_html = []
    for key, label, placeholder in config.METADATA_FIELDS:
        value = str(data.get(key, "") or "")
        missing = " missing" if not value else ""
        fields_html.append(f"""
      <label class="field{missing}">
        <span class="label">{label}</span>
        <input name="{key}" value="{_esc(value)}" placeholder="{_esc(placeholder)}" autocomplete="off">
      </label>""")

    extra = data.get("extra") or {}
    extra_rows = "".join(
        f'<div class="extra-row"><input class="ek" value="{_esc(k)}" placeholder="name">'
        f'<input class="ev" value="{_esc(str(v))}" placeholder="value">'
        f'<button type="button" class="rm">remove</button></div>'
        for k, v in extra.items()
    )

    warn_html = ""
    if warnings:
        items = "".join(f"<li>{_esc(w)}</li>" for w in warnings)
        warn_html = f'<div class="warn"><ul>{items}</ul></div>'

    missing_count = sum(1 for k, _, _ in config.METADATA_FIELDS if not data.get(k))
    subtitle = (
        f"{missing_count} field{'s' if missing_count != 1 else ''} empty"
        if missing_count else "all fields present"
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Review — {_esc(data.get('id',''))}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh; background: {p['ground']}; color: {p['text']};
    font: 15px/1.55 -apple-system, "Segoe UI", system-ui, sans-serif;
    display: grid; grid-template-columns: minmax(0,1fr) 460px;
  }}
  @media (max-width: 900px) {{ body {{ grid-template-columns: 1fr; }} }}

  .preview {{
    position: sticky; top: 0; height: 100vh; padding: 32px;
    display: grid; place-items: center; background: {p['ground']};
  }}
  .preview img {{
    max-width: 100%; max-height: calc(100vh - 64px);
    object-fit: contain; display: block;
  }}

  .panel {{
    padding: 40px 36px 120px; border-left: 1px solid {p['hairline']};
    background: {p['raised']}; overflow-y: auto; max-height: 100vh;
  }}
  h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 2px; letter-spacing: -0.01em; }}
  .sub {{ color: {p['muted']}; font-size: 13px; margin-bottom: 26px; }}

  .warn {{
    border-left: 2px solid {p['accent']}; background: rgba(196,85,61,.09);
    padding: 10px 14px; margin-bottom: 24px; font-size: 13px; color: {p['text']};
  }}
  .warn ul {{ margin: 0; padding-left: 16px; }}

  .field {{ display: block; margin-bottom: 16px; }}
  .label {{
    display: block; font-size: 12px; color: {p['muted']}; margin-bottom: 5px;
  }}
  .field.missing .label::after {{
    content: " empty"; color: {p['accent']}; font-size: 11px;
  }}
  input {{
    width: 100%; padding: 9px 11px; font: inherit; font-size: 14px;
    color: {p['text']}; background: {p['ground']};
    border: 1px solid {p['hairline']}; border-radius: 3px;
  }}
  input:focus {{ outline: none; border-color: {p['accent']}; }}

  h2 {{
    font-size: 12px; color: {p['muted']}; font-weight: 500;
    margin: 30px 0 10px; padding-top: 20px; border-top: 1px solid {p['hairline']};
  }}
  .extra-row {{ display: grid; grid-template-columns: 1fr 1fr auto; gap: 6px; margin-bottom: 6px; }}
  .extra-row button, .add {{
    background: none; border: 1px solid {p['hairline']}; color: {p['muted']};
    border-radius: 3px; padding: 8px 12px; font: inherit; font-size: 13px; cursor: pointer;
  }}
  .extra-row button:hover, .add:hover {{ color: {p['text']}; border-color: {p['muted']}; }}
  .add {{ margin-top: 4px; }}

  .actions {{
    position: fixed; bottom: 0; right: 0; width: 460px;
    padding: 16px 36px; background: {p['raised']};
    border-top: 1px solid {p['hairline']}; border-left: 1px solid {p['hairline']};
    display: flex; gap: 10px; align-items: center;
  }}
  @media (max-width: 900px) {{ .actions {{ width: 100%; }} }}
  .confirm {{
    flex: 1; padding: 11px; font: inherit; font-weight: 600; cursor: pointer;
    background: {p['text']}; color: {p['ground']}; border: none; border-radius: 3px;
  }}
  .confirm:hover {{ background: #fff; }}
  .cancel {{
    padding: 11px 16px; font: inherit; cursor: pointer; color: {p['muted']};
    background: none; border: 1px solid {p['hairline']}; border-radius: 3px;
  }}
  .cancel:hover {{ color: {p['text']}; }}
  .done {{ display: grid; place-items: center; height: 100vh; color: {p['muted']}; }}
</style></head>
<body>
  <div class="preview"><img src="/preview.webp" alt=""></div>
  <div class="panel">
    <h1>{_esc(data.get('id',''))}</h1>
    <div class="sub">{data.get('width','?')} × {data.get('height','?')} · {subtitle}</div>
    {warn_html}
    <form id="f">{''.join(fields_html)}</form>

    <h2>Extra fields — anything the camera didn't record</h2>
    <div id="extras">{extra_rows}</div>
    <button type="button" class="add" id="add">+ add field</button>
  </div>

  <div class="actions">
    <button class="cancel" id="cancel">Cancel</button>
    <button class="confirm" id="confirm">Confirm &amp; publish</button>
  </div>

<script>
  const extras = document.getElementById('extras');

  document.getElementById('add').onclick = () => {{
    const row = document.createElement('div');
    row.className = 'extra-row';
    row.innerHTML = '<input class="ek" placeholder="name"><input class="ev" placeholder="value"><button type="button" class="rm">remove</button>';
    extras.appendChild(row);
    row.querySelector('.ek').focus();
  }};

  extras.addEventListener('click', e => {{
    if (e.target.classList.contains('rm')) e.target.closest('.extra-row').remove();
  }});

  function collect() {{
    const data = {json.dumps(data)};
    for (const el of document.querySelectorAll('#f input')) data[el.name] = el.value.trim();
    const extra = {{}};
    for (const row of extras.querySelectorAll('.extra-row')) {{
      const k = row.querySelector('.ek').value.trim();
      const v = row.querySelector('.ev').value.trim();
      if (k) extra[k] = v;
    }}
    data.extra = extra;
    return data;
  }}

  async function send(action) {{
    await fetch('/', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ action, data: action === 'confirm' ? collect() : null }})
    }});
    document.body.innerHTML =
      '<div class="done">' +
      (action === 'confirm' ? 'Confirmed — back to the terminal.' : 'Cancelled.') +
      '</div>';
  }}

  document.getElementById('confirm').onclick = () => send('confirm');
  document.getElementById('cancel').onclick  = () => send('cancel');

  // cmd/ctrl+enter confirms
  document.addEventListener('keydown', e => {{
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') send('confirm');
  }});
</script>
</body></html>"""


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
