"""Export approved artwork without redrawing its hand contours."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "tools" / "brand" / "approved-hand-heart.png"
ICON_SIZES = [(n, n) for n in (16, 24, 32, 48, 64, 128, 256)]

def main():
    with Image.open(MASTER) as source:
        icon = source.convert("RGBA").resize((256, 256), Image.Resampling.LANCZOS)
    icon.save(ROOT / "web" / "shulian-brand-icon.png", optimize=True)
    icon.save(ROOT / "shulian.ico", format="ICO", sizes=ICON_SIZES)

if __name__ == "__main__":
    main()
