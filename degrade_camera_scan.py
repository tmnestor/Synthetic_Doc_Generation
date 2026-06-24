"""Camera-scan degradation: a phone photo of a receipt lying on a flat surface.

Models the REAL production case (operator-described): a clean, upright receipt is
placed on a flat background and photographed off-axis. The result is a receipt
that occupies a *sub-region* of the frame, surrounded by background, and is
**perspective-distorted (trapezoid) and rotated** — not merely a frame-filling
page with a small tilt. This is the input the document-rectification preprocessor
(detect quad -> 4-point perspective transform) must later undo.

The warp uses the SAME homography library the rectifier will use
(``cv2.getPerspectiveTransform`` / ``cv2.warpPerspective``), so degrade and
rectify are exact numerical inverses — clean round-trip validation. Compositing
and photometrics stay in PIL/NumPy. Everything is kept in RGB order (PIL does
I/O; NumPy arrays are fed straight to cv2), so there is no BGR channel swap.

Deterministic per case (seed), so reruns are reproducible.

Usage:
    python degrade_camera_scan.py <clean.png> <out.png> <seed>
"""

import io
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


def _rot(pt, cx, cy, deg):
    t = np.radians(deg)
    x, y = pt[0] - cx, pt[1] - cy
    return [cx + x * np.cos(t) - y * np.sin(t), cy + x * np.sin(t) + y * np.cos(t)]


def degrade(clean_path: Path, out_path: Path, seed: int) -> None:
    rng = np.random.default_rng(seed)
    receipt = Image.open(clean_path).convert("RGB")
    w, h = receipt.size

    # --- canvas (the "photo"): a cooperative user frames the receipt to fill
    #     most of the shot, so it occupies ~75-88% of the frame (modest margin) ---
    pad_x = int(w * rng.uniform(0.07, 0.16))
    pad_y = int(h * rng.uniform(0.07, 0.16))
    cw, ch = w + 2 * pad_x, h + 2 * pad_y

    # --- flat background: muted desk tone, gentle lighting gradient, faint noise ---
    base = np.array([rng.uniform(150, 200), rng.uniform(140, 190), rng.uniform(125, 175)])
    bg = np.ones((ch, cw, 3)) * base
    gx = np.linspace(rng.uniform(-25, 0), rng.uniform(0, 25), cw)[None, :, None]
    gy = np.linspace(rng.uniform(-20, 0), rng.uniform(0, 20), ch)[:, None, None]
    bg = np.clip(bg + gx + gy + rng.normal(0, 3, (ch, cw, 3)), 0, 255)

    # --- destination quad: mild perspective + small rotation (best-effort capture) ---
    f = rng.uniform(0.02, 0.08)  # foreshorten fraction (slight off-parallel tilt)
    edge = int(rng.integers(0, 4))
    q = [[0, 0], [w, 0], [w, h], [0, h]]  # TL, TR, BR, BL
    if edge == 0:  # top edge away
        q[0][0] += w * f
        q[1][0] -= w * f
    elif edge == 1:  # right edge away
        q[1][1] += h * f
        q[2][1] -= h * f
    elif edge == 2:  # bottom edge away
        q[3][0] += w * f
        q[2][0] -= w * f
    else:  # left edge away
        q[0][1] += h * f
        q[3][1] -= h * f
    deg = rng.uniform(-8, 8)  # small misalignment, not worst-case
    q = [_rot(p, w / 2, h / 2, deg) for p in q]
    ox = pad_x + rng.uniform(-pad_x * 0.3, pad_x * 0.3)
    oy = pad_y + rng.uniform(-pad_y * 0.3, pad_y * 0.3)
    dst = np.array([[x + ox, y + oy] for x, y in q], dtype=np.float32)
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)

    # --- cv2 perspective warp of the receipt (RGBA) onto the canvas ---
    m = cv2.getPerspectiveTransform(src, dst)
    rgba = np.dstack([np.array(receipt), np.full((h, w), 255, np.uint8)])
    warped = cv2.warpPerspective(
        rgba,
        m,
        (cw, ch),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    a = (warped[:, :, 3].astype(np.float32) / 255.0)[:, :, None]

    # --- drop shadow under the receipt ---
    sh = cv2.GaussianBlur(warped[:, :, 3], (0, 0), max(w, h) * 0.02) * 0.45
    off = int(max(w, h) * 0.015)
    sh = np.roll(np.roll(sh, off, axis=0), off, axis=1)[:, :, None] / 255.0
    bg = bg * (1 - sh) + np.array([25, 22, 20]) * sh

    # --- composite receipt over (shadowed) background ---
    comp = bg * (1 - a) + warped[:, :, :3].astype(np.float32) * a
    canvas = Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8), "RGB")

    # --- camera photometrics: lighting, blur, sensor noise, JPEG ---
    canvas = ImageEnhance.Brightness(canvas).enhance(rng.uniform(0.92, 1.05))
    canvas = ImageEnhance.Contrast(canvas).enhance(rng.uniform(0.90, 1.0))
    canvas = canvas.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 0.9)))
    arr = np.array(canvas).astype(np.int16) + rng.normal(0, rng.uniform(2, 5), (ch, cw, 3)).astype(np.int16)
    canvas = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=int(rng.integers(72, 90)))
    buf.seek(0)
    Image.open(buf).convert("RGB").save(out_path, format="PNG")


def _case_seed(name: str) -> int:
    """Deterministic seed from the CASE number in the filename (CASE001 -> 1)."""
    digits = "".join(c for c in name.split("_")[0] if c.isdigit())
    return int(digits) if digits else 0


def batch(clean_dir: Path, degraded_dir: Path) -> int:
    """Degrade every clean receipt into degraded_dir as <name>_degraded.png."""
    n = 0
    for clean in sorted(clean_dir.glob("*.png")):
        out = degraded_dir / f"{clean.stem}_degraded.png"
        degrade(clean, out, _case_seed(clean.stem))
        n += 1
    return n


if __name__ == "__main__":
    if sys.argv[1] == "--batch":  # usage: --batch <output_root>
        root = Path(sys.argv[2])
        count = batch(root / "clean" / "receipts", root / "degraded" / "receipts")
        print(f"degraded {count} receipts -> {root / 'degraded' / 'receipts'}")
    else:
        clean, out, seed = sys.argv[1], sys.argv[2], int(sys.argv[3])
        degrade(Path(clean), Path(out), seed)
        print(f"wrote {out}")
