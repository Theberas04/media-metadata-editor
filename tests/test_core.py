"""Tests voor mediameta.core tegen echte mediabestanden (echte ffmpeg)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mediameta import core  # noqa: E402


def make_media(directory: Path, name: str, extra: list[str], duration: float = 3.0) -> Path:
    ffmpeg = core.find_ffmpeg()
    target = directory / name
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    if name.endswith((".mp4", ".mkv", ".mov")):
        args = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=15:duration={duration}",
                "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    args += extra + [str(target)]
    subprocess.run(args, check=True, capture_output=True)
    return target


class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix="mediameta-test-"))
        base = ["-metadata", "title=Oorspronkelijke titel", "-metadata", "artist=Onbekend"]
        cls.mp3 = make_media(cls.dir, "test.mp3", base)
        cls.mp4 = make_media(cls.dir, "test.mp4", base + ["-shortest"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_probe_finds_duration_and_tags(self):
        info = core.probe(self.mp3)
        self.assertGreater(info.duration_ms, 2000)
        self.assertEqual(info.tag("title"), "Oorspronkelijke titel")
        self.assertEqual(info.tag("artist"), "Onbekend")
        self.assertFalse(info.is_video)
        self.assertTrue(info.probe_source)

    def test_probe_video_reports_resolution(self):
        info = core.probe(self.mp4)
        self.assertTrue(info.is_video)
        self.assertEqual((info.width, info.height), (320, 180))
        self.assertIn("180", info.resolution)
        self.assertEqual(info.kind, "Video")

    def test_write_tags_in_place(self):
        target = self.dir / "inplace.mp3"
        shutil.copy(self.mp3, target)
        values = {
            "title": "Nieuwe titel",
            "artist": "Tom Werdens",
            "album": "Demo album",
            "genre": "Ambient",
            "year": "2026",
            "comment": "Opgenomen in de studio",
        }
        core.write_tags(target, None, values)
        info = core.probe(target)
        self.assertEqual(core.tags_match(values, info), {k: True for k in core.FIELDS})
        self.assertEqual(info.tag("title"), "Nieuwe titel")
        self.assertEqual(info.tag("year"), "2026")

    def test_write_to_new_file_keeps_source(self):
        target = self.dir / "copy.mp3"
        before = core.probe(self.mp3).fields()
        result = core.write_tags(self.mp3, target, {"title": "Kopie"})
        self.assertTrue(target.exists())
        self.assertEqual(result.tag("title"), "Kopie")
        after = core.probe(self.mp3).fields()
        self.assertEqual(before, after, "bronbestand mag niet aangepast worden")

    def test_clearing_a_field(self):
        target = self.dir / "clear.mp3"
        shutil.copy(self.mp3, target)
        core.write_tags(target, None, {"title": "", "artist": "Alleen artiest"})
        info = core.probe(target)
        self.assertEqual(info.tag("title"), "")
        self.assertEqual(info.tag("artist"), "Alleen artiest")

    def test_unicode_and_specials_survive(self):
        target = self.dir / "unicode.mp3"
        shutil.copy(self.mp3, target)
        values = {"title": "Ça va — 日本語", "comment": "a=b; c\\d"}
        core.write_tags(target, None, values)
        info = core.probe(target)
        self.assertEqual(info.tag("title"), values["title"])
        self.assertEqual(info.tag("comment"), values["comment"])

    def test_video_metadata_write(self):
        target = self.dir / "video.mp4"
        shutil.copy(self.mp4, target)
        values = {"title": "Drone vlucht", "artist": "Werdens Media", "year": "2025"}
        core.write_tags(target, None, values)
        info = core.probe(target)
        self.assertEqual(core.tags_match(values, info), {"title": True, "artist": True, "year": True})
        self.assertEqual((info.width, info.height), (320, 180), "video mag niet veranderen")

    def test_progress_reaches_one(self):
        target = self.dir / "progress.mp3"
        shutil.copy(self.mp3, target)
        seen: list[float] = []
        core.write_tags(target, None, {"title": "Voortgang"}, on_progress=seen.append)
        self.assertTrue(seen, "progress callback hoort minstens een keer te lopen")
        self.assertAlmostEqual(seen[-1], 1.0, places=3)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in seen))

    def test_missing_file_raises(self):
        with self.assertRaises(core.MediaError):
            core.probe(self.dir / "bestaat-niet.mp3")

    def test_poster_image_extracts_a_frame(self):
        target = self.dir / "poster.png"
        out = core.poster_image(self.mp4, target, 500)
        self.assertIsNotNone(out)
        data = Path(out).read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertGreater(len(data), 1000)

    def test_poster_from_cover_art(self):
        """Cover-art in een mp3 moet ook een poster opleveren (zonder -ss)."""
        ffmpeg = core.find_ffmpeg()
        cover = self.dir / "cover.png"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=0x3355aa:s=320x180:d=1", "-frames:v", "1", str(cover)],
                       check=True, capture_output=True)
        with_cover = self.dir / "cover.mp3"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(self.mp3), "-i", str(cover),
                        "-map", "0:a", "-map", "1:v", "-c:v", "mjpeg",
                        "-disposition:v", "attached_pic", "-c:a", "copy", str(with_cover)],
                       check=True, capture_output=True)
        out = core.poster_image(with_cover, self.dir / "cover-out.png")
        self.assertIsNotNone(out, "cover-art hoort een poster op te leveren")
        self.assertTrue(Path(out).read_bytes().startswith(b"\x89PNG"))
        info = core.probe(with_cover)
        self.assertFalse(info.is_video, "cover-art mag het bestand niet video maken")

    def test_ffmetadata_parsing(self):
        text = ";FFMETADATA1\ntitle=Een \\= titel\nartist=Tom\n[bogus]\ncomment=a\\;b\n"
        tags = core.parse_ffmetadata(text)
        self.assertEqual(tags["title"], "Een = titel")
        self.assertEqual(tags["comment"], "a;b")
        self.assertNotIn("bogus", tags)

    def test_ffmpeg_fallback_path(self):
        """Zonder ffprobe moet de ffmpeg-terugvalweg dezelfde info geven."""
        if not core.find_ffprobe():
            self.skipTest("ffprobe ontbreekt al; fallback is de standaard")
        original = core._ffmpeg_cache.get("ffprobe")
        core._ffmpeg_cache["ffprobe"] = None
        try:
            info = core.probe(self.mp4)
        finally:
            core._ffmpeg_cache["ffprobe"] = original
        self.assertEqual(info.probe_source, "ffmpeg")
        self.assertEqual(info.tag("title"), "Oorspronkelijke titel")
        self.assertEqual((info.width, info.height), (320, 180))
        self.assertGreater(info.duration_ms, 2000)

    def test_helpers(self):
        self.assertEqual(core.format_duration(0), "00:00")
        self.assertEqual(core.format_duration(65000), "01:05")
        self.assertEqual(core.format_duration(3725000), "1:02:05")
        self.assertEqual(core.human_size(1536), "1.5 kB")
        self.assertTrue(core.is_supported("a.MP4"))
        self.assertFalse(core.is_supported("a.pdf"))

    def test_version_file_matches_module(self):
        version_file = Path(__file__).resolve().parent.parent / "version.txt"
        self.assertEqual(version_file.read_text().strip(), core_version())


def core_version() -> str:
    from mediameta.version import VERSION

    return VERSION


if __name__ == "__main__":
    unittest.main(verbosity=2)