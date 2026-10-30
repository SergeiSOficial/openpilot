package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import static ai.comma.openpilot.sim.SimulationTestSupport.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import android.app.Activity;
import java.io.File;
import java.nio.file.Files;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class LifecycleTest {
    @Test public void foldingAndRotationPreserveSixtyFrameSimulation() throws Exception {
        if (android.os.Build.MODEL.startsWith("SM-F926")) {
            foldedPhoneRotationPreservesSimulation();
            return;
        }
        Activity activity = launch();
        try {
            File root = start(activity);
            JSONObject before = await(root, report -> report.optInt("frames") >= 3, 60000);
            int pid = before.getJSONObject("workers").getJSONObject("modeld").getInt("pid");
            int openedWidth = width(activity);
            int openedHeight = height(activity);
            screenshot(root, "dashboard-open.png");
            assertTrue(shell("cmd device_state print-states").contains("CLOSED"));
            shell("cmd device_state state reset");
            fold(root, "fold");
            Thread.sleep(1500);
            assertEquals("1", shell("cmd device_state print-state"));
            int foldedWidth = width(activity);
            int foldedHeight = height(activity);
            assertTrue("Folding did not resize the Android window", (long)foldedWidth*foldedHeight < (long)openedWidth*openedHeight);
            screenshot(root, "dashboard-folded.png");
            fold(root, "unfold");
            Thread.sleep(1000);
            assertEquals("3", shell("cmd device_state print-state"));
            shell("wm user-rotation lock 1");
            Thread.sleep(1500);
            assertTrue(shell("wm user-rotation").contains("1"));
            awaitOrientation(activity, true);
            assertLandscapeDashboard(activity);
            screenshot(root, "dashboard-rotated.png");
            JSONObject after = await(root, report -> report.optInt("frames") >= 8, 60000);
            assertEquals("Model worker restarted during fold/rotation", pid, after.getJSONObject("workers").getJSONObject("modeld").getInt("pid"));
            JSONObject done = await(root, report -> report.optString("state").equals("completed"), 1800000);
            assertTrue(done.toString(2), done.getBoolean("verification_passed"));
            assertEquals(60, done.getJSONObject("counts").getInt("longitudinalPlan"));
            awaitText(activity, "Desktop reference comparison passed");
            screenshot(root, "dashboard-completed.png");
            Files.write(new File(root, "lifecycle.json").toPath(), new JSONObject()
                .put("folded", true).put("unfolded", true).put("rotated", true).put("worker_preserved", true)
                .put("opened_width", openedWidth).put("folded_width", foldedWidth)
                .put("opened_height", openedHeight).put("folded_height", foldedHeight).put("landscape_main", true)
                .put("controls_visible", true)
                .put("emulator_viewport_workaround", new File(context.getFilesDir(), "fold-viewport-workaround-"+root.getName()).isFile())
                .put("verification_passed", true).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            Files.write(new File(context.getFilesDir(), "last-lifecycle-session.txt").toPath(), root.getName().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        } finally {
            shell("cmd device_state state reset"); shell("wm user-rotation free");
            finish(activity); assertWorkersStopped();
        }
    }

    private void foldedPhoneRotationPreservesSimulation() throws Exception {
        assertTrue(shell("cmd device_state print-states").contains("CLOSED"));
        assertEquals("Physical Fold 3 must remain closed", "0", shell("cmd device_state print-state"));
        String displayBefore = shell("wm size");
        Activity activity = launch();
        int orientationBefore = activity.getRequestedOrientation();
        try {
            var instrumentation = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation();
            instrumentation.runOnMainSync(() -> activity.getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON));
            assertEquals(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE, orientationBefore);
            awaitOrientation(activity, true);
            assertLandscapeDashboard(activity);
            File root = start(activity);
            JSONObject before = await(root, report -> report.optInt("frames") >= 3, 60000);
            int pid = before.getJSONObject("workers").getJSONObject("modeld").getInt("pid");
            int coverWidth = width(activity);
            screenshot(root, "dashboard-folded.png");
            instrumentation.runOnMainSync(() -> activity.setRequestedOrientation(android.content.pm.ActivityInfo.SCREEN_ORIENTATION_PORTRAIT));
            awaitOrientation(activity, false);
            screenshot(root, "dashboard-rotated.png");
            instrumentation.runOnMainSync(() -> activity.setRequestedOrientation(orientationBefore));
            awaitOrientation(activity, true);
            assertLandscapeDashboard(activity);
            JSONObject after = await(root, report -> report.optInt("frames") >= 8, 60000);
            assertEquals("Model worker restarted during cover-screen rotation", pid, after.getJSONObject("workers").getJSONObject("modeld").getInt("pid"));
            JSONObject done = await(root, report -> report.optString("state").equals("completed"), 1800000);
            assertTrue(done.toString(2), done.getBoolean("verification_passed"));
            assertEquals(60, done.getJSONObject("counts").getInt("longitudinalPlan"));
            awaitText(activity, "Desktop reference comparison passed");
            screenshot(root, "dashboard-completed.png");
            assertEquals(displayBefore, shell("wm size"));
            assertEquals("0", shell("cmd device_state print-state"));
            Files.write(new File(root, "lifecycle.json").toPath(), new JSONObject()
                .put("physical_device", android.os.Build.MODEL).put("folded_only", true)
                .put("physical_hinge_transition_tested", false).put("rotated", true).put("worker_preserved", true)
                .put("landscape_main", true).put("portrait_fallback", true).put("controls_visible", true)
                .put("cover_width", coverWidth).put("viewport_override_changed", false)
                .put("verification_passed", true).toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            Files.write(new File(context.getFilesDir(), "last-lifecycle-session.txt").toPath(), root.getName().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        } finally {
            androidx.test.platform.app.InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> activity.setRequestedOrientation(orientationBefore));
            finish(activity); assertWorkersStopped();
        }
    }

    @Test public void backgroundingAndRepeatedResetTerminateAllWorkers() throws Exception {
        Activity activity = launch();
        try {
            for (int cycle = 0; cycle < 2; cycle++) {
                File root = start(activity);
                await(root, report -> report.optInt("frames") >= 2, 60000);
                press(activity, "Stop");
                assertWorkersStopped();
                assertEquals("stopped", new JSONObject(read(new File(root, "verification.json"))).getString("state"));
                press(activity, "Reset");
                long deadline = android.os.SystemClock.elapsedRealtime()+10000;
                while (root.exists() && android.os.SystemClock.elapsedRealtime() < deadline) Thread.sleep(50);
                assertFalse("Reset retained old session state", root.exists());
                Thread.sleep(300);
            }
            File root = start(activity);
            await(root, report -> report.optInt("frames") >= 2, 60000);
            shell("input keyevent KEYCODE_HOME");
            assertWorkersStopped();
            assertEquals("stopped", new JSONObject(read(new File(root, "verification.json"))).getString("state"));
        } finally { finish(activity); assertWorkersStopped(); }
    }

    @Test public void requiredWorkerDeathStopsTheSession() throws Exception {
        Activity activity = launch();
        try {
            File root = start(activity);
            JSONObject report = await(root, value -> value.optInt("frames") >= 2, 60000);
            int pid = report.getJSONObject("workers").getJSONObject("modeld").getInt("pid");
            android.os.Process.killProcess(pid);
            JSONObject failure = await(root, value -> value.optString("state").equals("failed"), 15000);
            assertTrue(failure.getString("error").contains("modeld"));
            assertFalse(failure.optBoolean("verification_passed"));
            press(activity, "Stop"); assertWorkersStopped();
        } finally { finish(activity); assertWorkersStopped(); }
    }

    @Test public void corruptedFrameIsRejectedBeforeInference() throws Exception {
        Activity activity = launch();
        try {
            File root = start(activity);
            await(root, report -> report.optInt("frames") >= 2, 60000);
            File frame = new File(context.getFilesDir(), "fixture/narrowRoadCameraState/0010.nv12");
            Files.write(frame.toPath(), new byte[]{1, 2, 3});
            JSONObject failure = await(root, report -> report.optString("state").equals("failed"), 60000);
            assertTrue(failure.getString("error").contains("Corrupted fixture buffer"));
            press(activity, "Stop"); assertWorkersStopped();
        } finally { finish(activity); assertWorkersStopped(); FixtureAssets.extract(context); }
    }
}
