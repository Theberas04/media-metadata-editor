"""Kern: media uitlezen en metadata wegschrijven met ffmpeg/ffprobe.

Deze module heeft geen Qt nodig en is daarom los te testen (zie tests/test_core.py).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

AUDIO_EXTS = (
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".oga", ".opus",
    ".wma", ".m4a", ".aiff", ".aif", ".alac",
)
VIDEO_EXTS = (
    ".mp4", ".m4v", ".avi", ".mov", ".mkv", ".mxf",
    ".webm", ".wmv", ".mpg", ".mpeg", ".ts", ".flv",
)
SUPPORTED_EXTS = tuple(sorted(set(AUDIO_EXTS) | set(VIDEO_EXTS)))

# UI-veld -> ffmpeg-tagnaam.  'jaar' gaat naar 'date', dat is de tag die
# MP4/MKV/MP3 (TDRC) allemaal begrijpen; ffmpeg leest hem ook weer als jaar.
FIELDS = (
    "title", "artist", "albumartist", "album", "track", "disc",
    "genre", "year", "composer", "comment", "lyrics",
)
FIELD_TAGS = {
    "title": "title",
    "artist": "artist",
    "albumartist": "album_artist",
    "album": "album",
    "track": "track",
    "disc": "disc",
    "genre": "genre",
    "year": "date",
    "composer": "composer",
    "comment": "comment",
    "lyrics": "lyrics",
}

# Nederlandse labels voor meldingen en de batchrapportage.
FIELD_LABELS = {
    "title": "Titel",
    "artist": "Artiest",
    "albumartist": "Albumartiest",
    "album": "Album",
    "track": "Tracknummer",
    "disc": "Schijf",
    "genre": "Genre",
    "year": "Jaar",
    "composer": "Componist",
    "comment": "Commentaar",
    "lyrics": "Songtekst",
}

# Containers waar +faststart zin heeft (moov vooraan, sneller starten).
_FASTSTART_EXTS = (".mp4", ".m4v", ".m4a", ".mov", ".3gp")

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Hoe lang mag het wegschrijven duren voordat we ffmpeg afbreken?
WRITE_TIMEOUT_S = 3600

# Eén schrijfactie tegelijk: twee ffmpeg-processen op hetzelfde bestand is vragen
# om problemen.
_write_lock = threading.Lock()


# Optionele tracer: de self-test hangt hier een logger aan, zodat in CI te zien
# is bij welke aanroep een hang ontstaat. In normaal gebruik staat hij uit.
TRACE: Optional[Callable[[str], None]] = None


def _trace(message: str) -> None:
    if TRACE is None:
        return
    try:
        TRACE(f"core: {message}")
    except Exception:  # noqa: BLE001 - traceren mag nooit storen
        pass


class FFmpegMissing(RuntimeError):
    """ffmpeg is niet gevonden; de app kan dan niets met metadata."""


class MediaError(RuntimeError):
    """Het mediabestand kon niet gelezen of geschreven worden."""


@dataclass
class MediaInfo:
    path: str
    duration_ms: int = 0
    size_bytes: int = 0
    format_name: str = ""
    bit_rate: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    width: int = 0
    height: int = 0
    tags: dict = field(default_factory=dict)
    probe_source: str = ""

    @property
    def is_video(self) -> bool:
        return bool(self.video_codec) or self.height > 0

    @property
    def kind(self) -> str:
        return "Video" if self.is_video else "Audio"

    @property
    def resolution(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return ""

    def tag(self, name: str) -> str:
        """Tag opvragen met de ffmpeg-naam, hoofdletterongevoelig."""
        wanted = FIELD_TAGS.get(name, name).lower()
        for key, value in self.tags.items():
            if key.lower() == wanted:
                return str(value)
        return ""

    def fields(self) -> dict:
        """Alle UI-velden als platte dict."""
        return {name: self.tag(name) for name in FIELDS}

    def summary(self) -> str:
        bits = [self.kind]
        if self.resolution:
            bits.append(self.resolution)
        codec = self.video_codec or self.audio_codec
        if codec:
            bits.append(codec)
        if self.duration_ms:
            bits.append(format_duration(self.duration_ms))
        if self.size_bytes:
            bits.append(human_size(self.size_bytes))
        return "  ·  ".join(bits)


# --------------------------------------------------------------------------- #
# Hulpmiddelen zoeken
# --------------------------------------------------------------------------- #

def _bundled_dirs() -> list[Path]:
    """Mappen waar ffmpeg/ffprobe kan staan die bij de app horen."""
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))
    here = Path(__file__).resolve().parent
    dirs += [here.parent, here.parent / "vendor", here.parent / "vendor" / "ffmpeg", here / "bin"]
    # imageio-ffmpeg levert een ffmpeg-binary mee in de wheel (geen ffprobe).
    try:
        import imageio_ffmpeg  # type: ignore

        dirs.append(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
    except Exception:
        pass
    return dirs


def _find_tool(name: str) -> Optional[str]:
    env = os.environ.get(f"MEDIA_META_{name.upper()}")
    if env and Path(env).is_file():
        return str(Path(env))
    exe = f"{name}.exe" if sys.platform == "win32" else name
    for directory in _bundled_dirs():
        candidate = directory / exe
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    if sys.platform == "win32":
        for base in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"):
            candidate = Path(base) / exe
            if candidate.is_file():
                return str(candidate)
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg  # type: ignore

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return None


_ffmpeg_cache: dict[str, Optional[str]] = {}


def find_ffmpeg() -> str:
    """Pad naar ffmpeg; raises FFmpegMissing als hij nergens staat."""
    if "ffmpeg" not in _ffmpeg_cache:
        _ffmpeg_cache["ffmpeg"] = _find_tool("ffmpeg")
    path = _ffmpeg_cache["ffmpeg"]
    if not path:
        raise FFmpegMissing(
            "ffmpeg is niet gevonden. Installeer ffmpeg en zet hem in je PATH, "
            "of plaats ffmpeg.exe naast de applicatie."
        )
    return path


def find_ffprobe() -> Optional[str]:
    """Pad naar ffprobe of None (dan valt de app terug op ffmpeg)."""
    if "ffprobe" not in _ffmpeg_cache:
        _ffmpeg_cache["ffprobe"] = _find_tool("ffprobe")
    return _ffmpeg_cache["ffprobe"]


def reset_tool_cache() -> None:
    _ffmpeg_cache.clear()


def is_supported(path: str | os.PathLike) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTS


# --------------------------------------------------------------------------- #
# Weergave-hulpjes
# --------------------------------------------------------------------------- #

def format_duration(ms: int) -> str:
    """Milliseconden -> mm:ss, of uu:mm:ss bij een uur of langer."""
    if ms is None or ms < 0:
        ms = 0
    total = int(ms) // 1000
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def human_size(num_bytes: int) -> str:
    value = float(num_bytes or 0)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}".replace(".0 ", " ")
        value /= 1024.0
    return f"{value:.1f} TB"


def _ffmetadata_unescape(value: str) -> str:
    """Keert de escaping van het ffmetadata-formaat terug."""
    out: list[str] = []
    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value):
            out.append(value[i + 1])
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def parse_ffmetadata(text: str) -> dict:
    """Parseert de uitvoer van `ffmpeg -f ffmetadata -` naar een tag-dict."""
    tags: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        tags[key.strip().lower()] = _ffmetadata_unescape(value.strip())
    return tags


# --------------------------------------------------------------------------- #
# Uitlezen
# --------------------------------------------------------------------------- #

def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise FFmpegMissing(str(exc)) from exc


def probe(path: str | os.PathLike) -> MediaInfo:
    """Leest duur, formaat, streams en tags van een mediabestand."""
    path = Path(path)
    if not path.is_file():
        raise MediaError(f"Bestand niet gevonden: {path}")
    info = MediaInfo(path=str(path), size_bytes=path.stat().st_size)

    ffprobe = find_ffprobe()
    _trace(f"probe {path.name} via {'ffprobe' if ffprobe else 'ffmpeg-terugvalweg'}")
    if ffprobe:
        proc = _run([
            ffprobe, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ])
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                data = json.loads(proc.stdout)
            except json.JSONDecodeError:
                data = None
            if data:
                _fill_from_ffprobe(info, data)
                info.probe_source = "ffprobe"
                return info

    _fill_from_ffmpeg(info, path)
    info.probe_source = "ffmpeg"
    _trace(f"probe {path.name} klaar (ffmpeg-terugvalweg)")
    return info


def _fill_from_ffprobe(info: MediaInfo, data: dict) -> None:
    fmt = data.get("format") or {}
    info.format_name = fmt.get("format_name", "")
    info.bit_rate = int(float(fmt.get("bit_rate") or 0))
    duration = fmt.get("duration") or 0
    try:
        info.duration_ms = int(float(duration) * 1000)
    except (TypeError, ValueError):
        info.duration_ms = 0
    info.tags = {str(k).lower(): str(v) for k, v in (fmt.get("tags") or {}).items()}

    for stream in data.get("streams") or []:
        kind = stream.get("codec_type")
        if kind == "video" and not info.video_codec:
            # mjpeg in een mp3 is cover-art: dat is geen echte videostream.
            if (stream.get("disposition") or {}).get("attached_pic"):
                continue
            info.video_codec = stream.get("codec_name", "")
            info.width = int(stream.get("width") or 0)
            info.height = int(stream.get("height") or 0)
            if not info.duration_ms:
                try:
                    info.duration_ms = int(float(stream.get("duration") or 0) * 1000)
                except (TypeError, ValueError):
                    pass
        elif kind == "audio" and not info.audio_codec:
            info.audio_codec = stream.get("codec_name", "")


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2})\.(\d{1,3})")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?: Video: (\w+).*?(\d{2,5})x(\d{2,5})")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio: (\w+)")


def _fill_from_ffmpeg(info: MediaInfo, path: Path) -> None:
    """Terugvalpad zonder ffprobe: ffmpeg levert de tags en het info-blok."""
    ffmpeg = find_ffmpeg()

    _trace("ffmpeg-tags lezen")
    tag_proc = _run([ffmpeg, "-hide_banner", "-nostdin", "-v", "quiet",
                     "-i", str(path), "-f", "ffmetadata", "-"])
    _trace("ffmpeg-tags gelezen")
    if tag_proc.returncode == 0 and tag_proc.stdout:
        info.tags = parse_ffmetadata(tag_proc.stdout)

    _trace("ffmpeg-info lezen")
    info_proc = _run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path)])
    _trace("ffmpeg-info gelezen")
    stderr = info_proc.stderr or ""

    match = _DURATION_RE.search(stderr)
    if match:
        hours, minutes, seconds, frac = match.groups()
        info.duration_ms = (
            int(hours) * 3600000 + int(minutes) * 60000
            + int(seconds) * 1000 + int(frac.ljust(3, "0"))
        )
    video = _VIDEO_RE.search(stderr)
    if video:
        info.video_codec, width, height = video.group(1), int(video.group(2)), int(video.group(3))
        info.width, info.height = width, height
    audio = _AUDIO_RE.search(stderr)
    if audio:
        info.audio_codec = audio.group(1)

    fmt_match = re.search(r"Input #0,\s*([^,]+),", stderr)
    if fmt_match:
        info.format_name = fmt_match.group(1).strip()
    if not info.duration_ms:
        raise MediaError(
            "Kon dit bestand niet lezen met ffmpeg. Is het een geldig mediabestand?"
        )


# --------------------------------------------------------------------------- #
# Wegschrijven
# --------------------------------------------------------------------------- #

def _metadata_args(values: dict) -> list[str]:
    args: list[str] = []
    for name in FIELDS:
        tag = FIELD_TAGS[name]
        value = (values.get(name) or "").replace("\x00", "").strip()
        args += ["-metadata", f"{tag}={value}"]
    return args


def write_tags(
    source: str | os.PathLike,
    dest: Optional[str | os.PathLike] = None,
    values: Optional[dict] = None,
    on_progress: Optional[Callable[[float], None]] = None,
) -> MediaInfo:
    """Schrijft metadata weg zonder opnieuw te encoderen (-c copy).

    `dest` None of gelijk aan `source` betekent: het bronbestand vervangen.
    Er wordt altijd eerst naar een tijdelijk bestand geschreven, zodat een
    mislukte schrijfactie het origineel niet beschadigt.

    De voortgang komt uit een voortgangsbestand in plaats van uit `pipe:1`.
    Een pijp die niet leegloopt laat ffmpeg (en dus de app) op Windows
    oneindig wachten; een bestand kan dat niet. De foutuitvoer wordt door een
    aparte thread leeggemaakt om dezelfde reden.
    """
    source = Path(source)
    values = values or {}
    target = Path(dest) if dest else source
    if not source.is_file():
        raise MediaError(f"Bestand niet gevonden: {source}")

    with _write_lock:
        return _write_tags(source, target, values, on_progress)


def _write_tags(
    source: Path,
    target: Path,
    values: dict,
    on_progress: Optional[Callable[[float], None]],
) -> MediaInfo:
    ffmpeg = find_ffmpeg()
    _trace(f"schrijven naar {target.name}: eerst lezen")
    info = probe(source)
    duration_ms = info.duration_ms or 0
    _trace(f"schrijven naar {target.name}: ffmpeg starten")

    in_place = target.resolve() == source.resolve()
    suffix = target.suffix or source.suffix
    tmp = target.with_name(f"{target.stem}.mmtmp{suffix}")
    progress_file = tmp.with_name(tmp.name + ".progress")
    if not in_place:
        target.parent.mkdir(parents=True, exist_ok=True)
    tmp.unlink(missing_ok=True)
    progress_file.unlink(missing_ok=True)

    args = [
        ffmpeg, "-hide_banner", "-nostdin", "-y",
        "-loglevel", "error",
        "-i", str(source),
        "-map", "0", "-map_metadata", "0", "-c", "copy",
        *_metadata_args(values),
    ]
    if suffix.lower() in _FASTSTART_EXTS:
        args += ["-movflags", "+faststart"]
    args += ["-progress", str(progress_file), "-nostats", str(tmp)]

    started = time.time()
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        creationflags=_CREATE_NO_WINDOW,
    )
    _trace(f"ffmpeg gestart (pid {proc.pid})")
    stderr_chunks: list[str] = []

    def drain_stderr() -> None:
        try:
            if proc.stderr is not None:
                stderr_chunks.append(proc.stderr.read() or "")
        except Exception:  # noqa: BLE001 - de lezer mag nooit de app laten vallen
            pass

    reader = threading.Thread(target=drain_stderr, daemon=True)
    reader.start()

    deadline = started + WRITE_TIMEOUT_S
    code: Optional[int] = None
    try:
        while True:
            code = proc.poll()
            if code is not None:
                break
            if time.time() > deadline:
                proc.kill()
                proc.wait()
                raise MediaError(
                    f"ffmpeg deed er langer dan {WRITE_TIMEOUT_S // 60} minuten over "
                    "en is afgebroken. Het originele bestand is niet aangepast."
                )
            if on_progress and duration_ms:
                _report_progress(progress_file, duration_ms, on_progress)
            wacht = int(time.time() - started)
            if wacht and wacht % 15 == 0:
                _trace(f"ffmpeg draait al {wacht}s")
            time.sleep(0.1)
    except BaseException:
        tmp.unlink(missing_ok=True)
        progress_file.unlink(missing_ok=True)
        raise
    finally:
        reader.join(timeout=2)

    stderr = "".join(stderr_chunks)
    progress_file.unlink(missing_ok=True)
    if code != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        tail = (stderr or "").strip().splitlines()[-6:]
        raise MediaError("ffmpeg kon het bestand niet wegschrijven:\n" + "\n".join(tail))

    _trace("ffmpeg klaar, bestand vervangen")
    _replace_with_retry(tmp, target)
    if on_progress:
        on_progress(1.0)
    elapsed = time.time() - started

    result = probe(target)
    result.tags["_elapsed_s"] = f"{elapsed:.2f}"
    _trace(f"schrijven naar {target.name} klaar in {elapsed:.1f}s")
    return result


def _replace_with_retry(tmp: Path, target: Path, attempts: int = 6) -> None:
    """Vervangt het doelbestand, met herhaalpogingen.

    Windows staat het vervangen soms net niet toe omdat een ander programma
    (of onze eigen speler) het bestand nog heel even open heeft. Een paar keer
    opnieuw proberen is genoeg; blijft het misgaan, dan zeggen we het eerlijk.
    """
    for attempt in range(attempts):
        try:
            os.replace(tmp, target)
            return
        except PermissionError as exc:
            if attempt == attempts - 1:
                tmp.unlink(missing_ok=True)
                raise MediaError(
                    "Het bestand kon niet vervangen worden omdat het nog in gebruik is "
                    f"({target.name}). Sluit het bestand in andere programma's en probeer opnieuw."
                ) from exc
            time.sleep(0.35)


def _report_progress(
    progress_file: Path,
    duration_ms: int,
    on_progress: Callable[[float], None],
) -> None:
    """Leest het laatste out_time uit het voortgangsbestand van ffmpeg."""
    try:
        text = progress_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    stamp = None
    for line in text.splitlines():
        if line.startswith("out_time="):
            stamp = line.split("=", 1)[1]
    if not stamp:
        return
    seconds = _parse_time(stamp)
    if seconds is None:
        return
    on_progress(max(0.0, min(0.999, (seconds * 1000.0) / duration_ms)))


def _parse_time(stamp: str) -> Optional[float]:
    match = re.match(r"(\d+):(\d{2}):(\d{2})\.(\d+)", stamp)
    if not match:
        return None
    hours, minutes, seconds, frac = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + float("0." + frac)


def tags_match(expected: dict, info: MediaInfo) -> dict:
    """Welke van de opgegeven velden staan goed in het weggeschreven bestand?"""
    result: dict[str, bool] = {}
    for name in FIELDS:
        if name not in expected:
            continue
        want = (expected.get(name) or "").strip()
        got = info.tag(name).strip()
        if not want:
            result[name] = got == ""
        else:
            result[name] = got.lower() == want.lower() or want.lower() in got.lower()
    return result


def poster_image(
    source: str | os.PathLike,
    target: str | os.PathLike,
    position_ms: Optional[int] = None,
) -> Optional[str]:
    """Pakt één frame uit een mediabestand als preview-afbeelding (PNG).

    Bij audio met cover-art werkt `-ss` niet (de zoekactie slaat de
    afbeelding over), dus dan proberen we het zonder seek.
    """
    source, target = Path(source), Path(target)
    try:
        info = probe(source)
    except (MediaError, FFmpegMissing):
        info = MediaInfo(path=str(source))
    ffmpeg = find_ffmpeg()

    if info.is_video:
        if position_ms is None:
            position_ms = min(1500, max(0, (info.duration_ms or 0) // 10))
        attempts: list[Optional[float]] = [position_ms / 1000.0, 0.0]
    else:
        attempts = [None, 0.0]

    for attempt in attempts:
        args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
        if attempt is not None:
            args += ["-ss", f"{max(0.0, attempt):.3f}"]
        args += [
            "-i", str(source), "-frames:v", "1",
            "-vf", "scale='min(960,iw)':-2", str(target),
        ]
        proc = _run(args, timeout=120)
        if proc.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return str(target)
    return None

def extract_frame(
    source: str | os.PathLike,
    target: str | os.PathLike,
    position_ms: int = 0,
) -> str:
    """Pakt precies één frame op het opgegeven tijdstip als afbeelding.

    Werkt voor PNG en JPG; bij audio zonder videospoor is er niets te pakken
    en zeggen we dat eerlijk.
    """
    source, target = Path(source), Path(target)
    if not source.is_file():
        raise MediaError(f"Bestand niet gevonden: {source}")
    info = probe(source)
    if not info.is_video:
        raise MediaError(
            "Dit bestand heeft geen videospoor, dus er is geen frame om op te slaan."
        )
    ffmpeg = find_ffmpeg()
    target.parent.mkdir(parents=True, exist_ok=True)
    limit = max(0, (info.duration_ms or 0) - 1)
    seconds = max(0.0, min(float(position_ms), float(limit)) / 1000.0)
    args = [
        ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
        "-ss", f"{seconds:.3f}", "-i", str(source),
        "-frames:v", "1", "-an",
    ]
    if target.suffix.lower() in (".jpg", ".jpeg"):
        args += ["-q:v", "2"]
    args.append(str(target))
    proc = _run(args, timeout=180)
    if proc.returncode != 0 or not target.exists() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        tail = (proc.stderr or "").strip().splitlines()[-4:]
        raise MediaError("Kon geen frame opslaan:\n" + "\n".join(tail))
    return str(target)


def batch_write(
    files: list[str | os.PathLike],
    overrides: dict,
    on_progress: Optional[Callable[[float], None]] = None,
) -> list[dict]:
    """Zet dezelfde wijzigingen op een reeks bestanden.

    `overrides` bevat alleen de velden die aangepast moeten worden; velden die
    er niet in staan blijven zoals ze zijn. Een lege waarde wist het veld.
    Elk bestand wordt na het schrijven teruggelezen en gecontroleerd, en het
    resultaat per bestand komt terug in de lijst.
    """
    results: list[dict] = []
    total = len(files) or 1
    for index, item in enumerate(files):
        path = Path(item)
        entry = {"path": str(path), "name": path.name, "ok": False, "message": ""}
        try:
            info = probe(path)
            values = info.fields()
            values.update({k: v for k, v in overrides.items() if k in FIELDS})
            written = write_tags(path, None, values)
            matches = tags_match({k: values[k] for k in overrides}, written)
            missing = [FIELD_LABELS.get(k, k) for k, ok in matches.items() if not ok]
            if missing:
                entry["ok"] = False
                entry["message"] = (
                    "niet overgenomen door het bestandsformaat: " + ", ".join(missing)
                )
            else:
                entry["ok"] = True
                entry["message"] = "bijgewerkt"
        except (MediaError, FFmpegMissing) as exc:
            entry["message"] = str(exc).splitlines()[0]
        results.append(entry)
        if on_progress:
            on_progress((index + 1) / total)
    return results
