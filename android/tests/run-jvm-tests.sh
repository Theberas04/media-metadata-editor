#!/usr/bin/env bash
# Test de tag-lezers/schrijvers van de Android-app op de JVM, met echte mediabestanden.
#
#   bash android/tests/run-jvm-tests.sh
#
# Vereist: ffmpeg, ffprobe, java/javac (17+) en de mp3agic-jar (wordt gedownload
# als hij nog niet in .jvm-libs staat).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LIBS="$ROOT/.jvm-libs"
WORK="${TMPDIR:-/tmp}/mediameta-jvm-$$"
SRC="$WORK/src"
TAGS="$WORK/tags"
MP3AGIC="$LIBS/mp3agic-0.9.1.jar"

mkdir -p "$LIBS" "$SRC" "$TAGS"

if [ ! -f "$MP3AGIC" ]; then
  echo "== mp3agic downloaden =="
  curl -sSL -o "$MP3AGIC" "https://repo1.maven.org/maven2/com/mpatric/mp3agic/0.9.1/mp3agic-0.9.1.jar"
fi

echo "== testmedia maken =="
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "sine=frequency=440:duration=6" \
  -metadata title="Oud" -metadata artist="Oud" "$SRC/proef.mp3"
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc2=size=320x180:rate=15:duration=6" \
  -f lavfi -i "sine=frequency=440:duration=6" \
  -c:v libx264 -preset ultrafast -c:a aac -shortest "$SRC/proef-moov-achter.mp4"
ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc2=size=320x180:rate=15:duration=6" \
  -f lavfi -i "sine=frequency=440:duration=6" \
  -c:v libx264 -preset ultrafast -c:a aac -shortest -movflags +faststart \
  "$SRC/proef-faststart.mp4"
ffmpeg -hide_banner -loglevel error -y -f lavfi -i "sine=frequency=330:duration=5" \
  -c:a aac "$SRC/proef.m4a"
cp "$SRC"/* "$TAGS"/

echo "== compileren =="
rm -rf "$WORK/classes" && mkdir -p "$WORK/classes"
javac -encoding UTF-8 -nowarn -cp "$MP3AGIC" -d "$WORK/classes" \
  "$ROOT/android/app/src/main/java/nl/werdens/mediameta/Mp4Tags.java" \
  "$ROOT/android/app/src/main/java/nl/werdens/mediameta/Mp3Tags.java" \
  "$ROOT/android/app/src/main/java/nl/werdens/mediameta/MediaTags.java" \
  "$HERE/jvm/TagRoundTripTest.java"

echo "== test uitvoeren =="
java -cp "$WORK/classes:$MP3AGIC" TagRoundTripTest "$TAGS"

echo "== onafhankelijke controle met ffprobe =="
python3 "$HERE/verify_tags.py" "$SRC" "$TAGS"

echo "== klaar =="
rm -rf "$WORK"