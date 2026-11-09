"""Startpunt van de applicatie."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    if sys.platform == "win32":
        # Zorgt dat de taakbalk het eigen icoon gebruikt in plaats van dat van python.
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Werdens.MediaMetadataEditor")
        except Exception:
            pass

    if "--selftest" in sys.argv:
        # Geen modale vensters in een run zonder scherm; die wachten op een klik.
        os.environ.setdefault("MEDIA_META_HEADLESS", "1")
        return selftest()

    from mediameta.ui import run

    return run([arg for arg in sys.argv if arg != "--selftest"])


def selftest() -> int:
    """Controleert de gebouwde app: ffmpeg, Qt, UI, metadata lezen én schrijven.

    De Windows-build is een --windowed exe zonder console, dus de uitslag gaat
    naar een JSON-bestand (--out) én naar stdout als die er is. Elke stap wordt
    direct weggeschreven, zodat een crash de laatste geslaagde stap achterlaat.
    """
    out_path = None
    if "--out" in sys.argv:
        index = sys.argv.index("--out")
        if index + 1 < len(sys.argv):
            out_path = Path(sys.argv[index + 1])
    lines: list[str] = []

    def log(message: str) -> None:
        lines.append(message)
        if sys.stdout is not None:
            try:
                print(message, flush=True)
            except Exception:
                pass
        if out_path:
            try:
                out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except OSError:
                pass

    log("selftest: start")
    log(f"selftest: python {sys.version.split()[0]}, frozen={bool(getattr(sys, 'frozen', False))}")
    log(f"selftest: QT_QPA_PLATFORM={os.environ.get('QT_QPA_PLATFORM', '(niet gezet)')}")

    imports_only = "--imports-only" in sys.argv

    # Stap voor stap importeren: dit is de plek waar een verpakte Qt-app het
    # vaakst stil crasht, en dan wil je weten welke module het was.
    try:
        from PyQt5.QtCore import QT_VERSION_STR  # noqa: F401

        log(f"selftest: import QtCore ok (Qt {QT_VERSION_STR})")
        from PyQt5.QtWidgets import QApplication  # noqa: F401

        log("selftest: import QtWidgets ok")
        from PyQt5.QtMultimedia import QMediaPlayer  # noqa: F401

        log("selftest: import QtMultimedia ok")
        from PyQt5.QtMultimediaWidgets import QVideoWidget  # noqa: F401

        log("selftest: import QtMultimediaWidgets ok")
    except Exception as exc:  # noqa: BLE001
        log(f"selftest: IMPORTFOUT {exc!r}")
        return 1

    if imports_only:
        log('selftest: {"selftest": "OK", "mode": "imports-only"}')
        return 0

    from mediameta import core
    from mediameta.ui import MainWindow
    from mediameta.version import VERSION

    log("selftest: mediameta-modules geladen")

    log(f"selftest: versie {VERSION}")
    log(f"selftest: ffmpeg  = {core.find_ffmpeg()}")
    log(f"selftest: ffprobe = {core.find_ffprobe() or '(niet meegeleverd, ffmpeg-terugvalweg)'}")

    workdir = Path(tempfile.mkdtemp(prefix="mm-selftest-"))
    sample = workdir / "selftest.mp3"
    subprocess.run(
        [core.find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-metadata", "title=Zelftest", "-metadata", "artist=Hermes",
         str(sample)],
        check=True, capture_output=True,
    )

    app = QApplication([])  # noqa: F841 - houdt de UI in leven
    window = MainWindow(autoupdate=False)
    window.resize(1000, 800)
    window.show()
    window.open_path(str(sample))
    app.processEvents()

    assert window.edits["title"].text() == "Zelftest", "metadata niet ingelezen"
    assert window.edits["artist"].text() == "Hermes", "artiest niet ingelezen"
    log("selftest: UI gebouwd en metadata gelezen")

    window.edits["title"].setText("Zelftest na opslaan")
    window.edits["album"].setText("Controle")
    window.save_metadata(save_as=False)
    deadline = time.time() + 90
    while window._worker is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    if window._worker is not None:
        # Een lopende QThread houdt het proces bij het afsluiten tegen; daarom
        # hier hard stoppen met een duidelijke melding in plaats van hangen.
        log("selftest: TIMEOUT - opslaan kwam niet binnen 90 seconden klaar")
        os._exit(3)

    info = core.probe(str(sample))
    assert info.tag("title") == "Zelftest na opslaan", f"titel niet weggeschreven: {info.tag('title')!r}"
    assert info.tag("album") == "Controle", f"album niet weggeschreven: {info.tag('album')!r}"
    log("selftest: metadata weggeschreven en teruggelezen")

    poster = core.poster_image(str(sample), workdir / "poster.png")
    log(f"selftest: poster = {'ja' if poster else 'geen (audiobestand zonder cover)'}")

    report = {
        "selftest": "OK",
        "version": VERSION,
        "ffprobe": bool(core.find_ffprobe()),
        "frozen": bool(getattr(sys, "frozen", False)),
        "log": lines,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    log(f"selftest: {json.dumps({k: v for k, v in report.items() if k != 'log'})}")
    if out_path:
        out_path.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())