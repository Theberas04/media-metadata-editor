# Android-app

Dezelfde functie als de Windows-versie, op de telefoon: mediabestand openen,
afspelen, metadata bekijken en aanpassen, en terugschrijven naar hetzelfde
bestand.

## Wat de app doet

- **Elf velden**: titel, artiest, albumartiest, album, tracknummer, schijf, genre,
  jaar, componist, commentaar en songtekst.
- **Frame opslaan en delen**: het beeld dat je ziet bewaren als PNG of JPG en via
  een andere app doorsturen.
- **Bijwerken**: bij het starten controleert de app of er een nieuwere versie is
  en toont dan een balk met de downloadlink; Android installeert nooit stil.
- **Merk**: het Werdens Media-merk linksboven in de app en als launcher-icoon
  (gewoon, rond en adaptief) via `tools/make_android_icons.py`.

## Installeren

Download `app-release.apk` uit de laatste release en open hem op de telefoon
(Instellingen → "Onbekende apps toestaan" voor de app die hem opent). De app
vraagt géén opslagmachtigingen: je kiest zelf een bestand via de documentenkiezer.

## Wat werkt per formaat

| Formaat | Afspelen | Tags lezen | Tags aanpassen |
|---|---|---|---|
| MP3 | ja | ja (ID3v2/ID3v1) | ja |
| MP4 / M4V / MOV | ja | ja (iTunes-metadata) | ja |
| M4A | ja | ja | ja |
| FLAC, OGG, WAV | ja | ja (wat Android zelf kent) | nee |
| MKV, WEBM | ja* | ja (wat Android zelf kent) | nee |
| AVI, WMV, MXF | nee* | nee | nee |

\* Afspelen hangt af van de codecs die het toestel ondersteunt. De app zegt het
gewoon als iets niet lukt in plaats van te doen alsof.

Bewust niet ondersteund bij het schrijven: containers waarvan de tag-structuur
per fabrikant verschilt (MXF, AVI, WMV) en FLAC/OGG (extra bibliotheek, nog geen
vraag naar). Bij die bestanden blijven afspelen en lezen werken.

## Hoe het schrijven werkt

1. Het gekozen bestand wordt naar de cache gekopieerd (de app heeft dan een
   gewoon bestand om in te werken).
2. `MediaTags` kiest de schrijver: `Mp3Tags` (mp3agic) voor MP3, `Mp4Tags` voor
   MP4/M4A/MOV.
3. `Mp4Tags` schrijft de `moov/udta/meta/ilst`-boxen zelf. Wordt de `moov` groter
   en staat hij vóór de media-data (faststart), dan worden alle chunk-offsets
   (`stco`/`co64`) met precies die groei opgehoogd — zonder dat is het bestand
   onleesbaar. Daarom gebeurt dit in eigen code en niet met een oude
   MP4-bibliotheek die dit niet doet.
4. De bytes gaan terug naar het originele document. Kan dat niet (bijvoorbeeld
   bij een alleen-lezen provider), dan biedt de app "opslaan als" aan.
5. Daarna leest de app het bestand terug en meldt per veld of het gelukt is.

## Testen

De tag-laag is pure Java en wordt op de JVM getest met echte mediabestanden:

```bash
bash android/tests/run-jvm-tests.sh
```

Dat maakt met ffmpeg een mp3, een mp4 met de `moov` achteraan, een mp4 met
`+faststart` en een m4a, schrijft alle tags (inclusief UTF-8 en een `;` in het
commentaar), en controleert daarna met `ffprobe`:

- staan de tags erin zoals een speler ze ziet (geen BOM-tekens),
- is de duur onveranderd,
- decodeert het bestand nog echt (één frame video + één seconde audio).

De CI doet hetzelfde en bouwt daarna de APK, ondertekent hem en start hem op een
emulator om te controleren dat hij echt opent. Die proef maakt ook
controlebeelden van het scherm (met het nieuwe launcher-icoon) en bewaart ze als
artifact.

## Zelf bouwen

```bash
cd android
gradle :app:assembleDebug          # of ./gradlew als je de wrapper gebruikt
```

Vereist JDK 17 en de Android SDK (platform 35, build-tools 35.0.0). Voor een
ondertekende release zet je `ANDROID_KEYSTORE_PATH`, `ANDROID_KEYSTORE_PASSWORD`,
`ANDROID_KEY_ALIAS` en `ANDROID_KEY_PASSWORD` in de omgeving (de CI doet dat met
repository-secrets).

## Licenties van derden

- [mp3agic](https://github.com/mpatric/mp3agic) — MIT, voor ID3-tags in MP3.
- [AndroidX Media3](https://developer.android.com/jetpack/androidx/releases/media3) — Apache 2.0, speler.
- De MP4-tagwriter is eigen code in deze repository.