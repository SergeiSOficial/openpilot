package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;
import android.content.Intent;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
/** Included only by tools/android/acceleration.init.gradle. */
public class AccelerationTest {
    @Test(timeout=1800000) public void compareInferenceBackendsOnTarget() throws Exception {
        var instrumentation = InstrumentationRegistry.getInstrumentation();
        var context = instrumentation.getTargetContext();
        assumeTrue("Isolated diagnostic application only", java.util.Set.of("ai.comma.openpilot.acceleration","ai.comma.openpilot.qnn").contains(context.getPackageName()));
        ModelAssets.extract(context);
        FixtureAssets.extract(context);
        var root = new File(context.getFilesDir(),"model");
        JSONObject manifest;
        try (var input=context.getAssets().open("acceleration/manifest.json")) {
            manifest = new JSONObject(new String(input.readAllBytes(),StandardCharsets.UTF_8));
        }
        for (var names=manifest.getJSONObject("sha256").keys(); names.hasNext();) {
            String name=names.next();
            if (!name.matches("[A-Za-z0-9][A-Za-z0-9_.-]*")) throw new IOException("Invalid asset path");
            File target=new File(root,name); MessageDigest digest=MessageDigest.getInstance("SHA-256");
            try (var input=context.getAssets().open("acceleration/"+name); var output=new FileOutputStream(target)) {
                byte[] block=new byte[65536];
                for(int count;(count=input.read(block))!=-1;) {digest.update(block,0,count);output.write(block,0,count);}
            }
            StringBuilder actual=new StringBuilder(); for(byte value:digest.digest())actual.append(String.format("%02x",value&255));
            assertEquals("Original model integrity",manifest.getJSONObject("sha256").getString(name),actual.toString());
        }
        Files.write(new File(context.getFilesDir(),"acceleration-build.json").toPath(),manifest.toString().getBytes(StandardCharsets.UTF_8));
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","acceleration_diagnostic");
        try(var input=instrumentation.getContext().getAssets().open("acceleration_diagnostic.py")) {
            python.getModule("builtins").callAttr("exec",new String(input.readAllBytes(),StandardCharsets.UTF_8),module.get("__dict__"));
        }
        var args=InstrumentationRegistry.getArguments();
        String backend=args.getString("backend","capabilities");
        String modelRole=args.getString("model_role","road");
        if(!java.util.Set.of("road","cabin").contains(modelRole))throw new IllegalArgumentException("Unknown model role");
        if(modelRole.equals("cabin")&&!context.getPackageName().equals("ai.comma.openpilot.qnn"))
            throw new IllegalArgumentException("Cabin QNN diagnostics require the isolated QNN application");
        if(backend.startsWith("gpu"))ModelAssets.extractLive(context);
        var activity=instrumentation.startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        try {
            QnnGraphBridge.attachActivity(activity);
            instrumentation.runOnMainSync(() -> activity.getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON));
            boolean before=visible(instrumentation,activity);
            String result=module.callAttr("run",context.getFilesDir().getAbsolutePath(),context.getApplicationInfo().nativeLibraryDir,
                backend,Integer.parseInt(args.getString("threads","2")),Integer.parseInt(args.getString("frames","60")),args.getString("attemptId",""),before,modelRole).toString();
            JSONObject report=new JSONObject(result);
            boolean after=visible(instrumentation,activity);
            report.put("foreground_at_start",before).put("foreground_at_end",after).put("timing_qualified",before && after);
            String prefix=modelRole.equals("road")?"":"cabin-";
            Files.write(new File(context.getFilesDir(),"acceleration/"+prefix+backend+"-"+args.getString("threads","2")+".json").toPath(),report.toString(2).getBytes(StandardCharsets.UTF_8));
            assertTrue(report.toString(),report.getBoolean("passed"));
        } finally {
            QnnGraphBridge.attachActivity(null);
            instrumentation.runOnMainSync(() -> {
                activity.getWindow().clearFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                activity.finish();
            });
        }
    }

    private static boolean visible(android.app.Instrumentation instrumentation,android.app.Activity activity) {
        var focused=new java.util.concurrent.atomic.AtomicBoolean();
        instrumentation.runOnMainSync(() -> focused.set(activity.hasWindowFocus()));
        return focused.get() && activity.getSystemService(android.os.PowerManager.class).isInteractive()
            && !activity.getSystemService(android.app.KeyguardManager.class).isDeviceLocked();
    }
}
