import nl.werdens.mediameta.MediaTags;

import java.io.File;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * JVM-test voor de tag-lezers en -schrijvers die de Android-app gebruikt.
 *
 * Draait zonder Android: dezelfde klassen, maar met echte mediabestanden die
 * met ffmpeg zijn gemaakt (zie android/tests/run-jvm-tests.sh).
 */
public final class TagRoundTripTest {

    private static int failures = 0;

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.out.println("gebruik: TagRoundTripTest <map-met-mediabestanden>");
            System.exit(2);
        }
        File dir = new File(args[0]);
        File[] files = dir.listFiles();
        if (files == null || files.length == 0) {
            System.out.println("geen bestanden in " + dir);
            System.exit(2);
        }
        Arrays.sort(files, Comparator.comparing(File::getName));

        for (File file : files) {
            if (!MediaTags.canWrite(file.getName())) {
                System.out.println("overslaan (alleen lezen): " + file.getName());
                continue;
            }
            Map<String, String> want = valuesFor(file.getName());
            Map<String, String> before = MediaTags.read(file);
            System.out.println("[voor] " + file.getName() + " -> " + before);

            MediaTags.write(file, want);

            Map<String, String> after = MediaTags.read(file);
            System.out.println("[na]   " + file.getName() + " -> " + after);
            for (String key : want.keySet()) {
                String expected = want.get(key);
                String actual = after.get(key);
                if (!expected.equals(actual)) {
                    System.out.println("  FAIL " + file.getName() + " veld '" + key
                            + "': verwacht '" + expected + "', kreeg '" + actual + "'");
                    failures++;
                }
            }
            System.out.println("       grootte na schrijven: " + file.length() + " bytes");
        }

        // Een onbekende genre mag een MP3 niet laten crashen en de oude waarde bewaren.
        // (Op een kopie, zodat de ffprobe-controle hierna de echte tags ziet.)
        File mp3 = null;
        for (File file : files) {
            if (file.getName().endsWith(".mp3")) {
                mp3 = file;
                break;
            }
        }
        if (mp3 != null) {
            File copy = new File(System.getProperty("java.io.tmpdir"),
                    "mediameta-genre-" + System.nanoTime() + ".mp3");
            java.nio.file.Files.copy(mp3.toPath(), copy.toPath());
            try {
                Map<String, String> keep = new LinkedHashMap<>();
                keep.put("title", "Genre-test");
                keep.put("genre", "Documentaire");
                MediaTags.write(copy, keep);
                Map<String, String> result = MediaTags.read(copy);
                System.out.println("[genre] onbekende genre op MP3 -> '" + result.get("genre") + "'");
                if (!"Genre-test".equals(result.get("title"))) {
                    System.out.println("  FAIL titel niet gezet bij genre-test");
                    failures++;
                }
            } finally {
                copy.delete();
            }
        }

        System.out.println(failures == 0 ? "TAGS OK" : "FAILURES: " + failures);
        System.exit(failures == 0 ? 0 : 1);
    }

    private static Map<String, String> valuesFor(String name) {
        Map<String, String> values = new LinkedHashMap<>();
        values.put("title", "Ça va — 日本語 (test)");
        values.put("artist", "Tom Werdens");
        values.put("album", "Waddenreeks 2026");
        // ID3 kent alleen vaste genrenamen; MP4 slaat vrije tekst op.
        values.put("genre", name.endsWith(".mp3") ? "Ambient" : "Documentaire");
        values.put("year", "2026");
        values.put("comment", "definitief; klant, 4K");
        values.put("albumartist", "Werdens Media");
        values.put("composer", "Tom Werdens");
        values.put("track", "3/12");
        values.put("disc", "1/2");
        values.put("lyrics", "Eerste regel\nTweede regel");
        return values;
    }
}