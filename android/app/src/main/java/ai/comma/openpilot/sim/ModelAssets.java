package ai.comma.openpilot.sim;

import android.content.Context;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.io.ByteArrayOutputStream;
import org.json.JSONObject;

final class ModelAssets {
    static synchronized File extract(Context context) throws Exception {
        String prefix = "generated/model/";
        JSONObject manifest;
        try (var input = context.getAssets().open(prefix + "manifest.json")) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            for (int count; (count = input.read(buffer)) != -1;) bytes.write(buffer, 0, count);
            manifest = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name())).getJSONObject("sha256");
        }
        File root = new File(context.getFilesDir(), "model");
        if (!root.isDirectory() && !root.mkdirs()) throw new IllegalStateException("Cannot create model cache");
        var names = manifest.keys();
        while (names.hasNext()) {
            String name = names.next();
            if (!name.matches("[A-Za-z0-9_.]+")) throw new IllegalStateException("Invalid model asset name");
            File target = new File(root, name);
            File temporary = new File(root, name + "." + android.os.Process.myPid() + ".tmp");
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (var input = context.getAssets().open(prefix + name); var output = new FileOutputStream(temporary)) {
                byte[] bytes = new byte[65536];
                for (int count; (count = input.read(bytes)) != -1;) {
                    digest.update(bytes, 0, count);
                    output.write(bytes, 0, count);
                }
            }
            StringBuilder actual = new StringBuilder();
            for (byte value : digest.digest()) actual.append(String.format("%02x", value & 255));
            if (!actual.toString().equals(manifest.getString(name))) {
                temporary.delete();
                throw new IllegalStateException("Model checksum failed: " + name);
            }
            java.nio.file.Files.move(temporary.toPath(), target.toPath(), java.nio.file.StandardCopyOption.ATOMIC_MOVE,
                java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        }
        writeManifest(root,new JSONObject().put("sha256",manifest));
        CpuAccelerationAssets.extract(context,root);
        return root;
    }

    static synchronized File extractLive(Context context) throws Exception {
        File root = new File(context.getFilesDir(), "model");
        JSONObject existing = new JSONObject(new String(java.nio.file.Files.readAllBytes(new File(root, "manifest.json").toPath()), StandardCharsets.UTF_8));
        JSONObject live;
        try (var input = context.getAssets().open("generated/live/manifest.json")) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] block = new byte[4096];
            for (int count; (count = input.read(block)) != -1;) bytes.write(block, 0, count);
            live = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name())).getJSONObject("sha256");
        }
        for (var names = live.keys(); names.hasNext();) {
            String name = names.next();
            if (!name.matches("[A-Za-z0-9_.-]+")) throw new IllegalStateException("Invalid live asset name");
            File temporary = new File(root, name + ".live.tmp");
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (var input = context.getAssets().open("generated/live/" + name); var output = new FileOutputStream(temporary)) {
                byte[] block = new byte[65536];
                for (int count; (count = input.read(block)) != -1;) { digest.update(block, 0, count); output.write(block, 0, count); }
            }
            StringBuilder hash = new StringBuilder(); for (byte value : digest.digest()) hash.append(String.format("%02x", value & 255));
            if (!hash.toString().equals(live.getString(name))) { temporary.delete(); throw new IllegalStateException("Live asset checksum failed: " + name); }
            java.nio.file.Files.move(temporary.toPath(), new File(root, name).toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            existing.getJSONObject("sha256").put(name, live.getString(name));
        }
        writeManifest(root,existing);
        return root;
    }

    private static void writeManifest(File root,JSONObject manifest) throws Exception {
        File temporary=new File(root,"manifest."+android.os.Process.myPid()+".tmp");
        java.nio.file.Files.write(temporary.toPath(),manifest.toString().getBytes(StandardCharsets.UTF_8));
        java.nio.file.Files.move(temporary.toPath(),new File(root,"manifest.json").toPath(),
            java.nio.file.StandardCopyOption.ATOMIC_MOVE,java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }
}
