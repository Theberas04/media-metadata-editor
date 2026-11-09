"""Maakt demo-media (video + audio met cover) voor screenshots en de demo-opname.

De titelkaart wordt met Qt getekend (geen drawtext/font-afhankelijkheid) en daarna
met ffmpeg tot een echt mediabestand gemaakt, inclusief metadata.

Gebruik: python tools/make_demo_media.py --out ./.demo
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt5.QtGui import (  # noqa: E402
    QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPixmap, QRadialGradient,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mediameta import core  # noqa: E402

W, H = 1280, 720


def draw_card(title: str, subtitle: str, tag: str) -> QPixmap:
    pixmap = QPixmap(W, H)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    gradient = QLinearGradient(0, 0, W, H)
    gradient.setColorAt(0.0, QColor("#0b1a34"))
    gradient.setColorAt(0.55, QColor("#12314f"))
    gradient.setColorAt(1.0, QColor("#1c1007"))
    painter.fillRect(0, 0, W, H, gradient)

    # Warme "zon" linksonder, als een zonsopkomst.
    glow = QRadialGradient(QPointF(W * 0.30, H * 0.78), H * 0.52)
    glow.setColorAt(0.0, QColor(255, 176, 92, 200))
    glow.setColorAt(0.45, QColor(255, 145, 60, 60))
    glow.setColorAt(1.0, QColor(255, 140, 60, 0))
    painter.fillRect(0, 0, W, H, glow)

    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 18))
    painter.drawEllipse(QRectF(W * 0.30 - 150, H * 0.78 - 150, 300, 300))

    # Titelblok
    painter.setPen(QColor("#ffffff"))
    title_font = QFont("DejaVu Sans", 46, QFont.DemiBold)
    painter.setFont(title_font)
    painter.drawText(QRectF(90, H * 0.30, W - 180, 140), Qt.AlignLeft | Qt.AlignBottom, title)

    painter.setPen(QColor(255, 255, 255, 175))
    painter.setFont(QFont("DejaVu Sans", 19))
    painter.drawText(QRectF(92, H * 0.30 + 150, W - 180, 60), Qt.AlignLeft | Qt.AlignTop, subtitle)

    # Kleine tag linksboven
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, 36))
    painter.drawRoundedRect(QRectF(90, 70, 190, 40), 20, 20)
    painter.setPen(QColor(255, 255, 255, 220))
    painter.setFont(QFont("DejaVu Sans", 12, QFont.DemiBold))
    painter.drawText(QRectF(90, 70, 190, 40), Qt.AlignCenter, tag)

    painter.end()
    return pixmap


def run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg mislukte:\n{' '.join(args)}\n{proc.stderr[-1500:]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=".demo")
    parser.add_argument("--seconds", type=float, default=24.0)
    ns = parser.parse_args()

    app = QGuiApplication(sys.argv)  # noqa: F841
    out = Path(ns.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    video_card = out / "card-video.png"
    audio_card = out / "card-audio.png"
    draw_card("Zonsopkomst boven de Wadden", "demo-fragment · Werdens Media",
              "DEMO").save(str(video_card), "PNG")
    draw_card("Nachtegaal in de duinen", "geluidsopname · demo", "AUDIO").save(str(audio_card), "PNG")

    ffmpeg = core.find_ffmpeg()
    video = out / "wadden-zonsopkomst.mp4"
    audio = out / "duinen-nachtegaal.mp3"

    # Video: stilstaande kaart met een langzame zoom (Ken Burns), 25 fps.
    frames = int(ns.seconds * 25)
    run([
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
        "-loop", "1", "-i", str(video_card),
        "-f", "lavfi", "-i", f"sine=frequency=220:duration={ns.seconds}",
        "-vf", f"zoompan=z='min(zoom+0.00035,1.18)':d={frames}:s={W}x{H}:fps=25,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "96k", "-shortest",
        "-metadata", "title=Zonsopkomst boven de Wadden",
        "-metadata", "artist=Werdens Media",
        "-metadata", "album=Demo-materiaal",
        "-metadata", "genre=Documentaire",
        "-metadata", "date=2026",
        "-metadata", "comment=demo,video,wadden",
        "-movflags", "+faststart",
        str(video),
    ])

    # Audio (mp3) met cover-art, zodat de speler een poster heeft.
    run([
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency=660:duration={ns.seconds * 0.6}",
        "-i", str(audio_card),
        "-map", "0:a", "-map", "1:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic",
        "-c:a", "libmp3lame", "-b:a", "128k",
        "-metadata", "title=Nachtegaal in de duinen",
        "-metadata", "artist=Werdens Media",
        "-metadata", "album=Veldopnames",
        "-metadata", "genre=Natuur",
        "-metadata", "date=2026",
        "-metadata", "comment=demo,audio",
        str(audio),
    ])

    for path in (video, audio):
        info = core.probe(path)
        print(f"{path.name:32} {info.summary():55} tags: {info.fields()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())