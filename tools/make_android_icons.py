"""Genereert de Android-launchericonen uit het Werdens Media-merk.

Gebruik: python tools/make_android_icons.py
Uitvoer: android/app/src/main/res/mipmap-*/ic_launcher[_round].png
         android/app/src/main/res/drawable-nodpi/ic_launcher_foreground.png
         docs/logo/android-icoon-<dichtheid>.png (controlebeelden)

Hetzelfde merk wordt ook voor Windows gebruikt (tools/make_branding.py); de
tekening zelf staat in tools/brand_icon.py, zodat beide platformen gelijk zijn.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brand_icon import ROOT, draw_foreground, draw_icon  # noqa: E402

from PyQt5.QtGui import QGuiApplication  # noqa: E402

RES = ROOT / "android" / "app" / "src" / "main" / "res"

DENSITIES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - nodig voor QPixmap

    preview_dir = ROOT / "docs" / "logo"
    preview_dir.mkdir(parents=True, exist_ok=True)

    for density, size in DENSITIES.items():
        directory = RES / f"mipmap-{density}"
        directory.mkdir(parents=True, exist_ok=True)

        square = draw_icon(size, plate="rounded")
        square.save(str(directory / "ic_launcher.png"), "PNG")

        # Een rond icoon heeft geen hoeken: een schijf als vlak en het merk iets
        # kleiner, zodat de puntige uiteinden binnen de cirkel blijven.
        round_icon = draw_icon(size, plate="circle", coverage=0.68)
        round_icon.save(str(directory / "ic_launcher_round.png"), "PNG")

        if density == "xxxhdpi":
            round_icon.save(str(preview_dir / "android-icoon-rond.png"), "PNG")
            square.save(str(preview_dir / "android-icoon-vierkant.png"), "PNG")
        print(f"mipmap-{density}: {size}x{size}")

    foreground_dir = RES / "drawable-nodpi"
    foreground_dir.mkdir(parents=True, exist_ok=True)
    draw_foreground(432).save(str(foreground_dir / "ic_launcher_foreground.png"), "PNG")
    print("adaptive foreground: 432x432 (veilige zone)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
