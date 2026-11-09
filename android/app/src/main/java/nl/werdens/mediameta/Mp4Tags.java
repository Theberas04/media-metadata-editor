package nl.werdens.mediameta;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Leest en schrijft iTunes-metadata (moov/udta/meta/ilst) in MP4-, M4A- en MOV-bestanden.
 *
 * Bewust zonder externe bibliotheek: de gebruikelijke MP4-libraries schrijven deze
 * boxen niet (of alleen via een volledige re-mux). Deze klasse werkt op de
 * boxstructuur zelf, is pure Java en draait dus zowel op Android als in de tests
 * op de JVM.
 *
 * Belangrijk detail: staat de moov vóór de mdat (faststart), dan verschuift alle
 * media-data zodra de moov groter wordt. In dat geval worden alle chunk-offsets
 * (stco/co64) met precies die verschuiving opgehoogd — anders is het bestand
 * onleesbaar.
 */
public final class Mp4Tags {

    public static final String[] KEYS = {"title", "artist", "album", "genre", "year", "comment"};

    /** iTunes-atomen die bij de sleutels horen (0xA9 is het ©-teken). */
    private static final String[] ATOMS = {
            "\u00A9nam", "\u00A9ART", "\u00A9alb", "\u00A9gen", "\u00A9day", "\u00A9cmt"
    };

    private static final String[] CONTAINERS = {
            "moov", "trak", "mdia", "minf", "stbl", "edts", "dinf", "udta", "mvex",
            "rinf", "sinf", "schi", "tref", "gmhd"
    };

    private Mp4Tags() {
    }

    // ------------------------------------------------------------------ lezen

    /** Alle bekende tags; velden die niet in het bestand staan zijn lege strings. */
    public static Map<String, String> read(File file) throws IOException {
        Map<String, String> tags = emptyTags();
        byte[] moov = readMoov(file);
        if (moov == null) {
            return tags;
        }
        Box ilst = findIlst(moov);
        if (ilst == null) {
            return tags;
        }
        Map<String, String> byAtom = new LinkedHashMap<>();
        for (Box item : parseChildren(moov, ilst.contentStart, ilst.end)) {
            Box data = find(parseChildren(moov, item.contentStart, item.end), "data");
            byAtom.put(item.type, data == null ? "" : decodeData(moov, data));
        }
        for (int i = 0; i < KEYS.length; i++) {
            String value = byAtom.get(ATOMS[i]);
            if (value == null && ATOMS[i].equals("\u00A9gen")) {
                String numeric = byAtom.get("gnre");
                if (numeric != null) {
                    value = genreName(numeric);
                }
            }
            tags.put(KEYS[i], value == null ? "" : value);
        }
        return tags;
    }

    private static Map<String, String> emptyTags() {
        Map<String, String> tags = new LinkedHashMap<>();
        for (String key : KEYS) {
            tags.put(key, "");
        }
        return tags;
    }

    private static String decodeData(byte[] data, Box box) {
        int type = u32(data, box.contentStart);
        int payloadStart = box.contentStart + 8;
        int length = box.end - payloadStart;
        if (length <= 0) {
            return "";
        }
        String value;
        if (type == 2) {
            value = new String(data, payloadStart, length, StandardCharsets.UTF_16BE);
        } else if (type == 21) {
            value = String.valueOf((long) u32(data, payloadStart));
        } else if (type == 0) {
            value = String.valueOf((long) u32(data, payloadStart));
        } else {
            value = new String(data, payloadStart, length, StandardCharsets.UTF_8);
        }
        return value.trim();
    }

    // --------------------------------------------------------------- schrijven

