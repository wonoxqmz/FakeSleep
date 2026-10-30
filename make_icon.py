# -*- coding: utf-8 -*-
"""纯标准库生成 FakeSleep 图标（PNG + ICO），不依赖 Pillow。

图形：深色圆角方块 + 绿色月牙 + 两颗小星。
"""
import struct
import zlib

BG = (16, 16, 20)
GREEN = (61, 220, 132)
GREEN_DIM = (61, 220, 132)

# 各形状的归一化参数
R_CORNER = 0.22
MOON_C = (0.50, 0.50)
MOON_R = 0.30
CUT_C = (0.695, 0.385)
CUT_R = 0.295
STARS = [((0.775, 0.245), 0.028), ((0.855, 0.385), 0.017)]


def in_round_rect(u, v, r):
    dx = max(r - u, 0.0, u - (1.0 - r))
    dy = max(r - v, 0.0, v - (1.0 - r))
    return dx * dx + dy * dy <= r * r


def in_circle(u, v, c, r):
    dx = u - c[0]
    dy = v - c[1]
    return dx * dx + dy * dy <= r * r


def render(size, ss=4):
    """超采样渲染，返回 RGBA bytes。"""
    buf = bytearray(size * size * 4)
    step = 1.0 / (size * ss)
    inv = 1.0 / (ss * ss)
    for py in range(size):
        for px in range(size):
            ar = ag = ab = aa = 0.0
            for sy in range(ss):
                for sx in range(ss):
                    u = (px * ss + sx + 0.5) * step
                    v = (py * ss + sy + 0.5) * step
                    if not in_round_rect(u, v, R_CORNER):
                        continue
                    # 底色 + 内描边
                    if not in_round_rect(u, v, R_CORNER - 0.010):
                        col, a = (61, 220, 132), 0.22
                    else:
                        col, a = BG, 1.0
                    # 月牙（大圆减偏移圆）
                    if in_circle(u, v, MOON_C, MOON_R) and not in_circle(u, v, CUT_C, CUT_R):
                        col, a = GREEN, 1.0
                    else:
                        for c, r in STARS:
                            if in_circle(u, v, c, r):
                                col, a = GREEN_DIM, 0.9
                                break
                    ar += col[0] * a
                    ag += col[1] * a
                    ab += col[2] * a
                    aa += a
            i = (py * size + px) * 4
            if aa > 0:
                buf[i] = int(ar / aa + 0.5)
                buf[i + 1] = int(ag / aa + 0.5)
                buf[i + 2] = int(ab / aa + 0.5)
                buf[i + 3] = int(min(aa * inv, 1.0) * 255 + 0.5)
    return bytes(buf)


def png_bytes(size, rgba):
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        raw += rgba[y * size * 4:(y + 1) * size * 4]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def ico_bytes(entries):
    n = len(entries)
    header = struct.pack("<HHH", 0, 1, n)
    offset = 6 + 16 * n
    dirs, blobs = b"", b""
    for size, png in entries:
        w = 0 if size >= 256 else size
        dirs += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    return header + dirs + blobs


if __name__ == "__main__":
    sizes = [256, 128, 64, 48, 32, 16]
    entries = []
    for s in sizes:
        ss = 4 if s >= 128 else 3
        png = png_bytes(s, render(s, ss))
        entries.append((s, png))
        print("rendered", s)
    with open(r"E:\jiaxiumian\icon.ico", "wb") as f:
        f.write(ico_bytes(entries))
    with open(r"E:\jiaxiumian\icon.png", "wb") as f:
        f.write(entries[0][1])
    print("icon.ico / icon.png 已生成")
