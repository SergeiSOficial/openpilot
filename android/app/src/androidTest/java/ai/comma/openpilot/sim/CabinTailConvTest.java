package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class CabinTailConvTest {
    @Test(timeout=240000) public void completePointwiseInputs() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        assumeTrue("Explicit tail arithmetic test only","true".equals(InstrumentationRegistry.getArguments().getString("cabinTail","false")));
        var context=instrumentation.getTargetContext();
        assertEquals("com.samsung.android.openpilot.shadow",context.getPackageName());
        String attempt=InstrumentationRegistry.getArguments().getString("attemptId",UUID.randomUUID().toString().replace("-",""));
        assertTrue(attempt.matches("[a-f0-9]{32}"));
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        var session=new File(context.getFilesDir(),"s/tail-"+attempt.substring(0,16));session.mkdirs();
        var destination=new File(context.getFilesDir(),"gpu-cabin-tail.json");
        Files.write(destination.toPath(),new JSONObject().put("attempt_id",attempt).put("completed",false).toString().getBytes(StandardCharsets.UTF_8));
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var common=python.getModule("types").callAttr("ModuleType","cabin_arithmetic_diagnostic");
        var module=python.getModule("types").callAttr("ModuleType","cabin_tail_diagnostic");
        try {
            try(var input=instrumentation.getContext().getAssets().open("cabin_arithmetic_diagnostic.py")) {
                python.getModule("builtins").callAttr("exec",new String(input.readAllBytes(),StandardCharsets.UTF_8),common.get("__dict__"));
            }
            try(var input=instrumentation.getContext().getAssets().open("cabin_tail_diagnostic.py")) {
                python.getModule("builtins").callAttr("exec",new String(input.readAllBytes(),StandardCharsets.UTF_8),module.get("__dict__"));
            }
            var result=module.callAttr("run",new File(context.getFilesDir(),"model").toString(),
                context.getApplicationInfo().nativeLibraryDir,session.toString(),attempt,common);
            var report=new JSONObject(python.getModule("json").callAttr("dumps",result).toString());
            report.put("timing_qualified",false);
            Files.write(destination.toPath(),report.toString(2).getBytes(StandardCharsets.UTF_8));
            assertTrue(report.toString(),report.getBoolean("completed"));
            assertTrue(report.getJSONObject("original_553").getBoolean("bit_equal"));
            assertEquals(339200,report.getInt("completed_output_values"));
            assertFalse(report.getBoolean("qualified"));
        } finally {DriverReference.close();}
    }
}
