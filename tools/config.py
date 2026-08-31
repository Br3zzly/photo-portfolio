"""
Settings for the publish pipeline. Edit these; nothing else should need touching.
"""

# --- Cloudflare R2 -----------------------------------------------------------
# R2_REMOTE is the name you gave the remote when you ran `rclone config`.
R2_REMOTE = "r2"
R2_BUCKET = "photo-portfolio"

# The bucket's public URL. Swap this for your custom domain when you get one --
# it is the only line that needs to change, and old tiles keep working.
R2_PUBLIC_URL = "https://pub-9775c4eec7a34ee9bedf8364e574d557.r2.dev"

# --- Tiling ------------------------------------------------------------------
# 512 gives ~4x fewer files than the 254 default for the same total bytes.
TILE_SIZE = 512
OVERLAP = 1

# WebP quality for tiles. 90 was chosen after comparing 80/90/lossless on real
# files: on detailed content 90 costs only 8-31% more than 80, and lossless
# costs 26x for no visible gain.
TILE_QUALITY = 90

# --- Gallery assets ----------------------------------------------------------
# Thumbnails are generated at 2x the largest displayed size so they stay sharp
# on retina screens.
THUMB_WIDTH = 1000
THUMB_QUALITY = 82

# The blurred placeholder inlined into the manifest. Tiny on purpose: it is
# base64'd into JSON, so every byte is paid for on first load.
LQIP_WIDTH = 24

# --- Publishing --------------------------------------------------------------
# Tiles never change once written -- their path carries a fingerprint of the
# source, so re-tiling produces a new URL. That makes `immutable` truthful.
TILE_CACHE_CONTROL = "public, max-age=31536000, immutable"

# The manifest changes every time you publish, so it must not be cached hard.
MANIFEST_CACHE_CONTROL = "public, max-age=60"

MANIFEST_NAME = "photos.json"

# Fields shown in the review form, in order.
# key -> (label, placeholder)
# Of those, the ones that come from the camera. Title and caption are yours to
# write, so their being empty is normal and must not be reported as a problem.
EXIF_FIELDS = ["camera", "lens", "focal", "aperture", "shutter", "iso", "date"]

METADATA_FIELDS = [
    ("title",    "Title",        "Untitled"),
    ("caption",  "Caption",      "optional, one or two lines"),
    ("date",     "Date",         "YYYY-MM-DD"),
    ("camera",   "Camera",       "e.g. SONY ILCE-7RM6"),
    ("lens",     "Lens",         "e.g. FE 85mm F1.4 GM II"),
    ("focal",    "Focal length", "e.g. 85mm"),
    ("aperture", "Aperture",     "e.g. f/1.4"),
    ("shutter",  "Shutter",      "e.g. 1/50"),
    ("iso",      "ISO",          "e.g. 100"),
]