    /** Schrijft de tags weg in hetzelfde bestand (via een tijdelijk bestand). */
    public static void write(File file, Map<String, String> values) throws IOException {
        byte[] moov = readMoov(file);
        if (moov == null) {
            throw new IOException("Geen moov-box gevonden: dit is geen geldig MP4-bestand.");
        }
        List<TopBox> layout = scanTopLevel(file);
        long moovEnd = -1;
        long mdatAfterMoov = -1;
        for (TopBox box : layout) {
            if (box.type.equals("moof")) {
                throw new IOException("Gefragmenteerde MP4-bestanden worden niet ondersteund.");
            }
            if (box.type.equals("sidx")) {
                throw new IOException("Bestanden met een segment-index worden niet ondersteund.");
            }
            if (box.type.equals("moov")) {
                moovEnd = box.start + box.size;
            }
        }
        for (TopBox box : layout) {
            if (box.type.equals("mdat") && moovEnd > 0 && box.start >= moovEnd) {
                mdatAfterMoov = box.start;
                break;
            }
        }

        byte[] newMoov = rebuildMoov(moov, values);
        long delta = newMoov.length - (long) moov.length;
        if (delta != 0 && mdatAfterMoov > 0) {
            patchChunkOffsets(newMoov, 8, newMoov.length, (int) delta);
        }

        Path target = file.toPath();
        Path temp = target.resolveSibling(target.getFileName() + ".mmtmp");
        try (RandomAccessFile in = new RandomAccessFile(file, "r");
             RandomAccessFile out = new RandomAccessFile(temp.toFile(), "rw")) {
            out.setLength(0);
            for (TopBox box : layout) {
                if (box.type.equals("moov")) {
                    out.write(newMoov);
                    continue;
                }
                in.seek(box.start);
                byte[] buffer = new byte[256 * 1024];
                long remaining = box.size;
                while (remaining > 0) {
                    int want = (int) Math.min(buffer.length, remaining);
                    int read = in.read(buffer, 0, want);
                    if (read <= 0) {
                        throw new IOException("Onverwacht einde van het bestand.");
                    }
                    out.write(buffer, 0, read);
                    remaining -= read;
                }
            }
        } catch (IOException e) {
            Files.deleteIfExists(temp);
            throw e;
        }
        try {
            Files.move(temp, target, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException e) {
            Files.deleteIfExists(temp);
            throw e;
        }
    }

    // ------------------------------------------------------------ moov/ilst

    private static byte[] rebuildMoov(byte[] moov, Map<String, String> values) {
        List<Box> children = parseChildren(moov, 8, moov.length);
        Box udtaBox = find(children, "udta");
        List<Box> udtaChildren = udtaBox == null
                ? new ArrayList<Box>()
                : parseChildren(moov, udtaBox.contentStart, udtaBox.end);

        // Bestaande ilst-items (cover, tracknummer, ...) bewaren we.
        Map<String, byte[]> existing = new LinkedHashMap<>();
        Box metaBox = find(udtaChildren, "meta");
        if (metaBox != null) {
            Box ilstBox = find(parseChildren(moov, metaBox.contentStart + 4, metaBox.end), "ilst");
            if (ilstBox != null) {
                for (Box item : parseChildren(moov, ilstBox.contentStart, ilstBox.end)) {
                    existing.put(item.type, slice(moov, item.start, item.end));
                }
            }
        }

        ByteArrayOutputStream ilstContent = new ByteArrayOutputStream();
        boolean writesGenre = values.get("genre") != null;
        for (Map.Entry<String, byte[]> entry : existing.entrySet()) {
            if (isOurAtom(entry.getKey())) {
                continue;
            }
            if (writesGenre && entry.getKey().equals("gnre")) {
                continue;
            }
            ilstContent.writeBytes(entry.getValue());
        }
        for (int i = 0; i < KEYS.length; i++) {
            String value = values.get(KEYS[i]);
            ilstContent.writeBytes(buildItem(ATOMS[i], value == null ? "" : value));
        }

        ByteArrayOutputStream udtaContent = new ByteArrayOutputStream();
        for (Box box : udtaChildren) {
            if (box.type.equals("meta")) {
                continue;
            }
            udtaContent.writeBytes(slice(moov, box.start, box.end));
        }
        udtaContent.writeBytes(buildMetaBox(ilstContent.toByteArray()));

        ByteArrayOutputStream moovContent = new ByteArrayOutputStream();
        boolean replaced = false;
        for (Box box : children) {
            if (box.type.equals("udta")) {
                moovContent.writeBytes(box("udta", udtaContent.toByteArray()));
                replaced = true;
            } else {
                moovContent.writeBytes(slice(moov, box.start, box.end));
            }
        }
        if (!replaced) {
            moovContent.writeBytes(box("udta", udtaContent.toByteArray()));
        }
        return box("moov", moovContent.toByteArray());
    }

    private static byte[] buildItem(String atom, String value) {
        ByteArrayOutputStream data = new ByteArrayOutputStream();
        data.writeBytes(u32(1));    // type 1 = UTF-8
        data.writeBytes(u32(0));    // locale
        data.writeBytes(value.getBytes(StandardCharsets.UTF_8));
        ByteArrayOutputStream content = new ByteArrayOutputStream();
        content.writeBytes(box("data", data.toByteArray()));
        return box(atom, content.toByteArray());
    }

    private static byte[] buildMetaBox(byte[] ilstBytes) {
        ByteArrayOutputStream hdlr = new ByteArrayOutputStream();
        hdlr.writeBytes(u32(0));                 // version/flags
        hdlr.writeBytes(u32(0));                 // pre_defined
        hdlr.writeBytes(fourccBytes("mdir"));    // handler
        hdlr.writeBytes(fourccBytes("appl"));    // manufacturer
        hdlr.writeBytes(new byte[12]);           // reserved
        hdlr.write(0);                           // lege naam

        ByteArrayOutputStream meta = new ByteArrayOutputStream();
        meta.writeBytes(u32(0));                 // version/flags van de meta-box
        meta.writeBytes(box("hdlr", hdlr.toByteArray()));
        meta.writeBytes(box("ilst", ilstBytes));
        return box("meta", meta.toByteArray());
    }

    private static boolean isOurAtom(String atom) {
        for (String candidate : ATOMS) {
            if (candidate.equals(atom)) {
                return true;
            }
        }
        return false;
    }

    private static Box findIlst(byte[] moov) {
        List<Box> children = parseChildren(moov, 8, moov.length);
        Box udta = find(children, "udta");
        if (udta == null) {
            return null;
        }
        Box meta = find(parseChildren(moov, udta.contentStart, udta.end), "meta");
        if (meta == null) {
            return null;
        }
        return find(parseChildren(moov, meta.contentStart + 4, meta.end), "ilst");
    }

    // ------------------------------------------------------- chunk-offsets

    private static void patchChunkOffsets(byte[] data, int from, int to, int delta) {
        for (Box box : parseChildren(data, from, to)) {
            if (box.type.equals("stco")) {
                int count = u32(data, box.contentStart + 4);
                for (int i = 0; i < count; i++) {
                    int at = box.contentStart + 8 + i * 4;
                    if (at + 4 > box.end) {
                        break;
                    }
                    writeU32(data, at, u32(data, at) + delta);
                }
            } else if (box.type.equals("co64")) {
                int count = u32(data, box.contentStart + 4);
                for (int i = 0; i < count; i++) {
                    int at = box.contentStart + 8 + i * 8;
                    if (at + 8 > box.end) {
                        break;
                    }
                    writeLong(data, at, readLong(data, at) + delta);
                }
            } else if (isContainer(box.type)) {
                int inner = box.type.equals("meta") ? box.contentStart + 4 : box.contentStart;
                patchChunkOffsets(data, inner, box.end, delta);
            }
        }
    }

    private static boolean isContainer(String type) {
        for (String candidate : CONTAINERS) {
            if (candidate.equals(type)) {
                return true;
            }
        }
        return false;
    }

    // -------------------------------------------------------------- bestand

    private static byte[] readMoov(File file) throws IOException {
        for (TopBox box : scanTopLevel(file)) {
            if (box.type.equals("moov")) {
                if (box.size > 64L * 1024 * 1024) {
                    throw new IOException("moov-box is te groot om te verwerken.");
                }
                byte[] data = new byte[(int) box.size];
                try (RandomAccessFile raf = new RandomAccessFile(file, "r")) {
                    raf.seek(box.start);
                    raf.readFully(data);
                }
                return data;
            }
        }
        return null;
    }

    private static List<TopBox> scanTopLevel(File file) throws IOException {
        List<TopBox> boxes = new ArrayList<>();
        long length = file.length();
        try (RandomAccessFile raf = new RandomAccessFile(file, "r")) {
            long position = 0;
            byte[] header = new byte[16];
            while (position + 8 <= length) {
                raf.seek(position);
                raf.readFully(header, 0, 8);
                long size = u32(header, 0);
                String type = fourcc(header, 4);
                int headerLen = 8;
                if (size == 1) {
                    raf.readFully(header, 8, 8);
                    size = readLong(header, 8);
                    headerLen = 16;
                } else if (size == 0) {
                    size = length - position;
                }
                if (size < headerLen || position + size > length) {
                    break;
                }
                boxes.add(new TopBox(type, position, size));
                position += size;
            }
        }
        return boxes;
    }

    private static final class TopBox {
        final String type;
        final long start;
        final long size;

        TopBox(String type, long start, long size) {
            this.type = type;
            this.start = start;
            this.size = size;
        }
    }

    // ------------------------------------------------------------- box-hulp

    private static final class Box {
        final String type;
        final int start;
        final int end;
        final int contentStart;

        Box(String type, int start, int end, int contentStart) {
            this.type = type;
            this.start = start;
            this.end = end;
            this.contentStart = contentStart;
        }
    }

    private static List<Box> parseChildren(byte[] data, int from, int to) {
        List<Box> boxes = new ArrayList<>();
        int position = from;
        while (position + 8 <= to) {
            long size = u32(data, position);
            String type = fourcc(data, position + 4);
            int headerLen = 8;
            if (size == 1) {
                if (position + 16 > to) {
                    break;
                }
                size = readLong(data, position + 8);
                headerLen = 16;
            } else if (size == 0) {
                size = to - position;
            }
            if (size < headerLen || position + size > to) {
                break;
            }
            boxes.add(new Box(type, position, position + (int) size, position + headerLen));
            position += (int) size;
        }
        return boxes;
    }

    private static Box find(List<Box> boxes, String type) {
        for (Box box : boxes) {
            if (box.type.equals(type)) {
                return box;
            }
        }
        return null;
    }

    private static byte[] box(String type, byte[] content) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        out.writeBytes(u32(content.length + 8));
        out.writeBytes(fourccBytes(type));
        out.writeBytes(content);
        return out.toByteArray();
    }

