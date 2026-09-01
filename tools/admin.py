"""
The admin console.

    python tools/admin.py

Opens a browser onto your published gallery with the controls the live site
must never have: a delete button on every photograph, and a way to add more.
Everything runs on this machine -- the tiling needs vips, and the credentials
that write to the bucket are yours and stay here, which is the whole reason
this is not part of the site.

Adding a photograph copies it no further than a staging folder, long enough to
read its EXIF, build its pyramid and push it. Your original stays wherever you
keep it.
"""

import argparse
import http.server
import json
import shutil
import socket
import threading
import time
import traceback
import urllib.parse
import webbrowser
from pathlib import Path

import config
import pipeline
import store
from pipeline import ROOT, STAGING_DIR, TILES_DIR, THUMBS_DIR

UI_DIR = Path(__file__).resolve().parent / "admin_ui"
SOURCE_TYPES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}

# Everything the server knows, guarded by one lock. The jobs are the only
# long-running work and the browser polls them; nothing else is shared.
STATE = {
    "manifest": None,
    "staged": {},        # id -> {"path": Path, "data": {...}, "warnings": [...]}
    "jobs": {},          # job id -> {"lines": [...], "done": bool, "error": str|None}
}
LOCK = threading.Lock()


# --- staging ----------------------------------------------------------------

def photo_id_for(name, folder):
    """
    A picked folder becomes an album, and its name becomes part of the id:

        sunset.jpg              -> "sunset"          (no album)
        Kyoto/temple.jpg        -> "Kyoto/temple"    (album "Kyoto")

    Keeping the album in the id means two albums can both hold a DSC01234.jpg
    without colliding, in the manifest or in the bucket.
    """
    stem = Path(name).stem
    folder = (folder or "").strip().strip("/").replace("\\", "/")
    folder = folder.split("/")[0] if folder else ""
    return (f"{folder}/{stem}", folder) if folder else (stem, "")


def stage(name, folder, body):
    """Write a picked file to the staging folder and read what it can tell us."""
    photo_id, album = photo_id_for(name, folder)
    dest = STAGING_DIR / f"{photo_id}{Path(name).suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)

    warnings = []
    profile = pipeline.colour_profile(dest)
    if profile and not pipeline.is_srgb(dest):
        warnings.append(
            f"Colour profile is '{profile}', not sRGB. Colours may render wrong "
            f"in some browsers -- re-export as sRGB if this photo looks off.")
    if pipeline.has_gps(dest):
        warnings.append(
            "This file contains GPS coordinates. They will NOT be published, "
            "but consider stripping them from your export too.")

    data = {"id": photo_id, "title": "", "caption": "", "extra": {}, "rotate": 0}
    data.update(pipeline.read_exif(dest))
    if album:
        data["album"] = album
    data["width"], data["height"] = pipeline.dimensions(dest, 0)

    labels = {k: label for k, label, _ in config.METADATA_FIELDS}
    missing = [labels[k] for k in config.EXIF_FIELDS if not data.get(k)]
    if missing:
        warnings.append(
            "The camera did not record: " + ", ".join(missing) +
            ". Stacked or heavily edited exports often lose this -- fill in "
            "whatever you know, or leave blank to hide those fields.")

    # a small preview for the review form, rebuilt whenever a rotation is chosen
    pipeline.make_thumb(dest, photo_id, force=True)

    with LOCK:
        STATE["staged"][photo_id] = {"path": dest, "data": data, "warnings": warnings}
    return {"id": photo_id, "album": album, "data": data, "warnings": warnings}


def clear_staging():
    shutil.rmtree(STAGING_DIR, ignore_errors=True)
    with LOCK:
        STATE["staged"] = {}


# --- jobs -------------------------------------------------------------------

