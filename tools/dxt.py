"""DXT1 / DXT5 (BC1 / BC3) block compression and decompression with numpy, plus mipmaps.

Images are uint8 arrays (height, width, 4) RGBA, top row first, sides multiple of 4.
Color endpoints come from the principal axis of each 4x4 block (PCA), inset slightly, then every
pixel picks the nearest of the 4 palette colors. Alpha (DXT5) uses the 8-value interpolated mode.
"""
import numpy as np


def _blocks(img):
    h, w = img.shape[:2]
    return img.reshape(h // 4, 4, w // 4, 4, -1).transpose(0, 2, 1, 3, 4).reshape(-1, 16, img.shape[2])


def _to565(c):
    c = np.clip(np.round(c), 0, 255).astype(np.uint32)
    return ((c[..., 0] >> 3) << 11) | ((c[..., 1] >> 2) << 5) | (c[..., 2] >> 3)


def _from565(v):
    v = v.astype(np.uint32)
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1).astype(np.float32)


def _color_blocks(px):
    """px: (n, 16, 3) float -> (n, 8) uint8 DXT color blocks, always in 4-color mode."""
    n = px.shape[0]
    mean = px.mean(1, keepdims=True)
    d = px - mean
    cov = np.einsum("nki,nkj->nij", d, d)
    axis = np.ones((n, 3), np.float32)
    for _ in range(8):
        axis = np.einsum("nij,nj->ni", cov, axis)
        axis /= np.linalg.norm(axis, axis=1, keepdims=True) + 1e-12
    proj = np.einsum("nki,ni->nk", d, axis)
    lo, hi = proj.min(1), proj.max(1)
    inset = (hi - lo) / 16
    c0 = mean[:, 0] + axis * (hi - inset)[:, None]
    c1 = mean[:, 0] + axis * (lo + inset)[:, None]
    e0, e1 = _to565(c0), _to565(c1)
    swap = e0 < e1
    e0, e1 = np.where(swap, e1, e0), np.where(swap, e0, e1)
    p0, p1 = _from565(e0), _from565(e1)
    pal = np.stack([p0, p1, (2 * p0 + p1) / 3, (p0 + 2 * p1) / 3], 1)
    dist = ((px[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)
    idx = dist.argmin(-1).astype(np.uint32)
    idx[e0 == e1] = 0
    bits = (idx << (2 * np.arange(16, dtype=np.uint32))).sum(1, dtype=np.uint64).astype(np.uint32)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0], out[:, 1] = e0 & 255, e0 >> 8
    out[:, 2], out[:, 3] = e1 & 255, e1 >> 8
    for k in range(4):
        out[:, 4 + k] = (bits >> (8 * k)) & 255
    return out


def _alpha_blocks(a):
    """a: (n, 16) float -> (n, 8) uint8 DXT5 alpha blocks (8-value mode)."""
    n = a.shape[0]
    a0, a1 = a.max(1).round(), a.min(1).round()
    pal = np.stack([a0, a1] + [((7 - k) * a0 + k * a1) / 7 for k in range(1, 7)], 1)
    idx = np.abs(a[:, :, None] - pal[:, None, :]).argmin(-1).astype(np.uint64)
    idx[a0 == a1] = 0
    bits = (idx << (3 * np.arange(16, dtype=np.uint64))).sum(1)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0], out[:, 1] = a0.astype(np.uint8), a1.astype(np.uint8)
    for k in range(6):
        out[:, 2 + k] = ((bits >> np.uint64(8 * k)) & np.uint64(255)).astype(np.uint8)
    return out


def encode(img, fmt):
    """img (h, w, 4) uint8, h and w multiples of 4 -> bytes. fmt 'DXT1' or 'DXT5'."""
    b = _blocks(img.astype(np.float32))
    color = _color_blocks(b[:, :, :3])
    if fmt == "DXT1":
        return color.tobytes()
    return np.concatenate([_alpha_blocks(b[:, :, 3]), color], 1).tobytes()


