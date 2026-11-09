package nl.werdens.mediameta;

import com.mpatric.mp3agic.ID3v1;
import com.mpatric.mp3agic.ID3v2;
import com.mpatric.mp3agic.ID3v24Tag;
import com.mpatric.mp3agic.Mp3File;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.LinkedHashMap;
import java.util.Map;

/** Leest en schrijft ID3-tags in MP3-bestanden (via de mp3agic-bibliotheek). */
public final class Mp3Tags {

    private Mp3Tags() {
    }

    public static Map<String, String> read(File file) throws IOException {
        Mp3File mp3 = open(file);
        if (mp3.hasId3v2Tag()) {
            return fill(mp3.getId3v2Tag());
        }
        if (mp3.hasId3v1Tag()) {
            return fill(mp3.getId3v1Tag());
        }
        return empty();
    }

    public static void write(File file, Map<String, String> values) throws IOException {
        Mp3File mp3 = open(file);
        ID3v2 tag = mp3.hasId3v2Tag() ? mp3.getId3v2Tag() : new ID3v24Tag();
        tag.setTitle(nullToEmpty(values.get("title")));
        tag.setArtist(nullToEmpty(values.get("artist")));
        tag.setAlbum(nullToEmpty(values.get("album")));
        tag.setYear(nullToEmpty(values.get("year")));
        tag.setComment(nullToEmpty(values.get("comment")));
        String genre = nullToEmpty(values.get("genre")).trim();
        if (!genre.isEmpty()) {
            try {
                tag.setGenreDescription(genre);
            } catch (IllegalArgumentException ignored) {
                // ID3 kent alleen vaste genrenamen; een vrije tekst laten we staan
                // zodat de bestaande waarde niet verloren gaat.
            }
        }
        mp3.setId3v2Tag(tag);

        Path target = file.toPath();
        Path temp = target.resolveSibling(target.getFileName() + ".mmtmp");
        Files.deleteIfExists(temp);
        try {
            mp3.save(temp.toFile().getAbsolutePath());
            fixUtf16Bom(temp.toFile());
        } catch (Exception e) {
            Files.deleteIfExists(temp);
            throw new IOException("Opslaan van de MP3-tags mislukte: " + e.getMessage(), e);
        }
        try {
            Files.move(temp, target, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            Files.deleteIfExists(temp);
            throw e;
        }
    }

    private static Mp3File open(File file) throws IOException {
        try {
            return new Mp3File(file);
        } catch (Exception e) {
            throw new IOException("Geen geldig MP3-bestand: " + e.getMessage(), e);
        }
    }

    /**
     * mp3agic schrijft UTF-16-tekst met encoding-byte 2 (UTF-16BE zónder BOM)
     * terwijl de bytes wél met een BOM beginnen. Veel spelers (en ffmpeg) tonen
     * dat BOM-teken vervolgens als een zichtbaar teken vóór de titel. Door de
     * encoding-byte 2 -> 1 te zetten klopt de declaratie met de inhoud en
     * verdwijnt het teken.
     */
    static int fixUtf16Bom(File file) throws IOException {
        int fixed = 0;
        try (RandomAccessFile raf = new RandomAccessFile(file, "rw")) {
            byte[] header = new byte[10];
            raf.seek(0);
            if (raf.read(header) < 10 || header[0] != 'I' || header[1] != 'D' || header[2] != '3') {
                return 0;
            }
            int version = header[3] & 0xFF;
            int flags = header[5] & 0xFF;
            long end = 10 + synchsafe(header, 6);
            long position = 10;
            if ((flags & 0x40) != 0) {
                // Uitgebreide header overslaan (schrijft mp3agic niet, maar toch).
                raf.seek(10);
                byte[] ext = new byte[4];
                if (raf.read(ext) == 4) {
                    position += (version == 4 ? synchsafe(ext, 0) : beInt(ext, 0)) + 4L;
                }
            }
            byte[] frameHeader = new byte[10];
            while (position + 10 <= end) {
                raf.seek(position);
                if (raf.read(frameHeader) < 10 || frameHeader[0] == 0) {
                    break;   // padding bereikt
                }
                int frameSize = version == 4 ? synchsafe(frameHeader, 4) : beInt(frameHeader, 4);
                if (frameSize <= 2 || position + 10 + frameSize > end) {
                    break;
                }
                raf.seek(position + 10);
                if (raf.read() == 2) {
                    int first = raf.read();
                    int second = raf.read();
                    if (first == 0xFE && second == 0xFF) {
                        raf.seek(position + 10);
                        raf.write(1);   // UTF-16 met BOM
                        fixed++;
                    }
                }
                position += 10L + frameSize;
            }
        }
        return fixed;
    }

    private static int synchsafe(byte[] data, int offset) {
        return ((data[offset] & 0x7F) << 21)
                | ((data[offset + 1] & 0x7F) << 14)
                | ((data[offset + 2] & 0x7F) << 7)
                | (data[offset + 3] & 0x7F);
    }

    private static int beInt(byte[] data, int offset) {
        return ((data[offset] & 0xFF) << 24)
                | ((data[offset + 1] & 0xFF) << 16)
                | ((data[offset + 2] & 0xFF) << 8)
                | (data[offset + 3] & 0xFF);
    }

    private static Map<String, String> fill(ID3v1 tag) {
        Map<String, String> tags = empty();
        tags.put("title", nullToEmpty(tag.getTitle()));
        tags.put("artist", nullToEmpty(tag.getArtist()));
        tags.put("album", nullToEmpty(tag.getAlbum()));
        tags.put("year", nullToEmpty(tag.getYear()));
        tags.put("comment", nullToEmpty(tag.getComment()));
        tags.put("genre", nullToEmpty(tag.getGenreDescription()));
        return tags;
    }

    private static Map<String, String> empty() {
        Map<String, String> tags = new LinkedHashMap<>();
        for (String key : Mp4Tags.KEYS) {
            tags.put(key, "");
        }
        return tags;
    }

    private static String nullToEmpty(String value) {
        return value == null ? "" : value;
    }
}