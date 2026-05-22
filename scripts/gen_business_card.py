#!/usr/bin/env python3
"""
生成长江证券武汉新华路营业部名片 PDF
尺寸：90mm × 54mm @ 300dpi
"""

from PIL import Image, ImageDraw, ImageFont

DPI   = 300
W     = int(90 / 25.4 * DPI)   # 1063
H     = int(54 / 25.4 * DPI)   # 638

FONT_ZH   = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
FONT_EN   = "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf"
FONT_EN_B = "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf"
OUT       = "/home/liam-sun/孙亮_长江证券名片.pdf"

RED   = (200, 16, 46)
GOLD  = (184, 150, 12)
WHITE = (255, 255, 255)
DARK  = (26, 26, 26)
GRAY  = (100, 100, 100)
PINK  = (255, 200, 200)


def px(mm): return int(mm / 25.4 * DPI)
def fz(s):  return ImageFont.truetype(FONT_ZH,   s)
def fe(s):  return ImageFont.truetype(FONT_EN,    s)
def feb(s): return ImageFont.truetype(FONT_EN_B,  s)


def draw_mixed(d, xy, text, font_zh, font_en, fill):
    """逐字判断是否为中文，分别用不同字体绘制，返回结束 x 坐标。"""
    x, y = xy
    for ch in text:
        f = font_zh if ord(ch) > 127 else font_en
        d.text((x, y), ch, font=f, fill=fill)
        bbox = d.textbbox((0, 0), ch, font=f)
        x += bbox[2] - bbox[0] + 1
    return x


# ══════════════════════════════════════════════════════════════════
# 正面
# ══════════════════════════════════════════════════════════════════
front = Image.new("RGB", (W, H), WHITE)
d = ImageDraw.Draw(front)

# 顶部红块
d.rectangle([0, 0, W, px(16)], fill=RED)
# 左侧红竖条
d.rectangle([0, px(16), px(2.5), H], fill=RED)
# 底部金线
d.rectangle([px(6), H - px(6) - 2, W - px(6), H - px(6)], fill=GOLD)

# 公司中文名
d.text((px(6), px(2.2)), "长江证券股份有限公司", font=fz(38), fill=WHITE)
# 英文名
d.text((px(6), px(10)),  "Changjiang Securities Co., Ltd.", font=fe(19), fill=PINK)

# 姓名
d.text((px(6), px(17)), "孙  亮", font=fz(62), fill=DARK)

# 职位（中文）
d.text((px(6), px(30)), "客户经理", font=fz(26), fill=RED)
# 职位分隔线
d.text((px(27.5), px(30.3)), "|", font=feb(26), fill=GRAY)
# 职位（英文）
d.text((px(30), px(30.5)), "Customer Manager", font=fe(22), fill=GRAY)

# 营业部
d.text((px(6), px(37.5)), "武汉新华路营业部", font=fz(23), fill=GRAY)

# 联系方式
y = px(43.5)
items = [
    ("手机/微信", "13317178088"),
    ("邮    箱",  "8407020@qq.com"),
]
for label, val in items:
    d.text((px(6), y), label, font=fz(20), fill=RED)
    d.text((px(22.5), y), val, font=fe(22), fill=DARK)
    y += px(4.8)

# ══════════════════════════════════════════════════════════════════
# 背面
# ══════════════════════════════════════════════════════════════════
back = Image.new("RGB", (W, H), RED)
d2   = ImageDraw.Draw(back)

# 装饰横线
d2.rectangle([px(8), H//2 - px(10),     W - px(8), H//2 - px(10) + 2], fill=(220, 60, 80))
d2.rectangle([px(8), H//2 + px(10) - 2, W - px(8), H//2 + px(10)    ], fill=(220, 60, 80))

# 公司中文名居中
cn_text = "长江证券股份有限公司"
fn_big  = fz(46)
bbox    = d2.textbbox((0, 0), cn_text, font=fn_big)
tw      = bbox[2] - bbox[0]
d2.text(((W - tw) // 2, H//2 - px(9)), cn_text, font=fn_big, fill=WHITE)

# 英文名居中
en_text = "Changjiang Securities Co., Ltd."
fn_sm   = fe(21)
bbox2   = d2.textbbox((0, 0), en_text, font=fn_sm)
tw2     = bbox2[2] - bbox2[0]
d2.text(((W - tw2) // 2, H//2 + px(2)), en_text, font=fn_sm, fill=PINK)

# ── 输出 PDF ─────────────────────────────────────────────────────
front.save(OUT, save_all=True, append_images=[back],
           resolution=DPI, format="PDF")
print(f"名片已生成：{OUT}")