def start_job(fn, total=0, label=""):
    """
    Run `fn` on a thread and let the page watch it.

    The page shows a bar, not a transcript, so the job reports how far along it
    is as well as what it is saying. The full detail still goes to the terminal.
    """
    job_id = f"{int(time.time()*1000)}"
    with LOCK:
        STATE["jobs"][job_id] = {"lines": [], "done": False, "error": None,
                                 "total": total, "step": 0, "label": label}

    def log(line, label=None):
        with LOCK:
            job = STATE["jobs"][job_id]
            job["lines"].append(str(line))
            if label is not None:
                job["label"] = label
        print(line, flush=True)

    def step(label=None):
        with LOCK:
            job = STATE["jobs"][job_id]
            job["step"] += 1
            if label is not None:
                job["label"] = label

    log.step = step

    def run():
        try:
            fn(log)
        except Exception as e:                       # noqa: BLE001
            traceback.print_exc()
            with LOCK:
                STATE["jobs"][job_id]["error"] = str(e)
        finally:
            with LOCK:
                STATE["jobs"][job_id]["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return job_id


def publish_job(edits):
    """Tile, upload and record each photograph the review form kept."""
    def work(log):
        manifest = store.load()
        published = 0

        for photo_id, edited in edits.items():
            with LOCK:
                item = STATE["staged"].get(photo_id)
            if not item:
                log(f"  {photo_id}: no longer staged, skipped")
                continue

            src = item["path"]
            rotate = int(edited.get("rotate") or 0)
            entry = dict(item["data"])
            entry.update(edited)
            entry["id"] = photo_id
            entry["rotate"] = rotate
            entry["width"], entry["height"] = pipeline.dimensions(src, rotate)
            if not entry.get("album"):
                entry.pop("album", None)

            log(f"  {photo_id}", label=photo_id)
            t0 = time.time()
            (count, total), cached, rev = pipeline.make_tiles(
                src, photo_id, force=True, rotate=rotate)
            entry["rev"] = rev
            log(f"    {count} tiles, {human(total)} in {time.time()-t0:.1f}s")

            pipeline.make_thumb(src, photo_id, force=True, rotate=rotate, rev=rev)
            entry["lqip"] = pipeline.make_lqip(src, rotate=rotate)

            store.upload(photo_id, rev, log=log)
            store.put(manifest, entry)
            # only once it is safely in the bucket
            store.discard_local(photo_id)
            published += 1
            log.step()

        if not published:
            log("nothing published")
            return

        log("updating the manifest", label="Updating the manifest")
        store.save(manifest)
        log.step()
        with LOCK:
            STATE["manifest"] = manifest
        clear_staging()
        log(f"done -- {published} photograph{'s' if published != 1 else ''} live")

    return start_job(work, total=len(edits) + 1, label="Preparing")


def delete_job(ids):
    def work(log):
        manifest = store.load()
        for photo_id in ids:
            log(f"  {photo_id}", label=photo_id)
            store.purge(photo_id, log=log)
            store.discard_local(photo_id)
            log.step()
        store.drop(manifest, ids)
        log("updating the manifest", label="Updating the manifest")
        store.save(manifest)
        log.step()
        with LOCK:
            STATE["manifest"] = manifest
        log(f"done -- removed {len(ids)} photograph{'s' if len(ids) != 1 else ''}")

    return start_job(work, total=len(ids) + 1, label="Deleting")


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# --- server -----------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # -- helpers
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    # -- routes
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path, query = url.path, urllib.parse.parse_qs(url.query)

        if path in ("/", "/index.html"):
            return self._file(UI_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/admin.css":
            return self._file(UI_DIR / "admin.css", "text/css; charset=utf-8")
        if path == "/admin.js":
            return self._file(UI_DIR / "admin.js", "application/javascript; charset=utf-8")

        if path == "/api/manifest":
            with LOCK:
                cached = STATE["manifest"]
            if cached is None or query.get("refresh"):
                cached = store.load()
                with LOCK:
                    STATE["manifest"] = cached
            return self._send(200, {
                "manifest": cached,
                "bucket": config.R2_PUBLIC_URL,
                "fields": config.METADATA_FIELDS,
            })

        if path == "/api/job":
            job_id = (query.get("id") or [""])[0]
            with LOCK:
                job = STATE["jobs"].get(job_id)
            return self._send(200, job or {"lines": [], "done": True,
                                           "error": "no such job"})

        if path == "/api/preview":
            photo_id = (query.get("id") or [""])[0]
            rotate = int((query.get("rotate") or ["0"])[0])
            with LOCK:
                item = STATE["staged"].get(photo_id)
            if not item:
                return self._send(404, {"error": "not staged"})
            thumb = pipeline.make_thumb(item["path"], photo_id,
                                        force=True, rotate=rotate)
            return self._file(thumb, "image/webp")

        return self._send(404, {"error": "not found"})

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        path, query = url.path, urllib.parse.parse_qs(url.query)

        try:
            if path == "/api/stage":
                # one raw request per file: no multipart to parse, and the
                # browser can stream a 16MB original straight in
                name = (query.get("name") or ["photo.jpg"])[0]
                folder = (query.get("folder") or [""])[0]
                if Path(name).suffix.lower() not in SOURCE_TYPES:
                    return self._send(400, {"error": f"{name}: not an image"})
                return self._send(200, stage(name, folder, self._body()))

            if path == "/api/publish":
                edits = json.loads(self._body() or b"{}")
                return self._send(200, {"job": publish_job(edits)})

            if path == "/api/delete":
                ids = json.loads(self._body() or b"{}").get("ids") or []
                if not ids:
                    return self._send(400, {"error": "nothing to delete"})
                return self._send(200, {"job": delete_job(ids)})

            if path == "/api/discard":
                clear_staging()
                return self._send(200, {"ok": True})

        except Exception as e:                       # noqa: BLE001
            traceback.print_exc()
            return self._send(500, {"error": str(e)})

        return self._send(404, {"error": "not found"})

    def _file(self, path, ctype):
        try:
            body = Path(path).read_bytes()
        except OSError:
            return self._send(404, {"error": f"missing {path}"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    ap = argparse.ArgumentParser(description="Manage the published gallery.")
    ap.add_argument("--no-browser", action="store_true",
                    help="print the URL instead of opening a browser")
    ap.add_argument("--port", type=int, default=0, help="fixed port")
    args = ap.parse_args()

    # anything left staged is from a run that did not finish; it was never
    # published, and the originals it came from are still wherever they live
    clear_staging()
    for d in (TILES_DIR, THUMBS_DIR):
        shutil.rmtree(d, ignore_errors=True)

    pipeline.find_tool("vips")          # fail now, not halfway through a publish
    pipeline.find_tool("exiftool")
    pipeline.find_tool("rclone")

    port = args.port or free_port()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"

    print(f"\n  admin console: {url}")
    print("  ctrl-c to stop\n")
    if not args.no_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        server.server_close()
        clear_staging()


if __name__ == "__main__":
    main()
