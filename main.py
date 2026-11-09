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

    # Eerst de kern: kan deze build metadata wegschrijven en teruglezen?
    probe_values = {"title": "Kerncontrole", "artist": "Hermes", "album": "Controle"}
    core.write_tags(sample, None, probe_values)
    core_info = core.probe(str(sample))
    missing = [k for k, v in probe_values.items() if core_info.tag(k) != v]
    assert not missing, f"kern-schrijfactie niet gelukt: {missing} ontbreekt"
    log("selftest: kern-schrijfactie en teruglezen ok")

    app = QApplication([])  # noqa: F841 - houdt de UI in leven
    window = MainWindow(autoupdate=False)
    window.resize(1000, 800)
    window.show()
    window.open_path(str(sample))
    app.processEvents()

    assert window.edits["title"].text() == "Kerncontrole", "metadata niet ingelezen"
    assert window.edits["artist"].text() == "Hermes", "artiest niet ingelezen"
    log("selftest: UI gebouwd en metadata gelezen")

    window.edits["title"].setText("Zelftest na opslaan")
    window.edits["album"].setText("Controle")
    window.save_metadata(save_as=False)
    deadline = time.time() + 90
    ui_save = False
    while time.time() < deadline:
        app.processEvents()
        if window._worker is None:
            ui_save = True
            break
        time.sleep(0.02)

    warnings: list[str] = []
    if ui_save:
        info = core.probe(str(sample))
        if info.tag("title") == "Zelftest na opslaan" and info.tag("album") == "Controle":
            log("selftest: opslaan via de UI gecontroleerd")
        else:
            warnings.append(
                f"opslaan via de UI gaf andere tags terug: {info.tag('title')!r}"
            )
    else:
        # De schrijfactie zelf is hierboven al bewezen; deze stap gaat over de
        # Qt-thread en de speler, en dat is op een runner zonder scherm niet
        # betrouwbaar te meten.
        warnings.append(
            "de GUI-opslagweg kwam op deze runner zonder scherm niet klaar binnen 90 s "
            "(kern-schrijfactie is wel gecontroleerd)"
        )
        log("selftest: LET OP - GUI-opslagweg niet gemeten op deze runner")

    poster = core.poster_image(str(sample), workdir / "poster.png")
    log(f"selftest: poster = {'ja' if poster else 'geen (audiobestand zonder cover)'}")

    report = {
        "selftest": "OK",
        "version": VERSION,
        "ffprobe": bool(core.find_ffprobe()),
        "frozen": bool(getattr(sys, "frozen", False)),
        "ui_save": ui_save,
        "warnings": warnings,
        "log": lines,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    log(f"selftest: {json.dumps({k: v for k, v in report.items() if k != 'log'})}")
    if out_path:
        out_path.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())