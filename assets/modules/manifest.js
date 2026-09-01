/* The manifest and every image live in the R2 bucket, so publishing a photo
   never touches this repository. */

export const BUCKET = "https://pub-9775c4eec7a34ee9bedf8364e574d557.r2.dev";

export async function loadManifest() {
  const res = await fetch(`${BUCKET}/photos.json`, { cache: "no-cache" });
  if (!res.ok) throw new Error(`manifest returned ${res.status}`);

  // tolerate a bare array, which is what the manifest was before albums
  const data = await res.json();
  return {
    photos: Array.isArray(data) ? data : data.photos || [],
    albums: (Array.isArray(data) ? [] : data.albums) || [],
  };
}

/* Falls back to 3:2 so a manifest entry missing its dimensions still lays out
   as a photograph rather than collapsing to nothing. */
export const aspect = (w, h) => (w || 3) / (h || 2);

/* Tile and thumbnail paths carry a fingerprint of the source file, so
   re-tiling a photo yields a new URL instead of colliding with a cached copy
   of its old self. That is what makes it safe to serve them as immutable. */
const stamped = (id, rev) => (rev ? `${id}__${rev}` : id);

export const thumbUrl = (id, rev) => `${BUCKET}/thumbs/${stamped(id, rev)}.webp`;
export const tileUrl  = (id, rev) => `${BUCKET}/${stamped(id, rev)}.dzi`;