def decode(data, w, h, fmt):
    """bytes -> (h, w, 4) uint8 (DXT1 decoded in 4-color or 3-color+transparent mode)."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    size = 8 if fmt == "DXT1" else 16
    raw = np.frombuffer(data, np.uint8, bw * bh * size).reshape(-1, size)
    out_a = np.full((raw.shape[0], 16), 255, np.float32)
    if fmt == "DXT5":
        a0, a1 = raw[:, 0].astype(np.float32), raw[:, 1].astype(np.float32)
        eight = a0 > a1
        pal = np.zeros((raw.shape[0], 8), np.float32)
        pal[:, 0], pal[:, 1] = a0, a1
        for k in range(1, 7):
            pal[:, k + 1] = np.where(eight, ((7 - k) * a0 + k * a1) / 7, 0)
        for k in range(1, 5):
            pal[:, k + 1] = np.where(eight, pal[:, k + 1], ((5 - k) * a0 + k * a1) / 5)
        pal[:, 6] = np.where(eight, pal[:, 6], 0)
        pal[:, 7] = np.where(eight, pal[:, 7], 255)
        bits = sum(raw[:, 2 + k].astype(np.uint64) << np.uint64(8 * k) for k in range(6))
        idx = ((bits[:, None] >> (3 * np.arange(16, dtype=np.uint64))) & np.uint64(7)).astype(np.int64)
        out_a = np.take_along_axis(pal, idx, 1)
        raw = raw[:, 8:]
    e0 = raw[:, 0].astype(np.uint32) | (raw[:, 1].astype(np.uint32) << 8)
    e1 = raw[:, 2].astype(np.uint32) | (raw[:, 3].astype(np.uint32) << 8)
    p0, p1 = _from565(e0), _from565(e1)
    four = (e0 > e1) | (fmt == "DXT5")
    pal = np.stack([p0, p1, np.where(four[:, None], (2 * p0 + p1) / 3, (p0 + p1) / 2),
                    np.where(four[:, None], (p0 + 2 * p1) / 3, 0)], 1)
    bits = sum(raw[:, 4 + k].astype(np.uint32) << (8 * k) for k in range(4))
    idx = ((bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))) & 3).astype(np.int64)
    rgb = np.take_along_axis(pal, idx[:, :, None].repeat(3, 2), 1)
    if fmt == "DXT1":
        out_a = np.where((idx == 3) & ~four[:, None], 0, 255).astype(np.float32)
    px = np.concatenate([rgb, out_a[:, :, None]], 2)
    img = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return np.clip(np.round(img), 0, 255).astype(np.uint8)[:h, :w]


def _srgb_to_linear(c):
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(c):
    c = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(np.clip(c, 0, None), 1 / 2.4) - 0.055)
    return np.clip(np.round(c * 255), 0, 255)


def mipmaps(img, normal=False):
    """Full mip chain, largest first. Color averaged in linear light; normal maps renormalized."""
    chain = [img]
    cur = img.astype(np.float32)
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        h, w = max(1, cur.shape[0] // 2), max(1, cur.shape[1] // 2)
        fy, fx = cur.shape[0] // h, cur.shape[1] // w
        if normal:
            v = cur[..., :3] / 127.5 - 1
            v = v.reshape(h, fy, w, fx, 3).mean((1, 3))
            v /= np.linalg.norm(v, axis=-1, keepdims=True) + 1e-8
            rgb = np.clip(np.round((v + 1) * 127.5), 0, 255)
        else:
            lin = _srgb_to_linear(cur[..., :3]).reshape(h, fy, w, fx, 3).mean((1, 3))
            rgb = _linear_to_srgb(lin)
        a = cur[..., 3:].reshape(h, fy, w, fx, 1).mean((1, 3))
        cur = np.concatenate([rgb, np.round(a)], -1)
        chain.append(cur.astype(np.uint8))
    return chain


def pad4(img):
    """Pad to multiples of 4 by edge replication (tiny mips)."""
    h, w = img.shape[:2]
    H, W = max(4, (h + 3) // 4 * 4), max(4, (w + 3) // 4 * 4)
    if (H, W) == (h, w):
        return img
    return np.pad(img, ((0, H - h), (0, W - w), (0, 0)), mode="edge")


def psnr(a, b):
    mse = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    return float("inf") if mse == 0 else 10 * np.log10(255 ** 2 / mse)
