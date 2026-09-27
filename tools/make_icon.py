"""生成 HISBot 应用图标（app.png / app.ico）。

纯 Pillow 绘制，跨平台可复现、无需联网素材。为保证小尺寸可辨，ICO 内嵌
三档繁简版本：
- full   （128/256）：蓝色渐变底 + 目标窗口(医疗十字) + 显示器支架 + 绿色对勾徽标
- simple （32/48/64）：去掉支架与窗口三点，放大窗口与对勾
- minimal（16/24）   ：蓝底大白医疗十字 + 右下绿色对勾圆点

用法：
    python tools/make_icon.py [输出目录]
"""
from __future__ import annotations

import struct
import sys
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

S = 1024
TOP = (46, 134, 222)
BOTTOM = (24, 78, 139)
WHITE = (255, 255, 255, 255)
BLUE = (31, 111, 178, 255)
GREEN = (39, 174, 96, 255)


def vertical_gradient(size, top, bottom):
    t = np.linspace(0, 1, size)[:, None, None]
    arr = (np.array(top, float) * (1 - t)
           + np.array(bottom, float) * t).astype(np.uint8)
    arr = np.repeat(arr, size, axis=1)
    return Image.fromarray(arr, "RGB").convert("RGBA")


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1],
                                        radius=radius, fill=255)
    return m


def cross(d, cx, cy, arm, length, fill, radius=None):
    if radius is None:
        radius = arm // 3
    d.rounded_rectangle([cx - arm // 2, cy - length // 2,
                         cx + arm // 2, cy + length // 2],
                        radius=radius, fill=fill)
    d.rounded_rectangle([cx - length // 2, cy - arm // 2,
                         cx + length // 2, cy + arm // 2],
                        radius=radius, fill=fill)


def check_badge(d, size, bx, by, br, ring=True):
    if ring:
        pad = int(0.14 * br)
        d.ellipse([bx - br - pad, by - br - pad, bx + br + pad,
                   by + br + pad], fill=BOTTOM[:3] + (255,))
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=GREEN)
    w = max(3, int(0.30 * br))
    p1 = (bx - int(0.40 * br), by + int(0.03 * br))
    p2 = (bx - int(0.10 * br), by + int(0.36 * br))
    p3 = (bx + int(0.48 * br), by - int(0.32 * br))
    d.line([p1, p2, p3], fill=WHITE, width=w, joint="curve")
    r = w // 2
    for p in (p1, p3):
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=WHITE)


def draw(variant: str = "full", size: int = S):
    img = vertical_gradient(size, TOP, BOTTOM)
    hl = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    ImageDraw.Draw(hl).rounded_rectangle(
        [0, 0, size, size // 2], radius=size // 5,
        fill=(255, 255, 255, 26))
    img = Image.alpha_composite(img, hl)
    d = ImageDraw.Draw(img)
    cx = size // 2

    if variant == "minimal":
        # 16/24 极小尺寸：仅保留最醒目的居中大白十字（对勾在此尺寸不可辨）
        cross(d, cx, int(0.50 * size), arm=int(0.205 * size),
              length=int(0.54 * size), fill=WHITE, radius=int(0.075 * size))
        radius = int(0.20 * size)
    else:
        # 窗口卡片：simple 版更大、更居中
        top_y = int(0.165 * size) if variant == "simple" else int(0.235 * size)
        bot_y = int(0.745 * size) if variant == "simple" else int(0.665 * size)
        if variant == "simple":
            left_x, right_x = int(0.165 * size), int(0.835 * size)
        else:
            left_x, right_x = int(0.205 * size), int(0.795 * size)
        d.rounded_rectangle([left_x, top_y, right_x, bot_y],
                            radius=int(0.06 * size), fill=WHITE)
        if variant == "full":
            dot_y = int(0.292 * size)
            dot_r = int(0.017 * size)
            gap = int(0.052 * size)
            x0 = int(0.262 * size)
            for i, col in enumerate([(231, 86, 79, 255), (240, 195, 70, 255),
                                     (92, 190, 120, 255)]):
                d.ellipse([x0 + i * gap - dot_r, dot_y - dot_r,
                           x0 + i * gap + dot_r, dot_y + dot_r], fill=col)
        ccy = (top_y + bot_y) // 2 + int(0.02 * size)
        cross(d, cx, ccy, arm=int(0.105 * size),
              length=int(0.27 * size), fill=BLUE, radius=int(0.035 * size))

        if variant == "full":
            stand = Image.new("RGBA", (size, size), (255, 255, 255, 0))
            sd = ImageDraw.Draw(stand)
            sd.rounded_rectangle([cx - int(0.035 * size), int(0.675 * size),
                                  cx + int(0.035 * size), int(0.745 * size)],
                                 radius=int(0.02 * size),
                                 fill=(255, 255, 255, 220))
            sd.rounded_rectangle([cx - int(0.135 * size), int(0.742 * size),
                                  cx + int(0.135 * size), int(0.792 * size)],
                                 radius=int(0.026 * size),
                                 fill=(255, 255, 255, 220))
            img = Image.alpha_composite(img, stand)
            d = ImageDraw.Draw(img)
            check_badge(d, size, int(0.752 * size), int(0.672 * size),
                        int(0.165 * size), ring=True)
        else:
            check_badge(d, size, int(0.80 * size), int(0.71 * size),
                        int(0.175 * size), ring=True)
        radius = int(0.224 * size)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), rounded_mask(size, radius))
    return out


def write_ico(path: Path, frames: list[Image.Image]) -> None:
    """手工写多帧 ICO（每帧可用不同设计，PNG 载荷，Vista+/Win10/11 支持）。"""
    header = struct.pack("<HHH", 0, 1, len(frames))
    entries = bytearray()
    payload = bytearray()
    offset = 6 + 16 * len(frames)
    for im in frames:
        w = h = im.width
        rgba = im.convert("RGBA")
        buf = io.BytesIO()
        rgba.save(buf, format="PNG")
        data = buf.getvalue()
        entries += struct.pack(
            "<BBBBHHII",
            0 if w >= 256 else w, 0 if h >= 256 else h,
            0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    path.write_bytes(bytes(header) + bytes(entries) + bytes(payload))


def main():
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[1] / "src" / "hisbot" / "resources")
    out_dir.mkdir(parents=True, exist_ok=True)

    full = draw("full")
    png = out_dir / "app.png"
    full.save(png)

    tiers = {"full": [128, 256], "simple": [32, 48, 64],
             "minimal": [16, 24]}
    renders = {v: draw(v) for v in tiers}
    frames, order = [], []
    for variant in ("minimal", "simple", "full"):
        for s in tiers[variant]:
            frames.append(renders[variant].resize((s, s), Image.LANCZOS))
            order.append(s)
    ico = out_dir / "app.ico"
    write_ico(ico, frames)
    print("wrote", png, "and", ico, "sizes", order)


if __name__ == "__main__":
    main()
