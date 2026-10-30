package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import android.content.Intent;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.nio.file.Files;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class OptimizedReplayTest {
    @Test(timeout=1800000) public void qualifiedCpuRunsFullDaemonReplay() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        var context=instrumentation.getTargetContext();
        ModelAssets.extract(context);
        assertTrue("Install the qualified CPU build",new File(context.getFilesDir(),"model/cpu-qualification.json").isFile());
        var activity=instrumentation.startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        try {
            new ReplayTest().sixtyRecordedFramesRunThroughRealAndroidDaemons();
            String session=new String(Files.readAllBytes(new File(context.getFilesDir(),"last-replay-session.txt").toPath())).trim();
            var backend=new JSONObject(new String(Files.readAllBytes(new File(context.getFilesDir(),"s/"+session+"/cpu-backend.json").toPath())));
            assertEquals("CPU_parallel",backend.getString("backend"));
            assertEquals(60,backend.getInt("reference_frames"));
        } finally {instrumentation.runOnMainSync(activity::finish);}
    }
}
