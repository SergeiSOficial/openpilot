package ai.comma.openpilot.sim;

import android.content.Context;
import java.io.File;
import java.io.FileOutputStream;
import java.io.ByteArrayOutputStream;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import java.util.zip.ZipInputStream;
import org.json.JSONObject;

final class FixtureAssets {
    static synchronized File extract(Context context) throws Exception {
        JSONObject manifest;
        try (var input = context.getAssets().open("generated/fixture/manifest.json")) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            for (int count; (count = input.read(buffer)) != -1;) bytes.write(buffer, 0, count);
            manifest = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
        }
        File root = new File(context.getFilesDir(), "fixture");
        if (!root.isDirectory() && !root.mkdirs()) throw new IllegalStateException("Cannot create fixture cache");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        // Hash the complete archive before trusting its entries.
        try (var input = new DigestInputStream(context.getAssets().open("generated/fixture/fixture.zip"), digest)) {
            byte[] buffer = new byte[65536];
            while (input.read(buffer) != -1) {}
        }
        StringBuilder actual = new StringBuilder();
        for (byte value : digest.digest()) actual.append(String.format("%02x", value & 255));
        if (!actual.toString().equals(manifest.getString("sha256"))) throw new IllegalStateException("Fixture archive checksum failed");
        int entries = 0;
        long total = 0;
        try (var archive = new ZipInputStream(context.getAssets().open("generated/fixture/fixture.zip"))) {
            for (var entry = archive.getNextEntry(); entry != null; entry = archive.getNextEntry()) {
                File target = new File(root, entry.getName());
                if (!target.getCanonicalPath().startsWith(root.getCanonicalPath() + File.separator) || entry.isDirectory()) {
                    throw new IllegalStateException("Invalid fixture archive path");
                }
                File parent = target.getParentFile();
                if (!parent.isDirectory() && !parent.mkdirs()) throw new IllegalStateException("Cannot create fixture directory");
                try (var output = new FileOutputStream(target)) {
                    byte[] buffer = new byte[65536];
                    for (int count; (count = archive.read(buffer)) != -1;) {
                        total += count;
                        if (total > 1024L * 1024 * 1024) throw new IllegalStateException("Fixture archive too large");
                        output.write(buffer, 0, count);
                    }
                }
                entries++;
            }
        }
        if (entries != manifest.getInt("entries")) throw new IllegalStateException("Incomplete fixture archive");
        return root;
    }
}
