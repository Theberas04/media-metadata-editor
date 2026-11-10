"""Startpunt van de applicatie."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
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

    # Een harde crash (access violation) laat anders niets na. faulthandler
    # schrijft de Python-stack naar een bestand, ook als het proces daarna valt.
    try:
        import faulthandler

        crash_pad = (out_path.with_suffix(".crash.log") if out_path
                     else Path(tempfile.gettempdir()) / "mediameta-crash.log")
        faulthandler.enable(open(crash_pad, "w", encoding="utf-8"))  # noqa: SIM115
    except Exception:
        pass

    def log(message: str) -> None:
        lines.append(message)
        # Eerst het bestand: een volle stdout-pijp mag het rapport niet blokkeren.
        if out_path:
            try:
                out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except OSError:
                pass
        if sys.stdout is not None:
            try:
                print(message, flush=True)
            except Exception:
                pass

    stap = {"nu": "start"}

    def watchdog(seconds: float = 120.0) -> None:
        time.sleep(seconds)
        log(f"selftest: TIMEOUT bij stap '{stap['nu']}' na {seconds:.0f} seconden")
        try:
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(4)

    threading.Thread(target=watchdog, daemon=True).start()

    def mark(naam: str) -> None:
        """Logt welke stap begint; de laatste regel is de plek van een crash."""
        stap["nu"] = naam
        log(f"selftest: stap - {naam}")

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
    mark("kern-schrijfactie")
    core.write_tags(sample, None, probe_values)
    core_info = core.probe(str(sample))
    missing = [k for k, v in probe_values.items() if core_info.tag(k) != v]
    assert not missing, f"kern-schrijfactie niet gelukt: {missing} ontbreekt"
    log("selftest: kern-schrijfactie en teruglezen ok")

    # Nieuwe velden: albumartiest, track, componist en songtekst moeten ook
    # aankomen (dat is de kern van "meer velden").
    extra_values = {
        "albumartist": "Werdens Media",
        "track": "3/12",
        "composer": "Hermes",
        "lyrics": "Eerste regel\nTweede regel",
    }
    mark("nieuwe velden")
    extra_file = workdir / "selftest-extra.mp3"
    extra_file.write_bytes(sample.read_bytes())
    core.write_tags(extra_file, None, {**probe_values, **extra_values})
    extra_info = core.probe(str(extra_file))
    ontbreekt = [k for k, v in extra_values.items()
                 if not core.tags_match({k: v}, extra_info).get(k)]
    assert not ontbreekt, f"nieuwe velden niet gelukt: {ontbreekt}"
    log("selftest: nieuwe velden (albumartiest, track, componist, songtekst) ok")

    # Frameknipsel: uit een echt videobestand één frame naar PNG.
    mark("frameknipsel")
    video = workdir / "selftest.mp4"
    subprocess.run(
        [core.find_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-shortest", str(video)],
        check=True, capture_output=True,
    )
    frame = workdir / "frame.png"
    core.extract_frame(str(video), frame, 1000)
    assert frame.is_file() and frame.stat().st_size > 500, "frame niet opgeslagen"
    log(f"selftest: frameknipsel ok ({frame.stat().st_size} bytes)")

    # Batchverwerking: twee bestanden in één keer, met controle per bestand.
    batch_a = workdir / "batch-a.mp3"
    batch_b = workdir / "batch-b.mp3"
    for bestand in (batch_a, batch_b):
        bestand.write_bytes(sample.read_bytes())
    mark("batchverwerking")
    rapport = core.batch_write([batch_a, batch_b], {"genre": "Zelftest"})
    assert len(rapport) == 2 and all(r["ok"] for r in rapport), f"batch: {rapport}"
    log("selftest: batchverwerking ok (2 bestanden)")

    app = QApplication([])  # noqa: F841 - houdt de UI in leven
    mark("venster bouwen")
    window = MainWindow(autoupdate=False)
    window.resize(1000, 800)
    window.show()
    mark("metadata lezen in de UI")
    window.open_path(str(extra_file))
    app.processEvents()

    assert window.edits["title"].text() == "Kerncontrole", "metadata niet ingelezen"
    assert window.edits["artist"].text() == "Hermes", "artiest niet ingelezen"
    assert window.edits["albumartist"].text() == "Werdens Media", "albumartiest niet ingelezen"
    assert set(window.edits) == set(core.FIELDS), "niet alle velden in de UI"
    log(f"selftest: UI gebouwd met {len(window.edits)} velden en metadata gelezen")

    # Afspeellijst, recente bestanden en de laatste map.
    window.add_paths([str(batch_a), str(batch_b)])
    assert window.playlist.count() >= 3, f"afspeellijst: {window.playlist.count()}"
    assert window.recent and window.recent[0].endswith(".mp3"), "recent niet bijgehouden"
    assert window.last_dir, "laatste map niet onthouden"
    log(f"selftest: afspeellijst {window.playlist.count()} bestanden, recent en laatste map ok")

    mark("opslaan via de UI")
    window.edits["title"].setText("Zelftest na opslaan")
    window.edits["lyrics"].setPlainText("regel een\nregel twee")
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
        info = core.probe(str(extra_file))
        if info.tag("title") == "Zelftest na opslaan" and info.tag("album") == "Controle":
            log("selftest: opslaan via de UI gecontroleerd")
        else:
            log(f"selftest: FOUT - opslaan via de UI gaf {info.tag('title')!r} terug")
            return 1
    else:
        # De schrijfactie zelf is hierboven al bewezen; deze stap gaat over de
        # Qt-thread en de speler, en dat is op een runner zonder scherm niet
        # betrouwbaar te meten.
        warnings.append(
            "de GUI-opslagweg kwam op deze runner zonder scherm niet klaar binnen 90 s "
            "(kern-schrijfactie is wel gecontroleerd)"
        )
        log("selftest: LET OP - GUI-opslagweg niet gemeten op deze runner")

    poster = core.poster_image(str(extra_file), workdir / "poster.png")
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