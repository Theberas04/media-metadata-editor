"""Genereert het logo en het Windows-icoon uit één bron (Qt-tekening).

Gebruik:  python tools/make_branding.py [--check]
Uitvoer:  branding/logo.png, branding/app.ico, branding/logo-256.png
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt5.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPixmap, QPolygonF  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BRANDING = ROOT / "branding"

NAVY = "#0f172a"
BLUE = "#2563eb"
WHITE = "#ffffff"


def draw_logo(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(NAVY))
    radius = size * 0.22
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    # Blauwe schijf met een witte play-driehoek: leesbaar tot 16 px.
    margin = size * 0.19
    painter.setBrush(QColor(BLUE))
    painter.drawEllipse(QRectF(margin, margin, size - 2 * margin, size - 2 * margin))

    painter.setBrush(QColor(WHITE))
    cx, cy = size * 0.53, size * 0.5
    half = size * 0.145
    triangle = QPolygonF([
        QPointF(cx - half * 0.75, cy - half),
        QPointF(cx - half * 0.75, cy + half),
        QPointF(cx + half, cy),
    ])
    painter.drawPolygon(triangle)

    painter.end()
    return pixmap


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - nodig voor QPixmap
    BRANDING.mkdir(exist_ok=True)

    big = draw_logo(512)
    logo_path = BRANDING / "logo.png"
    big.save(str(logo_path), "PNG")

    for size in (256,):
        draw_logo(size).save(str(BRANDING / f"logo-{size}.png"), "PNG")

    try:
        from PIL import Image
    except ImportError:
        print("Pillow ontbreekt; branding/app.ico niet bijgewerkt.")
        return 0

    temp = BRANDING / "_icon-256.png"
    draw_logo(256).save(str(temp), "PNG")
    with Image.open(temp) as image:
        image.save(BRANDING / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                                (64, 64), (128, 128), (256, 256)])
    temp.unlink(missing_ok=True)
    print(f"logo.png, logo-256.png en app.ico geschreven in {BRANDING}")
    return 0


if __name__ == "__main__":
    sys.exit(main())