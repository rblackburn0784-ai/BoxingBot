# make_placeholders.py
# pip install pillow
from PIL import Image, ImageDraw, ImageFont
import os

BASE = "graphics"
os.makedirs(BASE, exist_ok=True)
os.makedirs(os.path.join(BASE, "music"), exist_ok=True)

W, H = 480, 270
BG = {
    "MM": (30, 30, 30),
    "MF": (30, 50, 80),
    "FF": (70, 30, 70),
}
CORNER = {
    "Red":  (180, 40, 40),
    "Blue": (40, 80, 180),
}
WHITE = (240, 240, 240)

def mk(text_lines, path, bg=(40,40,40)):
    if os.path.exists(path):
        return
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    try:
        # try a nicer font if present
        font = ImageFont.truetype("arial.ttf", 24)
        font_big = ImageFont.truetype("arial.ttf", 36)
    except Exception:
        font = ImageFont.load_default()
        font_big = font

    # draw a simple border
    d.rectangle((4,4,W-5,H-5), outline=(200,200,200), width=3)

    # center the lines
    y = 60
    for i, line in enumerate(text_lines):
        f = font_big if i == 0 else font
        tw, th = d.textsize(line, font=f)
        d.text(((W - tw)//2, y), line, fill=WHITE, font=f)
        y += th + 10

    img.save(path, "GIF")
    print("created", path)

def ensure(fname):
    return os.path.join(BASE, fname)

# ---- Generic round gifs
mk(["ROUND", "MM"], ensure("round_mm.gif"), BG["MM"])
mk(["ROUND", "MF"], ensure("round_mf.gif"), BG["MF"])
mk(["ROUND", "FF"], ensure("round_ff.gif"), BG["FF"])

# ---- Ring gif
mk(["RING", "READY"], ensure("ring.gif"), (20,60,20))

# ---- Highlight gifs
matchups = ["MM","MF","FF"]
corners  = ["Red","Blue"]
types    = ["glancing","jab","cross","hook","uppercut","miss","low_blow"]

def hl_name(m,c,t):
    return f"highlight_{m.lower()}_{c.lower()}_{t}.gif"

for m in matchups:
    for c in corners:
        for t in types:
            bg = tuple(int((BG[m][i]*0.7 + CORNER[c][i]*0.3)) for i in range(3))
            mk([f"HIGHLIGHT", f"{m} • {c}", t.upper()], ensure(hl_name(m,c,t)), bg)

# ---- Finish gifs
finish_types = ["ko","tko","points"]
def fin_name(m,c,w):
    return f"{m.lower()}_{c.lower()}_{w.lower()}.gif"

for m in matchups:
    for c in corners:
        for w in finish_types:
            bg = tuple(int((BG[m][i]*0.5 + CORNER[c][i]*0.5)) for i in range(3))
            mk(["RESULT", f"{m} • {c}", w.upper()], ensure(fin_name(m,c,w)), bg)

print("Done. Placeholders are ready.")