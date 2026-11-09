"""Controleert met ffprobe/ffmpeg of de weggeschreven tags en streams kloppen.

Wordt aangeroepen door run-jvm-tests.sh:  verify_tags.py <bron-map> <tag-map>
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

EXPECTED = {
    "title": "Ça va — 日本語 (test)",
    "artist": "Tom Werdens",
    "album": "Waddenreeks 2026",
    "year": "2026",
    "comment": "definitief; klant, 4K",
}


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise SystemExit(f"ffprobe faalt op {path}: {out.stderr[-500:]}")
    return json.loads(out.stdout)


def main() -> int:
    source_dir, tag_dir = Path(sys.argv[1]), Path(sys.argv[2])
    failures = 0
    for tagged in sorted(tag_dir.iterdir()):
        original = source_dir / tagged.name
        info = probe(tagged)
        fmt = info.get("format") or {}
        tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
        streams = info.get("streams") or []
        kinds = [s.get("codec_type") for s in streams]

        print(f"\n{tagged.name}: {tags.get('title')!r} / {tags.get('artist')!r} "
              f"/ streams={kinds}")

        # 1. de tags moeten door ffprobe gezien worden (dus door elke speler)
        for key, expected in EXPECTED.items():
            actual = tags.get(key) or tags.get("date" if key == "year" else key) or ""
            if expected not in actual:
                print(f"  FAIL {key}: verwacht {expected!r}, kreeg {actual!r}")
                failures += 1
            if actual and actual[0] in ("\ufeff", "\u0000"):
                print(f"  FAIL {key}: begint met een BOM/nul-teken: {actual!r}")
                failures += 1
        genre = tags.get("genre", "")
        if "Ambient" not in genre and "Documentaire" not in genre:
            print(f"  FAIL genre: kreeg {genre!r}")
            failures += 1

        # 2. de duur mag niet veranderd zijn (er is niets opnieuw gecodeerd)
        before = float((probe(original).get("format") or {}).get("duration") or 0)
        after = float(fmt.get("duration") or 0)
        if abs(before - after) > max(0.15, before * 0.02):
            print(f"  FAIL duur: was {before:.3f}s, is {after:.3f}s")
            failures += 1

        # 3. het bestand moet nog echt afspeelbaar zijn: decodeer een frame
        if "video" in kinds:
            frame = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", "1",
                 "-i", str(tagged), "-frames:v", "1", "-f", "null", "-"],
                capture_output=True, text=True,
            )
            if frame.returncode != 0:
                print(f"  FAIL video niet decodeerbaar: {frame.stderr[-300:]}")
                failures += 1
            else:
                print("  video decodeert nog")
        audio = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(tagged),
             "-t", "1", "-f", "null", "-"],
            capture_output=True, text=True,
        )
        if audio.returncode != 0:
            print(f"  FAIL audio niet decodeerbaar: {audio.stderr[-300:]}")
            failures += 1

    print()
    if failures:
        print(f"VERIFICATIE MISLUKT: {failures} probleem(en)")
        return 1
    print("VERIFICATIE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())