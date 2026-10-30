package ai.comma.openpilot.sim;

import android.content.Context;
import java.io.*;
import java.nio.file.*;
import org.json.JSONObject;

/** Optional qualification belongs to this APK, never to an earlier installation. */
final class CpuAccelerationAssets {
    static void extract(Context context,File model) throws Exception {
        File target=new File(model,"cpu-qualification.json");
        byte[] bytes;
        try(var input=context.getAssets().open("acceleration/cpu-qualification.json")) { bytes=input.readAllBytes(); }
        catch(FileNotFoundException absent) {
            if(target.exists() && !target.delete())throw new IOException("Cannot clear stale CPU qualification");
            return;
        }
        JSONObject qualification=new JSONObject(new String(bytes,java.nio.charset.StandardCharsets.UTF_8));
        if(!qualification.getBoolean("passed") || qualification.getInt("frames")!=60)
            throw new IOException("CPU candidate is not qualified");
        File temporary=new File(model,"cpu-qualification."+android.os.Process.myPid()+".tmp");
        Files.write(temporary.toPath(),bytes);
        Files.move(temporary.toPath(),target.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
    }
}
