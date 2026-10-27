"""Valve Texture Format (.vtf) header reader: size, format, mipmaps, flags, VRAM and integrity.

Usage: python vtf.py file.vtf [...]
"""
import os
import struct
import sys

FORMATS = {
    0: ("RGBA8888", 4), 1: ("ABGR8888", 4), 2: ("RGB888", 3), 3: ("BGR888", 3), 4: ("RGB565", 2),
    5: ("I8", 1), 6: ("IA88", 2), 7: ("P8", 1), 8: ("A8", 1), 9: ("RGB888_BLUESCREEN", 3),
    10: ("BGR888_BLUESCREEN", 3), 11: ("ARGB8888", 4), 12: ("BGRA8888", 4), 13: ("DXT1", 0.5),
    14: ("DXT3", 1), 15: ("DXT5", 1), 16: ("BGRX8888", 4), 17: ("BGR565", 2), 18: ("BGRX5551", 2),
    19: ("BGRA4444", 2), 20: ("DXT1_ONEBITALPHA", 0.5), 21: ("BGRA5551", 2), 22: ("UV88", 2),
    23: ("UVWQ8888", 4), 24: ("RGBA16161616F", 8), 25: ("RGBA16161616", 8), 26: ("UVLX8888", 4),
}
COMPRESSED = {"DXT1", "DXT3", "DXT5", "DXT1_ONEBITALPHA"}
FLAGS = {0x1: "POINTSAMPLE", 0x2: "TRILINEAR", 0x4: "CLAMPS", 0x8: "CLAMPT", 0x10: "ANISOTROPIC",
         0x20: "HINT_DXT5", 0x80: "NORMAL", 0x100: "NOMIP", 0x200: "NOLOD", 0x400: "ALL_MIPS",
         0x800: "PROCEDURAL", 0x1000: "ONEBITALPHA", 0x2000: "EIGHTBITALPHA", 0x4000: "ENVMAP",
         0x8000: "RENDERTARGET", 0x10000: "DEPTHRENDERTARGET", 0x20000: "NODEBUGOVERRIDE",
         0x40000: "SINGLECOPY", 0x800000: "NODEPTHBUFFER", 0x2000000: "CLAMPU", 0x4000000: "VERTEXTEXTURE",
         0x8000000: "SSBUMP", 0x20000000: "BORDER"}


def image_bytes(fmt, w, h):
    name, bpp = FORMATS.get(fmt, ("?", 4))
    if name in COMPRESSED:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * (8 if bpp == 0.5 else 16)
    return int(w * h * bpp)


def mip_chain_bytes(fmt, w, h, mips, frames=1, faces=1, depth=1):
    total = 0
    for m in range(mips):
        total += image_bytes(fmt, max(1, w >> m), max(1, h >> m)) * max(1, depth >> m)
    return total * frames * faces


def read_vtf(path):
    d = open(path, "rb").read()
    r = {"file": path, "size": len(d), "valid": False}
    if len(d) < 64 or d[:4] != b"VTF\0":
        r["error"] = "not a VTF file (bad signature or too short)"
        return r
    major, minor, header_size = struct.unpack_from("<III", d, 4)
    w, h, flags, frames, first = struct.unpack_from("<HHIHH", d, 16)
    fmt = struct.unpack_from("<i", d, 52)[0]
    mips = d[56]
    low_fmt = struct.unpack_from("<i", d, 57)[0]
    low_w, low_h = d[61], d[62]
    depth = struct.unpack_from("<H", d, 63)[0] if (major, minor) >= (7, 2) else 1
    faces = 6 if flags & 0x4000 else 1
    r.update(version=f"{major}.{minor}", header_size=header_size, width=w, height=h,
             flags=[n for b, n in FLAGS.items() if flags & b], frames=frames, mipmaps=mips,
             format=FORMATS.get(fmt, (f"unknown({fmt})", 0))[0], depth=depth or 1)
    r["vram"] = mip_chain_bytes(fmt, w, h, mips, frames, faces, depth or 1)
    low = image_bytes(low_fmt, low_w, low_h) if low_fmt >= 0 and low_w and low_h else 0
    expected = header_size + low + r["vram"]
    r["expected_size"] = expected
    if (major, minor) <= (7, 2) and len(d) < expected:
        r["error"] = f"truncated: {len(d)} bytes, header promises {expected}"
        return r
    r["valid"] = True
    r["power_of_two"] = w & (w - 1) == 0 and h & (h - 1) == 0
    r["full_mip_chain"] = mips >= max(w, h).bit_length()
    return r


def main():
    for path in sys.argv[1:]:
        r = read_vtf(path)
        if not r["valid"]:
            print(f"{os.path.basename(path)}: INVALID {r['error']}")
            continue
        print(f"{os.path.basename(path)}: {r['width']}x{r['height']} {r['format']} mips {r['mipmaps']} "
              f"frames {r['frames']} VRAM {r['vram'] / 1024:,.0f} KB file {r['size'] / 1024:,.0f} KB "
              f"flags {r['flags']}")


if __name__ == "__main__":
    main()
