"""Genereert het app-icoon en het vensterlogo uit het Werdens Media-merk.

Gebruik:  python tools/make_branding.py
Uitvoer:  branding/logo.png (512), branding/logo-256.png, branding/app.ico,
          docs/logo/icoon-*.png (controlebeelden)

Het echte merk staat in branding/werdens-media-logo.png; dat bestand wordt
gemaakt door tools/prepare_werdens_logo.py uit het aangeleverde bronbeeld.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brand_icon import BRANDING, ROOT, draw_icon  # noqa: E402

from PyQt5.QtGui import QGuiApplication  # noqa: E402

ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
PREVIEW_SIZES = (256, 64, 32, 16)


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - nodig voor QPixmap
    BRANDING.mkdir(exist_ok=True)

    draw_icon(512).save(str(BRANDING / "logo.png"), "PNG")
    draw_icon(256).save(str(BRANDING / "logo-256.png"), "PNG")

    preview_dir = ROOT / "docs" / "logo"
    preview_dir.mkdir(parents=True, exist_ok=True)
    for size in PREVIEW_SIZES:
        draw_icon(size).save(str(preview_dir / f"icoon-{size}.png"), "PNG")

    try:
        from PIL import Image
    except ImportError:
        print("Pillow ontbreekt; branding/app.ico niet bijgewerkt (logo.png wel).")
        return 0

    temp = BRANDING / "_icon-256.png"
    draw_icon(256).save(str(temp), "PNG")
    with Image.open(temp) as image:
        image.save(BRANDING / "app.ico", sizes=ICO_SIZES)
    temp.unlink(missing_ok=True)

    print(f"logo.png, logo-256.png en app.ico geschreven in {BRANDING}")
    print(f"controlebeelden: {preview_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
