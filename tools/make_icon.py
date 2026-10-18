"""生成「行情条」的羽毛图标：assets/feather.png + assets/行情条.ico

设计：
  * 底：深色圆角方块（#151c26 → #0b0e11 微渐变），跟程序主色一致
  * 主体：一根斜置（左下→右上）的羽毛，浅色 #e9eef6 羽片 + 深色翎管 + 羽枝缺口
  * 缺口从外缘往翎管方向切到 60% 处停住，左右两侧对称 —— 这样才像羽毛，不像树叶
小尺寸（16px）也能认出来。
"""

import os
from PIL import Image, ImageDraw

OUT = r"G:\mydeepseek\crypto-ticker\assets"
os.makedirs(OUT, exist_ok=True)

S = 1024
SS = 3
W = S * SS

BG_TOP = (20, 26, 35)
BG_BOT = (10, 13, 16)
VANE = (255, 255, 255)
SHAFT = (58, 68, 82)
ACCENT = (90, 200, 250)


def rounded_bg(size, radius_ratio=0.225):
    grad = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / (size - 1)
        c = tuple(int(BG_TOP[i] * (1 - t) + BG_BOT[i] * t) for i in range(3))
        d.line([(0, y), (size, y)], fill=c)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1],
                                           radius=int(size * radius_ratio), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def feather_layer(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    ax, ay = 0.135 * size, 0.875 * size      # 翎管根
    bx, by = 0.885 * size, 0.125 * size      # 羽尖
    vx, vy = bx - ax, by - ay
    L = (vx * vx + vy * vy) ** 0.5
    ux, uy = vx / L, vy / L                  # 轴向
    nx, ny = -uy, ux                         # 法向

    def P(t, s):
        """轴上的 t 处，偏离轴的 s（-1..1 倍半宽）的点"""
        return (ax + vx * t + nx * s, ay + vy * t + ny * s)

    # --- 羽片：一串沿法向的短线段，端点按"半宽剖面"决定 ---
    t0, t1 = 0.075, 0.995
    peak, peak_at = 0.150 * size, 0.47
    steps = 600
    for i in range(steps + 1):
        t = t0 + (t1 - t0) * i / steps
        # 半宽剖面：根部 0→中段 peak→尖端 0（尖端收得更陡）
        if t <= peak_at:
            k = ((t - t0) / (peak_at - t0)) ** 0.62
        else:
            k = max(0.0, (t1 - t) / (t1 - peak_at)) ** 0.95
        half = peak * k
        if half < 0.5:
            continue
        p1 = P(t, -half)
        p2 = P(t, +half)
        d.line([p1, p2], fill=VANE + (255,), width=max(2, int(size / 420)))

    # --- 羽枝缺口：左右对称，从外缘往轴切到 55% 处 ---
    gap = Image.new("L", (size, size), 0)
    dg = ImageDraw.Draw(gap)
    for i in range(7):
        t = 0.235 + i * 0.092
        if t > 0.93:
            break
        if t <= peak_at:
            k = ((t - t0) / (peak_at - t0)) ** 0.62
        else:
            k = max(0.0, (t1 - t) / (t1 - peak_at)) ** 0.95
        half = peak * k
        for sgn in (-1, 1):
            outer = P(t, sgn * half * 1.06)
            inner = P(t + 0.030, sgn * half * 0.42)
            dg.line([outer, inner], fill=255, width=max(2, int(size * 0.013)))
    img.putalpha(Image.composite(Image.new("L", (size, size), 0), img.split()[3], gap))

    # --- 翎管：深的细杆，末端露一点点"羽根" ---
    d = ImageDraw.Draw(img)
    root = (ax - (vx / L) * size * 0.012, ay - (vy / L) * size * 0.012)
    d.line([root, (bx - (vx / L) * size * 0.055, by - (vy / L) * size * 0.055)],
           fill=SHAFT + (255,), width=max(3, int(size * 0.026)))
    d.line([root, (bx - (vx / L) * size * 0.075, by - (vy / L) * size * 0.075)],
           fill=ACCENT + (70,), width=max(1, int(size * 0.009)))
    return img


def build(size):
    return Image.alpha_composite(rounded_bg(size), feather_layer(size))


master = build(W).resize((S, S), Image.LANCZOS)
master.save(os.path.join(OUT, "feather.png"))

sizes = [256, 128, 64, 48, 40, 32, 24, 20, 16]
imgs = [master.resize((s, s), Image.LANCZOS) for s in sizes]
ico = os.path.join(OUT, "行情条.ico")
imgs[0].save(ico, format="ICO", sizes=[(s, s) for s in sizes])

# 预览条：16→256 摆一排，放大 3 倍看小尺寸表现
strip = Image.new("RGBA", (sum(sizes) + 8 * len(sizes) + 8, 256 + 16), (255, 255, 255, 0))
x = 8
for im in reversed(imgs):
    strip.paste(im.resize((im.width * 3, im.height * 3), Image.NEAREST), (x, 8), im.resize((im.width * 3, im.height * 3), Image.NEAREST))
    x += im.width * 3 + 8
strip.save(os.path.join(OUT, "_preview_strip.png"))
print("ok", ico, os.path.getsize(ico), "strip", strip.size)
