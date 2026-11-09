package nl.werdens.mediameta;

import java.io.File;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/** Kiest de juiste tag-lezer/schrijver op basis van de bestandsextensie. */
public final class MediaTags {

    private MediaTags() {
    }

    public static String extensionOf(String name) {
        int dot = name.lastIndexOf('.');
        return dot < 0 ? "" : name.substring(dot).toLowerCase(Locale.ROOT);
    }

    /** Formaten waarvan de app de tags ook kan aanpassen. */
    public static boolean canWrite(String name) {
        String ext = extensionOf(name);
        return ext.equals(".mp3") || ext.equals(".mp4") || ext.equals(".m4a")
                || ext.equals(".m4v") || ext.equals(".mov");
    }

    public static Map<String, String> read(File file) throws IOException {
        Map<String, String> tags;
        String ext = extensionOf(file.getName());
        if (ext.equals(".mp3")) {
            tags = Mp3Tags.read(file);
        } else if (ext.equals(".mp4") || ext.equals(".m4a") || ext.equals(".m4v") || ext.equals(".mov")) {
            tags = Mp4Tags.read(file);
        } else {
            tags = empty();
        }
        return tags;
    }

    public static void write(File file, Map<String, String> values) throws IOException {
        String ext = extensionOf(file.getName());
        if (ext.equals(".mp3")) {
            Mp3Tags.write(file, values);
        } else if (ext.equals(".mp4") || ext.equals(".m4a") || ext.equals(".m4v") || ext.equals(".mov")) {
            Mp4Tags.write(file, values);
        } else {
            throw new IOException("Van dit bestandstype (" + ext + ") kan de app de tags niet aanpassen.");
        }
    }

    private static Map<String, String> empty() {
        Map<String, String> tags = new LinkedHashMap<>();
        for (String key : Mp4Tags.KEYS) {
            tags.put(key, "");
        }
        return tags;
    }
}