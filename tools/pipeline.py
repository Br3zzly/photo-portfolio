"""
Image processing: EXIF, tiles, thumbnails, placeholders, sidecar metadata.

Everything here is idempotent -- running it twice does not redo work or
duplicate anything, unless force=True.
"""

import base64
import hashlib
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
        find_tool("exiftool"), "-json", "-s",
        "-Make", "-Model", "-LensMake", "-LensModel", "-LensID",
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

    def join_make_model(mk, md):
        """'SONY' + 'ILCE-7RM6' -> 'SONY ILCE-7RM6', without doubling the make
        when the model already carries it (e.g. 'Viltrox 85mm F1.8')."""
        if mk and md and not md.upper().startswith(mk.upper()):
            return f"{mk} {md}"
        return md or mk

    make = clean(raw.get("Make"))
    # some bodies write "NIKON CORPORATION"; the mark is just the brand
    make = make.replace(" CORPORATION", "").replace(" Corporation", "").strip()
    model = clean(raw.get("Model"))
    camera = join_make_model(make, model)

    lens_make = clean(raw.get("LensMake"))
    lens_model = clean(raw.get("LensModel")) or clean(raw.get("LensID"))
    lens = join_make_model(lens_make, lens_model)

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
        # kept separately so the plate can look up the maker's logo
        "make": make,
        "lens": lens,
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

def dimensions(src, rotate=0):
    """Dimensions as the photograph will actually be published."""
    # vipsheader is its own binary; `vips header` is not a valid action
    vh = find_tool("vipsheader")
    w = int(run([vh, "-f", "width", str(src)]).strip())
    h = int(run([vh, "-f", "height", str(src)]).strip())
    if orientation_swaps_axes(src):
        w, h = h, w
    if rotate in (90, 270):
        w, h = h, w
    return w, h


def orientation_swaps_axes(src):
    """True when the EXIF orientation flag turns a landscape file portrait."""
    out = run([find_tool("exiftool"), "-s", "-s", "-s", "-n", "-Orientation", str(src)])
    try:
        # 5..8 are the transposed orientations
        return int(out.strip()) >= 5
    except ValueError:
        return False


def _source(src, rotate=0):
    """
    A vips input specification honouring EXIF orientation.

    dzsave does not apply the orientation flag on its own -- only `thumbnail`
    does -- so tiles came out sideways for any photo the camera tagged as
    rotated. The [autorotate] loader option fixes that at load time, with no
    re-encode of the original.

    A manual rotation on top needs a real pass, so it goes through an
    uncompressed temporary in vips' own format: fast, and lossless.
    """
    spec = f"{src}[autorotate]"
    if not rotate:
        return spec, None

    TILES_DIR.mkdir(exist_ok=True)
    tmp = TILES_DIR / f".rot-{os.getpid()}-{Path(src).stem}.v"
    run([find_tool("vips"), "rot", spec, str(tmp), f"d{rotate}"])
    return str(tmp), tmp


def content_rev(src, rotate=0):
    """
    A short fingerprint of everything that affects the tiles.

    Tiles are served with `immutable`, which promises a URL's bytes will never
    change. Re-tiling a photo -- to correct its rotation, say -- broke that
    promise and left browsers showing a year-old copy. Putting the fingerprint
    in the path means changed tiles are simply a different URL, so the promise
    holds and nothing goes stale.
    """
    st = Path(src).stat()
    key = (f"{st.st_size}:{int(st.st_mtime)}:{rotate}:"
           f"{config.TILE_QUALITY}:{config.TILE_SIZE}:{config.OVERLAP}")
    return hashlib.sha1(key.encode()).hexdigest()[:8]


def tile_base(photo_id, rev):
    """Path stem for a photo's pyramid, e.g. 'Kyoto/temple__a1b2c3d4'."""
    return f"{photo_id}__{rev}"


def _drop_other_revs(photo_id, keep_rev):
    """Remove pyramids for superseded revisions of the same photograph."""
    parent = (TILES_DIR / photo_id).parent
    stem = Path(photo_id).name
    if not parent.is_dir():
        return
    for p in parent.glob(f"{stem}__*"):
        if p.name.startswith(f"{stem}__{keep_rev}"):
            continue
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


def make_tiles(src, photo_id, force=False, rotate=0):
    """Build the DeepZoom pyramid. Returns ((count, bytes), cached, rev)."""
    TILES_DIR.mkdir(exist_ok=True)
    # photo_id may be "Album/name", so make the album subfolder too
    (TILES_DIR / photo_id).parent.mkdir(parents=True, exist_ok=True)

    rev = content_rev(src, rotate)
    base = tile_base(photo_id, rev)
    dzi = TILES_DIR / f"{base}.dzi"
    files_dir = TILES_DIR / f"{base}_files"

    if dzi.exists() and files_dir.is_dir() and not force:
        return _tile_stats(files_dir), True, rev

    if files_dir.exists():
        shutil.rmtree(files_dir)
    dzi.unlink(missing_ok=True)

    spec, tmp = _source(src, rotate)
    try:
        run([
            find_tool("vips"), "dzsave", spec, str(TILES_DIR / base),
            "--tile-size", str(config.TILE_SIZE),
            "--overlap", str(config.OVERLAP),
            "--suffix", f".webp[Q={config.TILE_QUALITY}]",
        ])
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    _drop_other_revs(photo_id, rev)
    return _tile_stats(files_dir), False, rev


def _tile_stats(files_dir):
    count = 0
    total = 0
    for p in files_dir.rglob("*.webp"):
        count += 1
        total += p.stat().st_size
    return count, total


def make_thumb(src, photo_id, force=False, rotate=0, rev=None):
    """Thumbnails carry the same fingerprint as the tiles, for the same
    reason: they are cached hard and regenerated when a photo is re-tiled."""
    THUMBS_DIR.mkdir(exist_ok=True)
    (THUMBS_DIR / photo_id).parent.mkdir(parents=True, exist_ok=True)
    stem = tile_base(photo_id, rev) if rev else photo_id
    dest = THUMBS_DIR / f"{stem}.webp"
    if dest.exists() and not force:
        return dest
    # keep=icc drops EXIF/XMP but preserves the colour profile. Without this,
    # vips copies the source's ~100KB of metadata into every thumbnail.
    # `thumbnail` already applies the orientation flag; _source only matters
    # for a manual rotation on top of it
    spec, tmp = _source(src, rotate)
    try:
        run([
            find_tool("vips"), "thumbnail", spec,
            f"{dest}[Q={config.THUMB_QUALITY},keep=icc]", str(config.THUMB_WIDTH),
        ])
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    return dest


def make_lqip(src, rotate=0):
    """A tiny blurred placeholder, returned as a data: URI for inlining."""
    tmp = TILES_DIR / f".lqip-tmp.webp"
    TILES_DIR.mkdir(exist_ok=True)
    # keep=none: at 24px a colour profile would outweigh the image itself
    spec, rot_tmp = _source(src, rotate)
    try:
        run([
            find_tool("vips"), "thumbnail", spec,
            f"{tmp}[Q=40,keep=none]", str(config.LQIP_WIDTH),
        ])
    finally:
        if rot_tmp:
            rot_tmp.unlink(missing_ok=True)
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
