"""Convert an image (PNG, TGA, JPG...) to a Garry's Mod-ready .vtf, optionally with its .vmt.

- power-of-two resize (down) and --max side limit (2048 by default)
- DXT1 when the image is opaque, DXT5 when it has alpha (or --format)
- full mip chain (linear-light averaging; --normal renormalizes normal maps and sets the NORMAL flag)
- VTF 7.2, no thumbnail; prints the PSNR of the top level after compression
- --vmt writes a VertexLitGeneric material ($alphatest for alpha cut-outs)

Usage: blender -b --python texture.py -- input.png output.vtf [--max 2048] [--format auto|DXT1|DXT5]
       [--normal] [--vmt output.vmt --material-path models/me/outfit/name]
"""
import argparse
import os
import struct
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxt  # noqa: E402

FORMAT_ID = {"DXT1": 13, "DXT5": 15}
FLAG_NORMAL, FLAG_EIGHTBITALPHA, FLAG_TRILINEAR = 0x80, 0x2000, 0x2


def args():
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--max", type=int, default=2048)
    p.add_argument("--format", default="auto", choices=["auto", "DXT1", "DXT5"])
    p.add_argument("--normal", action="store_true")
    p.add_argument("--vmt")
    p.add_argument("--material-path", help="path written as $basetexture (relative to materials/)")
    return p.parse_args(sys.argv[sys.argv.index("--") + 1:])


def load(path):
    """-> (h, w, 4) uint8, top row first."""
    img = bpy.data.images.load(path)
    img.colorspace_settings.name = "Non-Color"
    w, h = img.size
    buf = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(buf)
    return np.clip(np.round(buf.reshape(h, w, 4)[::-1] * 255), 0, 255).astype(np.uint8)


def resize(img, w, h):
    """Box-average downscale to (h, w) (exact when the ratio is an integer, nearest blend otherwise)."""
    H, W = img.shape[:2]
    if (H, W) == (h, w):
        return img
    ys = (np.arange(h + 1) * H / h).astype(int)
    xs = (np.arange(w + 1) * W / w).astype(int)
    f = img.astype(np.float32)
    cs = np.pad(f.cumsum(0).cumsum(1), ((1, 0), (1, 0), (0, 0)))
    s = cs[ys[1:]][:, xs[1:]] - cs[ys[:-1]][:, xs[1:]] - cs[ys[1:]][:, xs[:-1]] + cs[ys[:-1]][:, xs[:-1]]
    area = ((ys[1:] - ys[:-1])[:, None] * (xs[1:] - xs[:-1])[None, :])[..., None]
    return np.clip(np.round(s / area), 0, 255).astype(np.uint8)


def pot_below(n):
    return 1 << (n.bit_length() - 1)


def write_vtf(path, chain, fmt, flags):
    h, w = chain[0].shape[:2]
    header = bytearray(80)
    header[0:4] = b"VTF\0"
    struct.pack_into("<III", header, 4, 7, 2, 80)
    struct.pack_into("<HHIHH", header, 16, w, h, flags, 1, 0)
    struct.pack_into("<fff", header, 32, *(chain[-1][0, 0, :3] / 255.0))
    struct.pack_into("<f", header, 48, 1.0)
    struct.pack_into("<i", header, 52, FORMAT_ID[fmt])
    header[56] = len(chain)
    struct.pack_into("<i", header, 57, -1)
    struct.pack_into("<H", header, 63, 1)
    with open(path, "wb") as f:
        f.write(header)
        for level in reversed(chain):
            lh, lw = level.shape[:2]
            f.write(dxt.encode(dxt.pad4(level), fmt)[: max(1, (lw + 3) // 4) * max(1, (lh + 3) // 4)
                                                       * (8 if fmt == "DXT1" else 16)])


def main():
    a = args()
    img = load(a.input)
    h, w = img.shape[:2]
    tw, th = min(pot_below(w), a.max), min(pot_below(h), a.max)
    img = resize(img, tw, th)
    has_alpha = bool((img[..., 3] < 250).any())
    fmt = a.format if a.format != "auto" else ("DXT5" if has_alpha else "DXT1")
    chain = dxt.mipmaps(img, normal=a.normal)
    flags = FLAG_TRILINEAR | (FLAG_NORMAL if a.normal else 0) | (FLAG_EIGHTBITALPHA if fmt == "DXT5" else 0)
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    write_vtf(a.output, chain, fmt, flags)
    back = dxt.decode(dxt.encode(dxt.pad4(img), fmt), tw, th, fmt)
    channels = 4 if fmt == "DXT5" else 3
    q = dxt.psnr(img[..., :channels], back[..., :channels])
    print(f"TEXTURE {os.path.basename(a.input)} {w}x{h} -> {tw}x{th} {fmt} mips {len(chain)} "
          f"alpha {'yes' if has_alpha else 'no'} PSNR {q:.1f} dB size {os.path.getsize(a.output)}")
    if a.vmt:
        base = (a.material_path or os.path.splitext(os.path.basename(a.output))[0]).replace("\\", "/")
        lines = ['"VertexLitGeneric"', "{", f'\t"$basetexture" "{base}"']
        if has_alpha:
            lines += ['\t"$alphatest" "1"', '\t"$alphatestreference" "0.5"']
        lines.append("}")
        with open(a.vmt, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
        print(f"VMT {a.vmt}")


main()
