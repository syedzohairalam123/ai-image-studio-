"""Procedural Art Engine
========================

A dependency-light, fully local generative art system used by the ``stub``
AI provider (and anywhere else the app needs a real, unique image without an
external paid API). It has no network dependency and no model weights to
download — every image is synthesized on the fly from numpy/scipy signal
processing + Pillow compositing, seeded deterministically from the prompt so
the same prompt + style + seed always reproduces the same artwork.

Techniques used (all genuinely computed, nothing is a static placeholder):

* Multi-octave fractal value noise (built from small random grids upsampled
  with bicubic interpolation — the classic "value noise" technique used in
  procedural shaders).
* Domain warping (``scipy.ndimage.map_coordinates``) to give noise fields an
  organic, flowing quality instead of a raw grid look.
* True nearest-seed Voronoi mosaics via ``scipy.spatial.cKDTree``.
* Metaball / organic blob fields with smoothstep thresholding.
* A tiny Lambertian + specular lighting model (real vector math on a
  synthetic height field) used to give the "3d" style a genuine sense of
  depth and light.
* Colour-theory-driven palette generation (complementary / triadic /
  analogous / monochrome schemes) with a keyword → hue lexicon so prompts
  like "sunset over the ocean" bias toward warm/cool colours automatically.

Every public entry point returns raw PNG bytes so callers never need to know
about the internals.
"""

from __future__ import annotations

import hashlib
import math
from typing import Optional, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageEnhance

try:
    from scipy.ndimage import map_coordinates, gaussian_filter
    from scipy.spatial import cKDTree
    _HAS_SCIPY = True
except Exception:  # pragma: no cover - scipy is a hard dependency in requirements.txt
    _HAS_SCIPY = False


# ============================================================
# DETERMINISTIC SEEDING
# ============================================================

def _seed_from_text(*parts) -> int:
    """Hash arbitrary text/number parts into a stable 32-bit seed."""
    joined = "||".join(str(p) for p in parts if p is not None)
    digest = hashlib.sha256(joined.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) % (2 ** 32 - 1)


def _make_rng(prompt: str, style: str, seed: Optional[int], salt: str = "") -> np.random.Generator:
    """Build a deterministic RNG from prompt + style + optional seed.

    The explicit seed (when given) is *folded together* with the prompt
    rather than replacing it outright — this keeps "same seed, same prompt"
    reproducible while still ensuring "same seed, different prompt" produces
    a visibly different piece of art (an explicit seed acts as a variation
    selector for a given prompt, matching how real generators behave).
    """
    prompt_seed = _seed_from_text(prompt, style)
    base_seed = _seed_from_text(prompt_seed, seed) if seed is not None else prompt_seed
    return np.random.default_rng(_seed_from_text(base_seed, salt))


# ============================================================
# COLOR THEORY — keyword lexicon + palette schemes
# ============================================================

# Hue in degrees [0, 360). Mixed prompts blend the matched hues.
_KEYWORD_HUES = {
    "sunset": 22, "sunrise": 34, "dawn": 38, "dusk": 18, "fire": 14, "flame": 16,
    "lava": 8, "autumn": 27, "fall": 30, "desert": 36, "gold": 45, "golden": 46,
    "amber": 40, "red": 355, "crimson": 350, "orange": 28, "coral": 10,
    "yellow": 52, "sun": 48, "sand": 44, "honey": 42, "lemon": 55,
    "forest": 128, "jungle": 122, "leaf": 112, "green": 120, "grass": 100,
    "emerald": 150, "mint": 162, "nature": 116, "garden": 104, "tree": 118,
    "ocean": 204, "sea": 198, "sky": 210, "water": 196, "blue": 218,
    "ice": 194, "winter": 202, "arctic": 197, "rain": 214, "storm": 222,
    "galaxy": 262, "space": 254, "nebula": 274, "cosmic": 258, "stars": 250,
    "purple": 272, "violet": 278, "magic": 284, "mystic": 268, "fantasy": 266,
    "dream": 260, "lavender": 258,
    "pink": 328, "rose": 338, "cherry": 334, "flower": 318, "blossom": 322,
    "cyberpunk": 300, "neon": 302, "futuristic": 188, "chrome": 205,
    "metal": 208, "steel": 206, "silver": 210, "electric": 296,
    "candy": 312, "bubblegum": 320,
    "lime": 92, "olive": 70, "teal": 178, "cyan": 186, "turquoise": 174,
    "peach": 24, "cream": 42, "beige": 38, "tan": 34,
}

