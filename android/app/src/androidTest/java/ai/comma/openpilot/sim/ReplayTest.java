package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class ReplayTest {
    @Test public void sixtyRecordedFramesRunThroughRealAndroidDaemons() throws Exception {
        var context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        String session = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        Files.write(new File(context.getFilesDir(), "last-replay-session.txt").toPath(), session.getBytes(StandardCharsets.UTF_8));
        File root = new File(context.getFilesDir(), "s/"+session);
        try (RuntimeTest.BoundWorker bound = new RuntimeTest.BoundWorker(WorkerService.Replay.class)) {
            IWorker worker = bound.get(); worker.start(session, "replay");
            long deadline = android.os.SystemClock.elapsedRealtime()+1800000;
            JSONObject state;
            do {
                Thread.sleep(500);
                state = new JSONObject(worker.status());
                if (state.getString("state").equals("failed")) fail(state.toString(2));
                if (state.getString("state").equals("finished")) break;
            } while (android.os.SystemClock.elapsedRealtime() < deadline);
            assertEquals("30-minute replay deadline exceeded", "finished", state.getString("state"));
            JSONObject report = new JSONObject(new String(Files.readAllBytes(new File(root, "verification.json").toPath()), StandardCharsets.UTF_8));
            assertTrue(report.toString(2), report.getBoolean("replay_passed"));
            assertTrue(report.toString(2), report.getBoolean("verification_passed"));
            assertEquals(60, report.getInt("frames"));
            assertEquals(60, report.getJSONObject("counts").getInt("longitudinalPlan"));
            assertTrue(report.getJSONObject("counts").getInt("sendcan") > 0);
        }
    }
}
