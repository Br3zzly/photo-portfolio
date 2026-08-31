"""
Image processing: EXIF, tiles, thumbnails, placeholders, sidecar metadata.

Everything here is idempotent -- running it twice does not redo work or
duplicate anything, unless force=True.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = ROOT / "photos"
TILES_DIR = ROOT / "tiles"
THUMBS_DIR = ROOT / "thumbs"


# --- locating the external tools --------------------------------------------
# winget installs put binaries on PATH, but a terminal opened before the
# install has a stale PATH and will not see them. Rather than telling the user
# to restart their shell, look in the usual install locations too.

_TOOL_CACHE = {}


def _registry_path_dirs():
    """
    The live PATH from the registry.

    A terminal opened before an install keeps a stale copy of PATH in its
    environment, so a freshly installed tool looks missing even though it is
    there. The registry always has the current value.
    """
    if sys.platform != "win32":
        return []
    import winreg

    dirs = []
    for root, key in (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, "Environment"),
    ):
        try:
            with winreg.OpenKey(root, key) as k:
                value, _ = winreg.QueryValueEx(k, "Path")
                dirs.extend(os.path.expandvars(d) for d in value.split(";") if d.strip())
        except OSError:
            continue
    return dirs


def find_tool(name):
    """Return a runnable path for an external tool, or exit with advice."""
    if name in _TOOL_CACHE:
        return _TOOL_CACHE[name]

    found = shutil.which(name)

    if not found and sys.platform == "win32":
        for d in _registry_path_dirs():
            candidate = Path(d) / f"{name}.exe"
            if candidate.is_file():
                found = str(candidate)
                break

    if not found:
        sys.exit(
            f"\n  Could not find '{name}'.\n"
            f"  Install it with:  winget install {_WINGET_IDS.get(name, name)}\n"
            f"  Then open a new terminal.\n"
        )

    _TOOL_CACHE[name] = found
    return found


_WINGET_IDS = {
    "vips": "libvips.libvips",
    "exiftool": "OliverBetz.ExifTool",
    "rclone": "Rclone.Rclone",
}


def run(args, **kwargs):
    """Run a subprocess, raising with useful output if it fails."""
    result = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(str(a) for a in args)}\n{result.stderr.strip()}"
        )
    return result.stdout


# --- EXIF -------------------------------------------------------------------

def read_exif(src):
    """Pull the fields the metadata bar needs. Missing keys simply stay absent."""
    out = run([
        find_tool("exiftool"), "-json", "-n" if False else "-s",
        "-Make", "-Model", "-LensModel", "-LensID",
        "-FocalLength", "-FNumber", "-ExposureTime", "-ISO",
        "-DateTimeOriginal", "-CreateDate",
        str(src),
    ])
    try:
        raw = json.loads(out)[0]
    except (json.JSONDecodeError, IndexError):
        raw = {}

    def clean(v):
        return str(v).strip() if v not in (None, "") else ""

    make = clean(raw.get("Make"))
    model = clean(raw.get("Model"))
    # "SONY" + "ILCE-7RM6" -> "SONY ILCE-7RM6", but avoid "SONY SONY ..."
    if make and model and not model.upper().startswith(make.upper()):
        camera = f"{make} {model}"
    else:
        camera = model or make

    # "85.0 mm" -> "85mm", but keep "10.5mm" intact
    focal = clean(raw.get("FocalLength")).replace(" mm", "mm")
    focal = re.sub(r"\.0(?=mm$)", "", focal)

    aperture = clean(raw.get("FNumber"))
    if aperture and not aperture.startswith("f/"):
        aperture = f"f/{aperture}"

    shutter = clean(raw.get("ExposureTime"))

    date = clean(raw.get("DateTimeOriginal")) or clean(raw.get("CreateDate"))
    # EXIF dates look like 2026:08:31 11:14:04
    m = re.match(r"(\d{4}):(\d{2}):(\d{2})", date)
    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""

    return {
        "camera": camera,
        "lens": clean(raw.get("LensModel")) or clean(raw.get("LensID")),
        "focal": focal,
        "aperture": aperture,
        "shutter": shutter,
        "iso": clean(raw.get("ISO")),
        "date": date,
    }


def colour_profile(src):
    """
    The embedded colour profile name, e.g. 'sRGB IEC61966-2.1'.

    Anything other than sRGB renders wrong in some browsers, so the caller
    warns rather than silently publishing shifted colour.
    """
    out = run([find_tool("exiftool"), "-s", "-s", "-s", "-ProfileDescription", str(src)])
    return out.strip()


def is_srgb(src):
    return "srgb" in colour_profile(src).lower().replace(" ", "")


def has_gps(src):
    """GPS must never be published. Returns True if any GPS tag is present."""
    out = run([find_tool("exiftool"), "-s", "-GPSLatitude", "-GPSLongitude", str(src)])
    return bool(out.strip())


# --- image derivatives ------------------------------------------------------

def dimensions(src):
    # vipsheader is its own binary; `vips header` is not a valid action
    vh = find_tool("vipsheader")
    w = int(run([vh, "-f", "width", str(src)]).strip())
    h = int(run([vh, "-f", "height", str(src)]).strip())
    return w, h


def make_tiles(src, photo_id, force=False):
    """Build the DeepZoom pyramid. Returns (tile_count, total_bytes)."""
    TILES_DIR.mkdir(exist_ok=True)
    # photo_id may be "Album/name", so make the album subfolder too
    (TILES_DIR / photo_id).parent.mkdir(parents=True, exist_ok=True)
    dzi = TILES_DIR / f"{photo_id}.dzi"
    files_dir = TILES_DIR / f"{photo_id}_files"

    if dzi.exists() and files_dir.is_dir() and not force:
        return _tile_stats(files_dir), True  # already done

    if files_dir.exists():
        shutil.rmtree(files_dir)
    dzi.unlink(missing_ok=True)

    run([
        find_tool("vips"), "dzsave", str(src), str(TILES_DIR / photo_id),
        "--tile-size", str(config.TILE_SIZE),
        "--overlap", str(config.OVERLAP),
        "--suffix", f".webp[Q={config.TILE_QUALITY}]",
    ])
    return _tile_stats(files_dir), False


def _tile_stats(files_dir):
    count = 0
    total = 0
    for p in files_dir.rglob("*.webp"):
        count += 1
        total += p.stat().st_size
    return count, total


def make_thumb(src, photo_id, force=False):
    THUMBS_DIR.mkdir(exist_ok=True)
    (THUMBS_DIR / photo_id).parent.mkdir(parents=True, exist_ok=True)
    dest = THUMBS_DIR / f"{photo_id}.webp"
    if dest.exists() and not force:
        return dest
    # keep=icc drops EXIF/XMP but preserves the colour profile. Without this,
    # vips copies the source's ~100KB of metadata into every thumbnail.
    run([
        find_tool("vips"), "thumbnail", str(src),
        f"{dest}[Q={config.THUMB_QUALITY},keep=icc]", str(config.THUMB_WIDTH),
    ])
    return dest


def make_lqip(src):
    """A tiny blurred placeholder, returned as a data: URI for inlining."""
    tmp = TILES_DIR / f".lqip-tmp.webp"
    TILES_DIR.mkdir(exist_ok=True)
    # keep=none: at 24px a colour profile would outweigh the image itself
    run([
        find_tool("vips"), "thumbnail", str(src),
        f"{tmp}[Q=40,keep=none]", str(config.LQIP_WIDTH),
    ])
    data = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    return "data:image/webp;base64," + base64.b64encode(data).decode("ascii")


# --- sidecar metadata -------------------------------------------------------
# The sidecar next to each source photo is the durable source of truth. The
# bucket manifest is generated from these, so a lost manifest costs nothing.

def sidecar_path(photo_id):
    return PHOTOS_DIR / f"{photo_id}.json"


def load_sidecar(photo_id):
    p = sidecar_path(photo_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def save_sidecar(photo_id, data):
    p = sidecar_path(photo_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    # utf-8 with no BOM: json.loads in the browser rejects a BOM
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def init_sidecar(src, photo_id):
    """Build a fresh sidecar prefilled from whatever EXIF exists."""
    w, h = dimensions(src)
    data = {
        "id": photo_id,
        "title": "",
        "caption": "",
        "width": w,
        "height": h,
        "extra": {},
    }
    data.update(read_exif(src))
    return data
