"""Bijwerken via GitHub Releases.

De oude versie haalde een zip bij Google Drive en pakte die over de draaiende
applicatie heen; dat werkt op Windows niet (de exe is vergrendeld) en de URL
bevatte een spatie. Deze module haalt `version.json` + de zip op bij de laatste
release, controleert de sha256 en laat een klein hulpscript de bestanden
vervangen nadat de app is afgesloten.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

REPO = "Theberas04/media-metadata-editor"
MANIFEST_URL = f"https://github.com/{REPO}/releases/latest/download/version.json"
TIMEOUT = 12
USER_AGENT = "MediaMetadataEditor-updater"


@dataclass
class UpdateInfo:
    current: str
    latest: str = ""
    url: str = ""
    sha256: str = ""
    notes: str = ""
    error: str = ""

    @property
    def available(self) -> bool:
        return bool(self.url) and version_tuple(self.latest) > version_tuple(self.current)


def version_tuple(text: str) -> tuple[int, ...]:
    """'1.2.3' -> (1, 2, 3); onbruikbare delen worden 0."""
    parts: list[int] = []
    for chunk in str(text).strip().lstrip("vV").replace("-", ".").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def check_for_update(current: str, url: str = MANIFEST_URL) -> UpdateInfo:
    """Haalt het manifest op; geeft nooit een exception, wel .error."""
    info = UpdateInfo(current=current)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        info.error = f"Geen update-informatie gevonden (HTTP {exc.code})."
        return info
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        info.error = f"Kon de updateserver niet bereiken: {exc}"
        return info

    info.latest = str(payload.get("version", ""))
    info.url = str(payload.get("url", ""))
    info.sha256 = str(payload.get("sha256", "")).lower()
    info.notes = str(payload.get("notes", ""))
    if not info.latest or not info.url:
        info.error = "Update-informatie is onvolledig."
    return info


def download(
    info: UpdateInfo,
    dest: Path,
    on_progress: Optional[Callable[[float], None]] = None,
) -> Path:
    """Downloadt de update-zip en controleert de sha256."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(info.url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, open(dest, "wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            read += len(chunk)
            if on_progress and total:
                on_progress(min(0.999, read / total))
    if on_progress:
        on_progress(1.0)
    actual = digest.hexdigest()
    if info.sha256 and actual != info.sha256:
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            "De gedownloade update klopt niet (sha256 komt niet overeen). "
            "Er is niets vervangen."
        )
    return dest


_WINDOWS_HELPER = r"""@echo off
setlocal
set "PID_WAIT={pid}"
set "ZIP={zip}"
set "DEST={dest}"
set "EXE={exe}"
rem Wacht tot de applicatie echt afgesloten is.
:wait
tasklist /FI "PID eq %PID_WAIT%" 2>nul | find "%PID_WAIT%" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto wait
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%DEST%' -Force"
if errorlevel 1 (
  echo Bijwerken mislukt. Pak de nieuwe zip handmatig uit in:
  echo %DEST%
  pause
  exit /b 1
)
del /Q "%ZIP%" >nul 2>&1
start "" "%EXE%"
exit /b 0
"""


def apply_update_windows(zip_path: Path, install_dir: Path, exe_path: Path) -> Path:
    """Schrijft een .bat die na het afsluiten van de app de bestanden vervangt."""
    helper = install_dir / "bijwerken.bat"
    helper.write_text(
        _WINDOWS_HELPER.format(
            pid=os.getpid(),
            zip=str(zip_path),
            dest=str(install_dir),
            exe=str(exe_path),
        ),
        encoding="utf-8",
    )
    subprocess.Popen(
        ["cmd", "/c", str(helper)],
        cwd=str(install_dir),
        creationflags=0x00000008,  # DETACHED_PROCESS
        close_fds=True,
    )
    return helper


def apply_update_posix(zip_path: Path, install_dir: Path) -> None:
    """Zelfde idee, maar met een shell-script (ontwikkelgebruik)."""
    script = install_dir / "bijwerken.sh"
    script.write_text(
        "#!/bin/sh\n"
        f"while kill -0 {os.getpid()} 2>/dev/null; do sleep 1; done\n"
        f"cd '{install_dir}' && unzip -o '{zip_path}' >/dev/null && rm -f '{zip_path}'\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    subprocess.Popen([str(script)], start_new_session=True, close_fds=True)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dirs() -> tuple[Path, Path]:
    """(installatiemap, pad naar de exe) van de draaiende applicatie."""
    exe = Path(sys.executable).resolve()
    return exe.parent, exe