"""Het Werdens Media-logo als app-icoon (Windows en Android) op één plek.

Het aangeleverde logo is een breed merk (536x396, doorzichtige achtergrond).
Dit bestand zet dat merk op een vierkant vlak, zodat het als programma-icoon en
als launcher-icoon werkt. Alle maten komen hier vandaan, zodat Windows en
Android hetzelfde beeld tonen.

Gebruik (vanuit andere tools):  from brand_icon import square_icon
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QRectF, Qt  # noqa: E402
from PyQt5.QtGui import QColor, QPainter, QPixmap  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BRANDING = ROOT / "branding"
LOGO = BRANDING / "werdens-media-logo.png"

PAPER = "#ffffff"

# Het merk is breder dan hoog. Bij deze breedte (als deel van het vlak) oogt het
# vierkant gevuld zonder dat de puntige uiteinden de rand raken.
MARK_WIDTH = 0.78
# Android knipt een adaptief icoon bij tot de veilige zone (de binnenste 61%);
# binnen die zone blijft het merk volledig staan.
SAFE_ZONE = 0.60


def _mark_pixmap(width: int) -> QPixmap:
    if not LOGO.is_file():
        raise SystemExit(f"logo ontbreekt: {LOGO} (draai eerst tools/prepare_werdens_logo.py)")
    pixmap = QPixmap(str(LOGO))
    if pixmap.isNull():
        raise SystemExit(f"logo kon niet gelezen worden: {LOGO}")
    return pixmap.scaledToWidth(width, Qt.SmoothTransformation)


def draw_icon(size: int, *, plate: str = "rounded", coverage: float = MARK_WIDTH) -> QPixmap:
    """Vierkant icoon met het merk gecentreerd.

    plate: "rounded" (vierkant met afgeronde hoeken), "circle" of "square".
    coverage: breedte van het merk als deel van het hele vlak.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.setPen(Qt.NoPen)

    if plate == "square":
        painter.fillRect(QRectF(0, 0, size, size), QColor(PAPER))
    elif plate == "circle":
        painter.setBrush(QColor(PAPER))
        painter.drawEllipse(QRectF(0, 0, size, size))
    else:
        painter.setBrush(QColor(PAPER))
        radius = size * 0.22
        painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    mark = _mark_pixmap(max(1, int(round(size * coverage))))
    x = (size - mark.width()) / 2
    y = (size - mark.height()) / 2
    painter.drawPixmap(int(round(x)), int(round(y)), mark)
    painter.end()
    return pixmap


def draw_foreground(size: int = 432) -> QPixmap:
    """Voorgrondlaag voor het adaptieve Android-icoon (transparant, veilige zone)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    mark = _mark_pixmap(max(1, int(round(size * SAFE_ZONE))))
    painter.drawPixmap((size - mark.width()) // 2, (size - mark.height()) // 2, mark)
    painter.end()
    return pixmap
