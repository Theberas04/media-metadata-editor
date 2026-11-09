"""Opname van de echte UI: screenshots en een demo-video (offscreen, headless).

Draait de echte MainWindow, doet een vaste scenario en schrijft:
  * screenshots (PNG) van een paar toestanden
  * losse frames die met ffmpeg tot een MP4 worden gezet

Gebruik:
  python tools/capture_demo.py --media ./.demo --stills docs/screenshots \
      --frames .demo/frames --video docs/demo.mp4
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mediameta import core  # noqa: E402
from mediameta.ui import MainWindow  # noqa: E402

FPS = 12


class Session:
    def __init__(self, window: MainWindow, app: QApplication, frames_dir: Path | None):
        self.window = window
        self.app = app
        self.frames_dir = frames_dir
        self.frame_index = 0
        self._last_frame = 0.0
        if frames_dir:
            frames_dir.mkdir(parents=True, exist_ok=True)

    def pump(self, seconds: float) -> None:
        end = time.time() + seconds
        while time.time() < end:
            self.app.processEvents()
            if self.frames_dir and time.time() - self._last_frame >= 1.0 / FPS:
                self._last_frame = time.time()
                self.grab_frame()
            time.sleep(0.008)
        self.app.processEvents()

    def grab_frame(self) -> None:
        assert self.frames_dir is not None
        self.frame_index += 1
        self.window.grab().save(str(self.frames_dir / f"f{self.frame_index:05d}.png"), "PNG")

    def still(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.window.grab().save(str(path), "PNG")
        print(f"  screenshot: {path}")

    def type_into(self, edit, text: str, chars_per_tick: int = 2, tick: float = 0.045) -> None:
        edit.setFocus(Qt.OtherFocusReason)
        edit.clear()
        self.pump(0.12)
        for index in range(chars_per_tick, len(text) + 1, chars_per_tick):
            edit.setText(text[:index])
            self.pump(tick)
        edit.setText(text)
        self.pump(tick)

    def wait_until(self, predicate, timeout: float = 30.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            self.app.processEvents()
            if predicate():
                self.pump(0.25)
                return True
            if self.frames_dir and time.time() - self._last_frame >= 1.0 / FPS:
                self._last_frame = time.time()
                self.grab_frame()
            time.sleep(0.02)
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media", default=".demo")
    parser.add_argument("--stills", default="docs/screenshots")
    parser.add_argument("--frames", default="")
    parser.add_argument("--video", default="")
    parser.add_argument("--no-typing", action="store_true")
    ns = parser.parse_args()

    media_dir = (ROOT / ns.media).resolve() if not os.path.isabs(ns.media) else Path(ns.media)
    video_file = media_dir / "wadden-zonsopkomst.mp4"
    audio_file = media_dir / "duinen-nachtegaal.mp3"
    for path in (video_file, audio_file):
        if not path.is_file():
            raise SystemExit(f"demo-media ontbreekt: {path} (eerst tools/make_demo_media.py)")

    app = QApplication(sys.argv)
    window = MainWindow(autoupdate=False)
    window.resize(1120, 860)
    window.show()
    app.processEvents()

    frames_dir = (ROOT / ns.frames).resolve() if ns.frames else None
    session = Session(window, app, frames_dir)
    stills_dir = (ROOT / ns.stills) if not os.path.isabs(ns.stills) else Path(ns.stills)

    session.pump(1.6)
    session.still(stills_dir / "01-startscherm.png")

    # Video openen.
    window.open_path(str(video_file))
    session.pump(1.8)
    session.still(stills_dir / "02-video-geopend.png")

    # Velden bewerken.
    values = {
        "title": "Zonsopkomst boven de Wadden (definitief)",
        "artist": "Werdens Media",
        "album": "Waddenreeks 2026",
        "genre": "Documentaire",
        "year": "2026",
        "comment": "definitief, klant, 4K master",
    }
    if not ns.no_typing:
        session.type_into(window.edits["title"], values["title"], 1, 0.055)
        session.type_into(window.edits["album"], values["album"], 1, 0.055)
        session.type_into(window.edits["comment"], values["comment"], 1, 0.055)
    else:
        window.set_values(values)
        session.pump(0.3)
    expected = {key: window.edits[key].text() for key in window.edits}
    session.pump(0.4)
    session.still(stills_dir / "03-metadata-bewerkt.png")

    # Opslaan (echte ffmpeg-schrijfactie, in een thread).
    window.save_metadata(save_as=False)
    session.pump(0.35)
    session.still(stills_dir / "04-opslaan-voortgang.png")
    ok = session.wait_until(lambda: window._worker is None, timeout=60)
    if not ok:
        raise SystemExit("opslaan kwam niet klaar")
    session.pump(0.6)
    session.still(stills_dir / "05-opgeslagen.png")

    # Controle: staan de tags echt in het bestand?
    info = core.probe(str(video_file))
    written = {key: info.tag(key) for key in core.FIELDS}
    print("  tags na opslaan:", written)
    if written.get("title") != expected["title"]:
        raise SystemExit(f"titel niet weggeschreven: {written.get('title')!r}")

    # Audio met cover-art openen.
    window.open_path(str(audio_file))
    session.pump(1.4)
    session.still(stills_dir / "06-audio-met-cover.png")

    # Terug naar de video, zodat de demo-video netjes eindigt.
    window.open_path(str(video_file))
    session.pump(1.0)
    session.still(stills_dir / "07-video-opnieuw.png")

    if frames_dir and ns.video:
        out = (ROOT / ns.video) if not os.path.isabs(ns.video) else Path(ns.video)
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            core.find_ffmpeg(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-framerate", str(FPS), "-i", str(frames_dir / "f%05d.png"),
            "-c:v", "libx264", "-preset", "slow", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out),
        ]
        subprocess.run(cmd, check=True)
        print(f"  video: {out} ({out.stat().st_size / 1024:.0f} kB, {session.frame_index} frames)")
    print(f"  frames: {session.frame_index}")
    return 0


if __name__ == "__main__":
    sys.exit(main())