    private static byte[] slice(byte[] data, int from, int to) {
        byte[] out = new byte[to - from];
        System.arraycopy(data, from, out, 0, out.length);
        return out;
    }

    private static String fourcc(byte[] data, int offset) {
        return new String(data, offset, 4, StandardCharsets.ISO_8859_1);
    }

    private static byte[] fourccBytes(String type) {
        byte[] out = new byte[4];
        byte[] raw = type.getBytes(StandardCharsets.ISO_8859_1);
        System.arraycopy(raw, 0, out, 0, Math.min(4, raw.length));
        return out;
    }

    private static int u32(byte[] data, int offset) {
        return ((data[offset] & 0xFF) << 24)
                | ((data[offset + 1] & 0xFF) << 16)
                | ((data[offset + 2] & 0xFF) << 8)
                | (data[offset + 3] & 0xFF);
    }

    private static long readLong(byte[] data, int offset) {
        long value = 0;
        for (int i = 0; i < 8; i++) {
            value = (value << 8) | (data[offset + i] & 0xFFL);
        }
        return value;
    }

    private static void writeU32(byte[] data, int offset, int value) {
        data[offset] = (byte) (value >>> 24);
        data[offset + 1] = (byte) (value >>> 16);
        data[offset + 2] = (byte) (value >>> 8);
        data[offset + 3] = (byte) value;
    }

