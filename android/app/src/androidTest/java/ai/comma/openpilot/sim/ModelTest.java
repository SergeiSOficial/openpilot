package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.util.UUID;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class ModelTest {
    @Test(timeout=120000) public void packagedDrivingModelMatchesHostReference() throws Exception {
        if (androidx.test.platform.app.InstrumentationRegistry.getArguments().getString("modelDiagnostic", "false").equals("true")) {
            var instrumentation = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation();
            var context = instrumentation.getTargetContext();
            ModelAssets.extract(context);
            FixtureAssets.extract(context);
            if (!com.chaquo.python.Python.isStarted())
                com.chaquo.python.Python.start(new com.chaquo.python.android.AndroidPlatform(context));
            var python = com.chaquo.python.Python.getInstance();
            var module = python.getModule("types").callAttr("ModuleType", "model_diagnostic");
            try (var input = instrumentation.getContext().getAssets().open("model_diagnostic.py")) {
                python.getModule("builtins").callAttr("exec", new String(input.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8), module.get("__dict__"));
            }
            module.callAttr("run", context.getFilesDir().getAbsolutePath(), context.getApplicationInfo().nativeLibraryDir);
            return;
        }
        String session = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        try (RuntimeTest.BoundWorker bound = new RuntimeTest.BoundWorker(WorkerService.Model.class)) {
            JSONObject result = new JSONObject(bound.get().probeModel(session));
            assertTrue(result.toString(), result.getBoolean("passed"));
            assertEquals("2.5.3", result.getString("numpy"));
        }
    }
}
