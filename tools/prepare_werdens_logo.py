"""Bereidt het Werdens Media-logo voor op gebruik in de app.

Bron:  branding/werdens-media-logo-bron.jpg  (aangeleverd beeld, witte achtergrond)
Uit:   branding/werdens-media-logo.png       (bijgesneden, witte achtergrond transparant)

Gebruik: python tools/prepare_werdens_logo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtGui import QImage, QGuiApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BRANDING = ROOT / "branding"
SOURCE = BRANDING / "werdens-media-logo-bron.jpg"
TARGET = BRANDING / "werdens-media-logo.png"

# Alles wat lichter is dan dit geldt als achtergrond.
WHITE_CUTOFF = 240


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841
    if not SOURCE.is_file():
        raise SystemExit(f"bronbestand ontbreekt: {SOURCE}")

    image = QImage(str(SOURCE)).convertToFormat(QImage.Format_ARGB32)
    width, height = image.width(), image.height()

    # 1. Kijk waar het beeld echt staat (de randen van de JPG zijn wit).
    left, top, right, bottom = width, height, -1, -1
    for y in range(height):
        for x in range(width):
            colour = image.pixelColor(x, y)
            if min(colour.red(), colour.green(), colour.blue()) < WHITE_CUTOFF:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    if right < 0:
        raise SystemExit("geen beeld gevonden in het bronbestand")

    # Kleine marge zodat het logo niet tegen de rand plakt.
    padding = max(4, int(0.02 * max(right - left, bottom - top)))
    left, top = max(0, left - padding), max(0, top - padding)
    right, bottom = min(width - 1, right + padding), min(height - 1, bottom + padding)
    cropped = image.copy(left, top, right - left + 1, bottom - top + 1)

    # 2. Witte achtergrond transparant maken (met een korte overgang, zodat de
    #    schuine randen niet rafelig worden).
    for y in range(cropped.height()):
        for x in range(cropped.width()):
            colour = cropped.pixelColor(x, y)
            brightness = min(colour.red(), colour.green(), colour.blue())
            if brightness >= WHITE_CUTOFF:
                colour.setAlpha(0)
            elif brightness > WHITE_CUTOFF - 40:
                colour.setAlpha(int(255 * (WHITE_CUTOFF - brightness) / 40))
            cropped.setPixelColor(x, y, colour)

    cropped.save(str(TARGET), "PNG")
    print(f"{TARGET.name}: {cropped.width()}x{cropped.height()} "
          f"(bron {width}x{height}, bijgesneden naar {right - left + 1}x{bottom - top + 1})")
    return 0


if __name__ == "__main__":
    sys.exit(main())