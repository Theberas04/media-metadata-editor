"""Genereert de Android-launchericonen uit dezelfde tekening als het logo.

Gebruik: python tools/make_android_icons.py
Uitvoer: android/app/src/main/res/mipmap-*/ic_launcher[_round].png
         android/app/src/main/res/drawable-nodpi/ic_launcher_foreground.png
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt5.QtGui import QColor, QGuiApplication, QPainter, QPixmap, QPolygonF  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "android" / "app" / "src" / "main" / "res"

DENSITIES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}

NAVY = "#0f172a"
BLUE = "#2563eb"
WHITE = "#ffffff"


def draw_mark(pixmap: QPixmap, plate: bool) -> QPixmap:
    size = pixmap.width()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)

    if plate:
        painter.setBrush(QColor(NAVY))
        radius = size * 0.22
        painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    # Voor het adaptieve icoon staat het beeld in de veilige zone (ongeveer 62%).
    scale = 0.62 if not plate else 0.62
    diameter = size * scale
    offset = (size - diameter) / 2
    painter.setBrush(QColor(BLUE))
    painter.drawEllipse(QRectF(offset, offset, diameter, diameter))

    painter.setBrush(QColor(WHITE))
    cx, cy = size * 0.53, size * 0.5
    half = diameter * 0.24
    painter.drawPolygon(QPolygonF([
        QPointF(cx - half * 0.75, cy - half),
        QPointF(cx - half * 0.75, cy + half),
        QPointF(cx + half, cy),
    ]))
    painter.end()
    return pixmap


def render(size: int, plate: bool) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    return draw_mark(pixmap, plate)


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841
    for density, size in DENSITIES.items():
        directory = RES / f"mipmap-{density}"
        directory.mkdir(parents=True, exist_ok=True)
        icon = render(size, plate=True)
        icon.save(str(directory / "ic_launcher.png"), "PNG")
        icon.save(str(directory / "ic_launcher_round.png"), "PNG")
        print(f"mipmap-{density}: {size}x{size}")

    foreground_dir = RES / "drawable-nodpi"
    foreground_dir.mkdir(parents=True, exist_ok=True)
    render(432, plate=False).save(str(foreground_dir / "ic_launcher_foreground.png"), "PNG")
    print("adaptive foreground: 432x432")
    return 0


if __name__ == "__main__":
    sys.exit(main())