_DESATURATE_WORDS = ("noir", "grayscale", "greyscale", "monochrome", "black and white", "sepia", "vintage")
_DARK_WORDS = ("night", "midnight", "dark", "shadow", "moody", "gothic", "horror")
_BRIGHT_WORDS = ("bright", "vivid", "vibrant", "neon", "glow", "sunny", "cheerful")

_STYLE_SCHEME = {
    "auto": "analogous", "photo": "monochrome_realistic", "art": "triadic",
    "paint": "analogous", "anime": "complementary", "3d": "complementary",
    "pixel": "triadic", "minimal": "monochrome",
    # explore-page categories reuse the same engine
    "photography": "monochrome_realistic", "digital_art": "triadic",
    "traditional_art": "analogous", "illustration": "complementary",
    "cinematic": "complementary", "sci_fi": "complementary",
    "architecture": "monochrome", "watercolor": "analogous", "fantasy": "complementary",
}

_STYLE_ALGORITHM = {
    "auto": "flow_field", "photo": "radial_mesh", "art": "organic_blobs",
    "paint": "flow_field", "anime": "particle_burst", "3d": "shaded_blobs",
    "pixel": "geometric_mosaic", "minimal": "geometric_mosaic",
    "photography": "radial_mesh", "digital_art": "organic_blobs",
    "traditional_art": "flow_field", "illustration": "particle_burst",
    "cinematic": "radial_mesh", "sci_fi": "shaded_blobs",
    "architecture": "geometric_mosaic", "watercolor": "flow_field", "fantasy": "shaded_blobs",
}