    private static void writeLong(byte[] data, int offset, long value) {
        for (int i = 0; i < 8; i++) {
            data[offset + i] = (byte) (value >>> (56 - 8 * i));
        }
    }

    private static byte[] u32(int value) {
        return new byte[]{
                (byte) (value >>> 24), (byte) (value >>> 16), (byte) (value >>> 8), (byte) value
        };
    }

    // -------------------------------------------------------------- genres

    private static final String[] ID3_GENRES = {
            "Blues", "Classic Rock", "Country", "Dance", "Disco", "Funk", "Grunge", "Hip-Hop",
            "Jazz", "Metal", "New Age", "Oldies", "Other", "Pop", "R&B", "Rap", "Reggae", "Rock",
            "Techno", "Industrial", "Alternative", "Ska", "Death Metal", "Pranks", "Soundtrack",
            "Euro-Techno", "Ambient", "Trip-Hop", "Vocal", "Jazz+Funk", "Fusion", "Trance",
            "Classical", "Instrumental", "Acid", "House", "Game", "Sound Clip", "Gospel", "Noise",
            "AlternRock", "Bass", "Soul", "Punk", "Space", "Meditative", "Instrumental Pop",
            "Instrumental Rock", "Ethnic", "Gothic", "Darkwave", "Techno-Industrial", "Electronic",
            "Pop-Folk", "Eurodance", "Dream", "Southern Rock", "Comedy", "Cult", "Gangsta",
            "Top 40", "Christian Rap", "Pop/Funk", "Jungle", "Native American", "Cabaret",
            "New Wave", "Psychedelic", "Rave", "Showtunes", "Trailer", "Lo-Fi", "Tribal",
            "Acid Punk", "Acid Jazz", "Polka", "Retro", "Musical", "Rock & Roll", "Hard Rock",
            "Folk", "Folk-Rock", "National Folk", "Swing", "Fast Fusion", "Bebob", "Latin",
            "Revival", "Celtic", "Bluegrass", "Avantgarde", "Gothic Rock", "Progressive Rock",
            "Psychedelic Rock", "Symphonic Rock", "Slow Rock", "Big Band", "Chorus",
            "Easy Listening", "Acoustic", "Humour", "Speech", "Chanson", "Opera",
            "Chamber Music", "Sonata", "Symphony", "Booty Bass", "Primus", "Porn Groove",
            "Satire", "Slow Jam", "Club", "Tango", "Samba", "Folklore", "Ballad", "Power Ballad",
            "Rhythmic Soul", "Freestyle", "Duet", "Punk Rock", "Drum Solo", "A capella",
            "Euro-House", "Dance Hall", "Goa", "Drum & Bass", "Club-House", "Hardcore", "Terror",
            "Indie", "BritPop", "Afro-Punk", "Polsk Punk", "Beat", "Christian Gangsta Rap",
            "Heavy Metal", "Black Metal", "Crossover", "Contemporary Christian",
            "Christian Rock", "Merengue", "Salsa", "Thrash Metal", "Anime", "JPop", "Synthpop",
    };

    private static String genreName(String numeric) {
        try {
            int index = Integer.parseInt(numeric.trim()) - 1;
            if (index >= 0 && index < ID3_GENRES.length) {
                return ID3_GENRES[index];
            }
        } catch (NumberFormatException ignored) {
            // geen numerieke genre
        }
        return numeric;
    }
}