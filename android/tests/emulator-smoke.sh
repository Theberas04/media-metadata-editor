#!/usr/bin/env bash
# Installeert de APK op een draaiende emulator, start de app, controleert dat hij
# echt in beeld staat en maakt screenshots. Wordt vanuit CI aangeroepen.
#
#   bash android/tests/emulator-smoke.sh <apk> <uitvoermap>
set -euo pipefail

APK="${1:?apk ontbreekt}"
OUT="${2:-screenshots}"
PKG="nl.werdens.mediameta"
ACTIVITY="$PKG/.MainActivity"

mkdir -p "$OUT"
rm -f "$OUT"/*.png "$OUT"/*.txt

echo "== wachten tot de emulator klaar is =="
adb wait-for-device
for i in $(seq 1 90); do
  if [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; then
    break
  fi
  sleep 2
done
adb shell input keyevent 82 >/dev/null 2>&1 || true

echo "== installeren =="
for attempt in 1 2 3; do
  if adb install -r -t "$APK"; then
    break
  fi
  echo "installatiepoging $attempt mislukt, opnieuw…"
  adb uninstall "$PKG" >/dev/null 2>&1 || true
  sleep 5
done
adb shell pm list packages | grep -q "$PKG"

echo "== starten =="
adb logcat -c
adb shell am start -W -n "$ACTIVITY" > "$OUT/start.txt"
cat "$OUT/start.txt"

for i in $(seq 1 60); do
  if adb logcat -d | grep -q "MediaMetaReady"; then
    break
  fi
  sleep 2
done
adb logcat -d > "$OUT/logcat.txt"
if ! grep -q "MediaMetaReady" "$OUT/logcat.txt"; then
  echo "app logde de startup-marker niet"; tail -40 "$OUT/logcat.txt"; exit 1
fi
if ! grep -qi "nl.werdens.mediameta/.MainActivity" "$OUT/start.txt"; then
  echo "verkeerde activity gestart"; exit 1
fi
if grep -qE "FATAL EXCEPTION|ANR in $PKG" "$OUT/logcat.txt"; then
  echo "crash in logcat"; grep -A15 "FATAL EXCEPTION" "$OUT/logcat.txt"; exit 1
fi

echo "== screenshot =="
sleep 3
for i in $(seq 1 8); do
  adb exec-out screencap -p > "$OUT/android-leeg.png"
  SIZE=$(wc -c < "$OUT/android-leeg.png")
  if [ "$SIZE" -gt 20000 ]; then
    break
  fi
  sleep 3
done
python3 - "$OUT/android-leeg.png" <<'PY'
import struct, sys
path = sys.argv[1]
data = open(path, "rb").read()
assert data[:8] == b"\x89PNG\r\n\x1a\n", "geen PNG"
width, height = struct.unpack(">II", data[16:24])
assert width > 300 and height > 600, f"onverwachte afmetingen {width}x{height}"
print(f"screenshot ok: {width}x{height}, {len(data)} bytes")
PY

echo "== klaar =="