"""Build .vtf test files straight from the VTF 7.2 specification (header + empty pixel data).

Usage: python make_vtf.py output.vtf width height format_id mipmaps [flags] [--truncate]
format ids: 12 = BGRA8888, 13 = DXT1, 15 = DXT5. mipmaps 0 = full chain.
"""
import struct
import sys

sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)),
                                              "..", "tools"))
from vtf import mip_chain_bytes  # noqa: E402


def build(width, height, fmt, mips, flags=0):
    if mips == 0:
        mips = max(width, height).bit_length()
    header = bytearray(80)
    header[0:4] = b"VTF\0"
    struct.pack_into("<III", header, 4, 7, 2, 80)
    struct.pack_into("<HHIHH", header, 16, width, height, flags, 1, 0)
    struct.pack_into("<fff", header, 32, 0.5, 0.5, 0.5)
    struct.pack_into("<f", header, 48, 1.0)
    struct.pack_into("<i", header, 52, fmt)
    header[56] = mips
    struct.pack_into("<i", header, 57, -1)
    header[61] = header[62] = 0
    struct.pack_into("<H", header, 63, 1)
    return bytes(header) + bytes(mip_chain_bytes(fmt, width, height, mips))


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    data = build(int(a[1]), int(a[2]), int(a[3]), int(a[4]), int(a[5]) if len(a) > 5 else 0)
    if "--truncate" in sys.argv:
        data = data[: len(data) // 2]
    open(a[0], "wb").write(data)


if __name__ == "__main__":
    main()
