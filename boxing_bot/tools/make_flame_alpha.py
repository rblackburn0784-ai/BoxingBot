# boxing_bot/tools/make_flame_alpha.py
from __future__ import annotations
from pathlib import Path
import argparse
from PIL import Image, ImageChops, ImageFilter, ImageEnhance

def guess_project_root() -> Path:
    # this file lives in boxing_bot/tools/ => root is two parents up
    return Path(__file__).resolve().parents[2]

def resolve_source(src: str | None) -> Path | None:
    root = guess_project_root()

    candidates: list[Path] = []
    if src:
        sp = Path(src)
        if sp.is_absolute():
            candidates.append(sp)
        else:
            candidates.append(root / sp)
            candidates.append(Path.cwd() / sp)

    # If no src or not found, try common names and recursive search
    candidates += [
        root / "graphics/promo/icons/Flame.png",
        root / "graphics/promo/icons/flame.png",
    ]

    for c in candidates:
        if c.exists():
            return c

    # recursive search for a plausible flame file
    for name in ("Flame.png", "flame.png"):
        hits = list(root.rglob(name))
        if hits:
            return hits[0]

    return None

def make_flame_alpha(src: Path, out: Path) -> Path:
    im = Image.open(src).convert("RGBA")

    # build mask from saturation * value (bright + colorful)
    HSV = im.convert("HSV")
    H, S, V = HSV.split()
    mask = ImageChops.multiply(S, V).point(lambda p: 255 if p > 60 else 0)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    mask = ImageEnhance.Brightness(mask).enhance(1.2)

    im.putalpha(mask)

    # Optional punch: color/contrast
    rgb = im.convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(1.3)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.15)
    out_img = Image.merge("RGBA", (*rgb.split(), mask))

    out.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(out)
    print(f"✅ Saved: {out}")
    return out

def main():
    parser = argparse.ArgumentParser(description="Make a real-alpha flame PNG from a checkerboard PNG.")
    parser.add_argument("--src", help="Path to source image (e.g. Flame.png). If omitted, we try to auto-find it.")
    parser.add_argument("--out", help="Output path (default graphics/promo/icons/flame.png under project root).")
    args = parser.parse_args()

    src_path = resolve_source(args.src)
    if not src_path:
        print("❌ Could not find a source image.\n"
              "Tried project-root & CWD, plus recursive search for Flame.png / flame.png.\n"
              "Provide --src with a valid path or place Flame.png in graphics/promo/icons/")
        return

    root = guess_project_root()
    out_path = Path(args.out) if args.out else (root / "graphics/promo/icons/flame.png")

    print(f"Source: {src_path}")
    print(f"Output: {out_path}")
    make_flame_alpha(src_path, out_path)

if __name__ == "__main__":
    main()