def _hsv_to_rgb_np(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Vectorized HSV -> RGB. h, s, v are float arrays in [0, 1] of equal shape."""
    h6 = (h % 1.0) * 6.0
    i = np.floor(h6).astype(np.int32) % 6
    f = h6 - np.floor(h6)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)

    conditions = [i == k for k in range(6)]
    r = np.select(conditions, [v, q, p, p, t, v])
    g = np.select(conditions, [t, v, v, q, p, p])
    b = np.select(conditions, [p, p, t, v, v, q])
    return np.stack([r, g, b], axis=-1)


class Palette:
    """A generated colour palette + mood flags derived from the prompt."""

    __slots__ = ("base_hue", "hues", "scheme", "desaturate", "dark", "bright")

    def __init__(self, base_hue: float, hues: Sequence[float], scheme: str,
                 desaturate: bool, dark: bool, bright: bool):
        self.base_hue = base_hue
        self.hues = list(hues)
        self.scheme = scheme
        self.desaturate = desaturate
        self.dark = dark
        self.bright = bright

    def hue(self, index: int = 0) -> float:
        return self.hues[index % len(self.hues)]


def _generate_palette(prompt: str, style: str, rng: np.random.Generator) -> Palette:
    lower = (prompt or "").lower()
    matched = [deg for kw, deg in _KEYWORD_HUES.items() if kw in lower]
    if matched:
        # Circular mean so e.g. "red" (355) + "orange" (28) averages sanely.
        radians = np.radians(matched)
        base_hue = (math.degrees(math.atan2(np.mean(np.sin(radians)), np.mean(np.cos(radians)))) % 360) / 360.0
    else:
        base_hue = float(rng.random())

    scheme = _STYLE_SCHEME.get(style, "analogous")
    if scheme == "complementary":
        hues = [base_hue, (base_hue + 0.5) % 1.0]
    elif scheme == "triadic":
        hues = [base_hue, (base_hue + 1 / 3) % 1.0, (base_hue + 2 / 3) % 1.0]
    elif scheme in ("analogous",):
        hues = [(base_hue - 0.07) % 1.0, base_hue, (base_hue + 0.07) % 1.0, (base_hue + 0.14) % 1.0]
    else:  # monochrome / monochrome_realistic
        hues = [base_hue, (base_hue + 0.02) % 1.0, (base_hue - 0.02) % 1.0]

    desaturate = any(w in lower for w in _DESATURATE_WORDS)
    dark = any(w in lower for w in _DARK_WORDS)
    bright = any(w in lower for w in _BRIGHT_WORDS)
    return Palette(base_hue, hues, scheme, desaturate, dark, bright)


# ============================================================
# NOISE PRIMITIVES
# ============================================================

def _value_noise(h: int, w: int, rng: np.random.Generator, freq: float) -> np.ndarray:
    """One octave of value noise: a coarse random grid, smoothly upsampled."""
    small_h = max(2, int(round(freq)) + 1)
    small_w = max(2, int(round(freq)) + 1)
    grid = rng.random((small_h, small_w)).astype(np.float32)
    img = Image.fromarray(grid, mode="F").resize((w, h), Image.BICUBIC)
    return np.asarray(img, dtype=np.float32)


def _fractal_noise(h: int, w: int, rng: np.random.Generator, octaves: int = 4,
                    persistence: float = 0.55, base_freq: float = 4.0) -> np.ndarray:
    """Multi-octave fractal (fBm) noise, normalized to [0, 1]."""
    total = np.zeros((h, w), dtype=np.float32)
    amp, amp_sum, freq = 1.0, 0.0, base_freq
    for _ in range(octaves):
        total += _value_noise(h, w, rng, freq) * amp
        amp_sum += amp
        amp *= persistence
        freq *= 2.0
    total /= max(amp_sum, 1e-6)
    lo, hi = float(total.min()), float(total.max())
    if hi - lo < 1e-6:
        return np.zeros((h, w), dtype=np.float32)
    return (total - lo) / (hi - lo)


def _domain_warp(field: np.ndarray, warp_x: np.ndarray, warp_y: np.ndarray, strength: float) -> np.ndarray:
    """Displace `field` by a noise-driven offset field for an organic, flowing look."""
    if not _HAS_SCIPY:
        return field
    h, w = field.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xx2 = np.clip(xx + (warp_x - 0.5) * strength, 0, w - 1)
    yy2 = np.clip(yy + (warp_y - 0.5) * strength, 0, h - 1)
    warped = map_coordinates(field, [yy2.ravel(), xx2.ravel()], order=1, mode="reflect")
    return warped.reshape(h, w)


# ============================================================
# ALGORITHM 1 — FLOW FIELD (domain-warped fractal noise)
# ============================================================

def _algo_flow_field(h: int, w: int, rng: np.random.Generator, palette: Palette) -> Image.Image:
    base = _fractal_noise(h, w, rng, octaves=5, base_freq=3.2, persistence=0.58)
    warp_x = _fractal_noise(h, w, rng, octaves=2, base_freq=2.0)
    warp_y = _fractal_noise(h, w, rng, octaves=2, base_freq=2.0)
    warped = _domain_warp(base, warp_x, warp_y, strength=min(h, w) * 0.12)
    detail = _fractal_noise(h, w, rng, octaves=3, base_freq=9.0, persistence=0.5)
    field = np.clip(warped * 0.75 + detail * 0.25, 0, 1)

    n_bands = len(palette.hues)
    band = np.clip((field * n_bands).astype(np.int32), 0, n_bands - 1)
    hue = np.take(np.array(palette.hues, dtype=np.float32), band)
    hue += (detail - 0.5) * 0.04

    sat = 0.15 if palette.desaturate else (0.75 if palette.bright else 0.55)
    sat_arr = np.clip(sat + (field - 0.5) * 0.25, 0.05, 1.0)
    val_base = 0.28 if palette.dark else 0.42
    val_arr = np.clip(val_base + field * (0.85 if palette.dark else 0.62), 0.03, 1.0)

    rgb = _hsv_to_rgb_np(hue % 1.0, sat_arr, val_arr)
    return Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")


# ============================================================
# ALGORITHM 2 — GEOMETRIC MOSAIC (true Voronoi via cKDTree)
# ============================================================

def _algo_geometric_mosaic(h: int, w: int, rng: np.random.Generator, palette: Palette) -> Image.Image:
    if not _HAS_SCIPY:
        return _algo_flow_field(h, w, rng, palette)

    # Work at reduced resolution for speed, upsample the label map with NEAREST
    # (keeps crisp mosaic edges) then anti-alias only the grout lines.
    scale = 3
    sh, sw = max(8, h // scale), max(8, w // scale)

    cols, rows = max(4, sw // 26), max(4, sh // 26)
    gx, gy = np.meshgrid(np.linspace(0, sw, cols, endpoint=False), np.linspace(0, sh, rows, endpoint=False))
    jitter = (rng.random((rows, cols, 2)) - 0.5) * (sw / cols)
    seeds = np.stack([gx + jitter[..., 0], gy + jitter[..., 1]], axis=-1).reshape(-1, 2)

    tree = cKDTree(seeds)
    yy, xx = np.mgrid[0:sh, 0:sw]
    query_pts = np.stack([xx.ravel(), yy.ravel()], axis=-1)
    dist, idx = tree.query(query_pts, k=2)
    dist = dist.reshape(sh, sw, 2)
    idx = idx.reshape(sh, sw, 2)

    n_cells = len(seeds)
    cell_hue_jitter = rng.random(n_cells).astype(np.float32)
    cell_val_jitter = rng.random(n_cells).astype(np.float32)

    n_hues = len(palette.hues)
    cell_band = (cell_hue_jitter * n_hues).astype(np.int32) % n_hues
    hue_lut = np.array(palette.hues, dtype=np.float32)[cell_band]
    hue = hue_lut[idx[..., 0]]

    # Grout line: darken pixels near the boundary between two cells.
    edge = np.clip(1.0 - (dist[..., 1] - dist[..., 0]) / (sw / cols * 0.28), 0, 1)

    sat = 0.12 if palette.desaturate else (0.7 if palette.bright else 0.5)
    sat_arr = np.full((sh, sw), sat, dtype=np.float32)
    val_base = 0.3 if palette.dark else 0.55
    val_arr = np.clip(val_base + cell_val_jitter[idx[..., 0]] * 0.4 - edge * 0.35, 0.04, 1.0)

    rgb = _hsv_to_rgb_np(hue % 1.0, sat_arr, val_arr)
    small = Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")
    return small.resize((w, h), Image.BICUBIC)


# ============================================================
# ALGORITHM 3 — RADIAL GRADIENT MESH
# ============================================================

def _algo_radial_mesh(h: int, w: int, rng: np.random.Generator, palette: Palette,
                       n_blobs: int = 6) -> Image.Image:
    val_floor = 0.10 if palette.dark else 0.22
    canvas = np.full((h, w, 3), val_floor, dtype=np.float32)
    weight_total = np.full((h, w), 1e-3, dtype=np.float32)
    accum = canvas * weight_total[..., None]

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for i in range(n_blobs):
        cx, cy = rng.random() * w, rng.random() * h
        radius = (0.25 + rng.random() * 0.45) * max(h, w)
        # Blending happens continuously across overlapping blobs here, so
        # widely-separated hues (complementary/triadic) would cancel toward
        # muddy gray in the overlap zones — stay close to the base hue and
        # let saturation/value carry the variation instead.
        hue = (palette.base_hue + (rng.random() - 0.5) * 0.09) % 1.0
        sat = 0.1 if palette.desaturate else (0.78 if palette.bright else 0.62)
        val = 0.35 + rng.random() * (0.5 if palette.dark else 0.6)
        rgb = _hsv_to_rgb_np(np.array([hue]), np.array([sat]), np.array([val]))[0]

        d2 = (xx - cx) ** 2 + (yy - cy) ** 2
        w_map = np.exp(-d2 / (2 * radius ** 2))
        accum += w_map[..., None] * rgb[None, None, :]
        weight_total += w_map

    rgb_final = accum / weight_total[..., None]
    rgb_final = np.clip(rgb_final, 0, 1)
    return Image.fromarray((rgb_final * 255).astype(np.uint8), mode="RGB")


# ============================================================
# ALGORITHM 4 — PARTICLE BURST
# ============================================================

def _algo_particle_burst(h: int, w: int, rng: np.random.Generator, palette: Palette,
                          n_particles: int = 220) -> Image.Image:
    base = _algo_radial_mesh(h, w, rng, palette, n_blobs=3)
    base = base.filter(ImageFilter.GaussianBlur(radius=max(2, min(h, w) // 40)))
    canvas = base.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")

    cx, cy = w / 2 + (rng.random() - 0.5) * w * 0.3, h / 2 + (rng.random() - 0.5) * h * 0.3
    for _ in range(n_particles):
        angle = rng.random() * 2 * math.pi
        dist = (rng.random() ** 1.6) * max(h, w) * 0.62
        px = cx + math.cos(angle) * dist
        py = cy + math.sin(angle) * dist
        size = max(1.5, (1.0 - dist / (max(h, w) * 0.7)) * (rng.random() * 14 + 3))
        hue = palette.hue(int(rng.integers(0, len(palette.hues))))
        sat = 0.15 if palette.desaturate else 0.65 + rng.random() * 0.3
        val = 0.6 + rng.random() * 0.4
        rgb = _hsv_to_rgb_np(np.array([hue]), np.array([sat]), np.array([val]))[0]
        color = tuple(int(c * 255) for c in rgb) + (int(90 + rng.random() * 140),)

        if rng.random() < 0.25:
            # Occasional streak for a sense of motion/energy.
            ex = px + math.cos(angle) * size * 3
            ey = py + math.sin(angle) * size * 3
            draw.line([(px, py), (ex, ey)], fill=color, width=max(1, int(size * 0.4)))
        else:
            draw.ellipse([px - size, py - size, px + size, py + size], fill=color)

    return canvas.convert("RGB")


# ============================================================
# ALGORITHM 5 — ORGANIC BLOBS (metaballs)
# ============================================================

def _metaball_field(h: int, w: int, rng: np.random.Generator, n_blobs: int = 7) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    field = np.zeros((h, w), dtype=np.float32)
    for _ in range(n_blobs):
        cx, cy = rng.random() * w, rng.random() * h
        radius = (0.12 + rng.random() * 0.22) * max(h, w)
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / radius
        field += np.clip(1.0 - d, 0, None) ** 2
    lo, hi = float(field.min()), float(field.max())
    return (field - lo) / max(hi - lo, 1e-6)


def _algo_organic_blobs(h: int, w: int, rng: np.random.Generator, palette: Palette) -> Image.Image:
    field = _metaball_field(h, w, rng, n_blobs=8)
    texture = _fractal_noise(h, w, rng, octaves=3, base_freq=6.0) * 0.15
    field = np.clip(field + texture, 0, 1)

    n_hues = len(palette.hues)
    # Smooth continuous blend rather than discrete height bands — banding
    # across a wide (triadic/complementary) hue spread produced a flat
    # concentric "target" look instead of an organic gradient.
    hue_a = palette.hue(0)
    hue_b = palette.hue(1 % n_hues) if n_hues > 1 else (hue_a + 0.06) % 1.0
    delta = ((hue_b - hue_a + 0.5) % 1.0) - 0.5  # shortest signed hue distance
    hue = (hue_a + delta * field) % 1.0
    sat = 0.12 if palette.desaturate else (0.72 if palette.bright else 0.58)
    sat_arr = np.full((h, w), sat, dtype=np.float32)
    val_base = 0.16 if palette.dark else 0.24
    val_arr = np.clip(val_base + field * (0.9 if not palette.dark else 0.7), 0.03, 1.0)

    rgb = _hsv_to_rgb_np(hue % 1.0, sat_arr, val_arr)
    return Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")


# ============================================================
# ALGORITHM 6 — SHADED BLOBS (mini Lambert + specular lighting)
# ============================================================

def _algo_shaded_blobs(h: int, w: int, rng: np.random.Generator, palette: Palette) -> Image.Image:
    """Treat a metaball field as a height map and light it — gives the "3d"
    style a real sense of depth via actual surface-normal / lighting math
    rather than a flat texture."""
    height = _metaball_field(h, w, rng, n_blobs=5)
    if _HAS_SCIPY:
        height = gaussian_filter(height, sigma=max(1.0, min(h, w) / 180))

    # Surface normal from the height-field gradient (dz/dx, dz/dy, 1), normalized.
    gy, gx = np.gradient(height.astype(np.float32))
    strength = 6.0
    nx, ny, nz = -gx * strength, -gy * strength, np.ones_like(height)
    norm = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2) + 1e-6
    nx, ny, nz = nx / norm, ny / norm, nz / norm

    light = np.array([-0.55, -0.55, 0.62])
    light = light / np.linalg.norm(light)
    diffuse = np.clip(nx * light[0] + ny * light[1] + nz * light[2], 0, 1)

    view = np.array([0.0, 0.0, 1.0])
    halfway = light + view
    halfway = halfway / np.linalg.norm(halfway)
    spec = np.clip(nx * halfway[0] + ny * halfway[1] + nz * halfway[2], 0, 1) ** 28

    ambient = 0.16 if palette.dark else 0.26
    shade = np.clip(ambient + diffuse * 0.72 + spec * 0.55, 0, 1)

    # A single coherent hue (richness comes from the lighting itself, not
    # from banding across the palette) reads as one lit glossy material —
    # multi-hue banding here previously produced a flat, muddy two-tone
    # blob instead of a convincing lit surface.
    hue = np.full(height.shape, palette.hue(0), dtype=np.float32)
    hue += (height - 0.5) * 0.05  # a whisper of gradient across the form
    sat = 0.08 if palette.desaturate else 0.55
    sat_arr = np.clip(sat * (0.35 + 0.65 * shade), 0.04, 1.0)

    rgb = _hsv_to_rgb_np(hue % 1.0, sat_arr, shade)
    img = Image.fromarray((rgb * 255).astype(np.uint8), mode="RGB")

    # Soft ambient-occlusion-like vignette to ground the "object" in space.
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h / 2
    d = np.sqrt(((xx - cx) / (w / 2)) ** 2 + ((yy - cy) / (h / 2)) ** 2)
    vignette = np.clip(1.0 - (d - 0.6) * 0.9, 0.35, 1.0)
    arr = np.asarray(img, dtype=np.float32) * vignette[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGB")


_ALGORITHMS = {
    "flow_field": _algo_flow_field,
    "geometric_mosaic": _algo_geometric_mosaic,
    "radial_mesh": _algo_radial_mesh,
    "particle_burst": _algo_particle_burst,
    "organic_blobs": _algo_organic_blobs,
    "shaded_blobs": _algo_shaded_blobs,
}


# ============================================================
# POST-PROCESSING
# ============================================================

def _apply_grain(img: Image.Image, rng: np.random.Generator, amount: float = 6.0) -> Image.Image:
    arr = np.asarray(img, dtype=np.float32)
    noise = rng.normal(0, amount, size=arr.shape[:2])[..., None]
    arr = np.clip(arr + noise, 0, 255)
    return Image.fromarray(arr.astype(np.uint8), mode="RGB")


def _apply_vignette(img: Image.Image, strength: float = 0.35) -> Image.Image:
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h / 2
    d = np.sqrt(((xx - cx) / (w / 2)) ** 2 + ((yy - cy) / (h / 2)) ** 2)
    mask = np.clip(1.0 - strength * np.clip(d - 0.35, 0, None), 0.25, 1.0)
    arr = np.asarray(img, dtype=np.float32) * mask[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), mode="RGB")


def _pixelate(img: Image.Image, block: int = 12) -> Image.Image:
    w, h = img.size
    small = img.resize((max(1, w // block), max(1, h // block)), Image.BILINEAR)
    return small.resize((w, h), Image.NEAREST)


def _post_process(img: Image.Image, style: str, rng: np.random.Generator) -> Image.Image:
    if style in ("paint", "traditional_art", "watercolor", "art"):
        img = img.filter(ImageFilter.GaussianBlur(radius=1.1))
        img = ImageEnhance.Color(img).enhance(1.08)
    if style in ("photo", "photography", "cinematic", "3d", "sci_fi"):
        img = _apply_vignette(img, strength=0.3)
        img = ImageEnhance.Contrast(img).enhance(1.06)
    if style == "pixel":
        img = _pixelate(img, block=max(6, min(img.size) // 48))
    if style in ("minimal", "architecture"):
        img = ImageEnhance.Color(img).enhance(0.9)
        img = ImageEnhance.Contrast(img).enhance(1.1)
    img = _apply_grain(img, rng, amount=3.5)
    img = img.filter(ImageFilter.SMOOTH_MORE) if style in ("minimal",) else img
    return img


# ============================================================
# PUBLIC API
# ============================================================

def generate_art(prompt: str, width: int = 512, height: int = 512, style: str = "auto",
                  seed: Optional[int] = None, negative_prompt: Optional[str] = None) -> bytes:
    """Generate a unique procedural artwork and return PNG bytes.

    Deterministic: the same (prompt, width, height, style, seed) always
    reproduces the same image, so results are reproducible and cache-friendly.
    """
    style_key = style if style in _STYLE_ALGORITHM else "auto"
    rng = _make_rng(prompt or "", style_key, seed)
    palette = _generate_palette(prompt or "", style_key, rng)

    # Render at a capped internal resolution for speed, then upscale to the
    # requested output size with a high-quality resample.
    render_w = min(max(width, 64), 640)
    render_h = min(max(height, 64), 640)

    algo_name = _STYLE_ALGORITHM.get(style_key, "flow_field")
    algo = _ALGORITHMS[algo_name]
    img = algo(render_h, render_w, rng, palette)

    if (render_w, render_h) != (width, height):
        img = img.resize((max(1, width), max(1, height)), Image.LANCZOS)

    img = _post_process(img, style_key, rng)

    import io as _io
    buf = _io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generate_thumbnail(seed_text: str, width: int = 400, height: int = 300, style: str = "auto") -> bytes:
    """Convenience wrapper for generating deterministic preview art (e.g. for
    style-category cards) from a short label rather than a full prompt."""
    return generate_art(prompt=seed_text, width=width, height=height, style=style, seed=None)


def available_algorithms() -> list:
    return sorted(_ALGORITHMS.keys())
