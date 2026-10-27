"""Validate dxt.py against an independent decoder (Blender's DDS reader) and measure quality.

1. Synthetic images (gradient, flower pattern, alpha cut-out) -> encode -> wrap the blocks in a .dds
   -> Blender decodes it -> must match dxt.decode (independent decoder agreement)
2. Real DXT blocks from tests/fixtures/vtf_real (Valve tools) -> same agreement check
3. Quality: PSNR of encode/decode against the source, per image type
4. Negative control: garbage blocks must score a low PSNR
Also writes the synthetic images as PNG (for texture.py tests) in the output folder.

Usage: blender -b --python check_dxt.py -- output_folder [vtf_real_folder]
Prints CHECK lines and RESULT OK|FAIL.
"""
import glob
import os
import struct
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import dxt  # noqa: E402
from vtf import read_vtf  # noqa: E402

out = sys.argv[sys.argv.index("--") + 1]
real = sys.argv[sys.argv.index("--") + 2] if len(sys.argv) > sys.argv.index("--") + 2 else None
os.makedirs(out, exist_ok=True)
ok = True


def check(name, cond, detail):
    global ok
    ok &= bool(cond)
    print(f"CHECK {'OK  ' if cond else 'FAIL'} {name}: {detail}")


def images():
    n = 256
    y, x = np.mgrid[0:n, 0:n].astype(np.float32)
    grad = np.stack([x, y, (x + y) / 2, np.full_like(x, 255)], -1)
    rng = np.random.default_rng(1)
    flowers = np.zeros((n, n, 4), np.float32)
    flowers[...] = (200, 60, 120, 255)
    flowers[..., :3] *= (0.6 + 0.4 * y / n)[..., None]
    for cx, cy, r in rng.uniform([0, 0, 6], [n, n, 22], (40, 3)):
        for k in range(5):
            ang = k * 2 * np.pi / 5
            px, py = cx + np.cos(ang) * r * 0.6, cy + np.sin(ang) * r * 0.6
            m = (x - px) ** 2 + (y - py) ** 2 < (r * 0.45) ** 2
            flowers[m, :3] = (250, 200, 225)
        flowers[(x - cx) ** 2 + (y - cy) ** 2 < (r * 0.18) ** 2, :3] = (230, 180, 60)
    cut = flowers.copy()
    cut[..., 3] = np.where(((x - n / 2) ** 2 + (y - n / 2) ** 2) < (n * 0.38) ** 2, 255, 0)
    return {"gradient": grad, "flowers": flowers, "cutout": cut}


def save_png(name, img):
    h, w = img.shape[:2]
    im = bpy.data.images.new(name, w, h, alpha=True)
    im.colorspace_settings.name = "Non-Color"
    im.pixels.foreach_set((img[::-1].astype(np.float32) / 255).ravel())
    im.filepath_raw = os.path.join(out, name + ".png")
    im.file_format = "PNG"
    im.save()


def dds(path, data, w, h, fmt):
    head = bytearray(128)
    head[0:4] = b"DDS "
    struct.pack_into("<IIIIIII", head, 4, 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000, h, w, len(data), 0, 0)
    struct.pack_into("<II4s", head, 76, 32, 0x4, fmt.encode())
    struct.pack_into("<I", head, 108, 0x1000)
    open(path, "wb").write(bytes(head) + data)


def blender_decode(path, w, h):
    im = bpy.data.images.load(path)
    im.colorspace_settings.name = "Non-Color"
    buf = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(buf)
    return np.clip(np.round(buf.reshape(h, w, 4)[::-1] * 255), 0, 255).astype(np.uint8)


def agree(name, data, w, h, fmt):
    path = os.path.join(out, name + ".dds")
    dds(path, data, w, h, fmt)
    theirs = blender_decode(path, w, h)
    mine = dxt.decode(data, w, h, fmt)
    diff = np.abs(theirs.astype(int) - mine.astype(int))
    ch = 4 if fmt == "DXT5" else 3
    check(f"decoder agreement {name}", diff[..., :ch].max() <= 3,
          f"max channel difference vs Blender DDS reader {diff[..., :ch].max()} (rounding of 1/3 steps: <= 3)")


odd = np.zeros((200, 300, 4), np.float32)
odd[...] = (90, 140, 200, 255)
save_png("odd_300x200", odd)

thresholds = {"gradient": 38, "flowers": 30, "cutout": 30}
for name, img in images().items():
    img = np.clip(np.round(img), 0, 255).astype(np.uint8)
    save_png(name, img)
    for fmt in ("DXT1", "DXT5"):
        if name == "cutout" and fmt == "DXT1":
            continue
        data = dxt.encode(img, fmt)
        agree(f"{name}_{fmt}", data, 256, 256, fmt)
        back = dxt.decode(data, 256, 256, fmt)
        ch = 4 if fmt == "DXT5" else 3
        q = dxt.psnr(img[..., :ch], back[..., :ch])
        check(f"quality {name} {fmt}", q >= thresholds[name], f"PSNR {q:.1f} dB (threshold {thresholds[name]})")

garbage = np.random.default_rng(2).integers(0, 256, 256 * 256 // 2, dtype=np.uint8).tobytes()
src = np.clip(np.round(images()["gradient"]), 0, 255).astype(np.uint8)
q = dxt.psnr(src[..., :3], dxt.decode(garbage, 256, 256, "DXT1")[..., :3])
check("negative control: garbage blocks", q < 15, f"PSNR {q:.1f} dB must be < 15")

if real and os.path.isdir(real):
    done = 0
    for f in sorted(glob.glob(os.path.join(real, "*.vtf"))):
        r = read_vtf(f)
        if not r["valid"] or r["format"] not in ("DXT1", "DXT5") or r["frames"] != 1:
            continue
        w, h = r["width"], r["height"]
        size = max(1, w // 4) * max(1, h // 4) * (8 if r["format"] == "DXT1" else 16)
        raw = open(f, "rb").read()
        top = raw[len(raw) - size:]
        agree(f"real_{done}_{r['format']}_{w}x{h}", top, w, h, r["format"])
        done += 1
    check("real files tested", done > 0, f"{done} real top-level mips")

print("RESULT", "OK" if ok else "FAIL")
