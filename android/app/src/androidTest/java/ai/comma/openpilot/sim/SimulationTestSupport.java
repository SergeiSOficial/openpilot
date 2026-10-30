package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import android.app.Activity;
import android.app.ActivityManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.TextView;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.function.Predicate;
import org.json.JSONObject;

final class SimulationTestSupport {
    static final Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
    static String read(File file) throws Exception { return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8); }
    static Activity launch() {
        Intent intent = new Intent(context, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        return InstrumentationRegistry.getInstrumentation().startActivitySync(intent);
    }
    private static Button button(View view, String label) {
        if (view instanceof Button && ((Button)view).getText().toString().equals(label)) return (Button)view;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) {
            Button found = button(((ViewGroup)view).getChildAt(i), label);
            if (found != null) return found;
        }
        return null;
    }
    static void press(Activity activity, String label) {
        InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> {
            Button target = button(activity.getWindow().getDecorView(), label);
            assertNotNull(label, target); assertTrue(target.performClick());
        });
    }
    static File start(Activity activity) throws Exception {
        long readyDeadline = SystemClock.elapsedRealtime()+30000;
        java.util.concurrent.atomic.AtomicBoolean ready = new java.util.concurrent.atomic.AtomicBoolean();
        do {
            InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> ready.set(ready(activity.getWindow().getDecorView())));
            if (ready.get()) break;
            Thread.sleep(50);
        } while (SystemClock.elapsedRealtime() < readyDeadline);
        assertTrue("Replay service did not become ready", ready.get());
        File pointer = new File(context.getFilesDir(), "last-replay-session.txt");
        String previous = pointer.isFile() ? read(pointer) : "";
        press(activity, "Start");
        long deadline = SystemClock.elapsedRealtime()+30000;
        do {
            if (pointer.isFile()) {
                String current = read(pointer);
                if (!current.equals(previous) && current.matches("[a-f0-9]{16}")) return new File(context.getFilesDir(), "s/"+current);
            }
            Thread.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        throw new AssertionError("Dashboard did not start a new replay session");
    }
    private static boolean ready(View view) {
        if (view instanceof TextView && ((TextView)view).getText().toString().startsWith("Ready.")) return true;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) {
            if (ready(((ViewGroup)view).getChildAt(i))) return true;
        }
        return false;
    }
    private static boolean contains(View view, String fragment) {
        if (view instanceof TextView && ((TextView)view).getText().toString().contains(fragment)) return true;
        if (view instanceof ViewGroup) for (int i = 0; i < ((ViewGroup)view).getChildCount(); i++) {
            if (contains(((ViewGroup)view).getChildAt(i), fragment)) return true;
        }
        return false;
    }
    static void awaitText(Activity activity, String fragment) throws Exception {
        java.util.concurrent.atomic.AtomicBoolean found = new java.util.concurrent.atomic.AtomicBoolean();
        long deadline = SystemClock.elapsedRealtime()+10000;
        do {
            InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> found.set(contains(activity.getWindow().getDecorView(), fragment)));
            if (found.get()) return;
            Thread.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        fail("Dashboard did not display: " + fragment);
    }
    static JSONObject await(File root, Predicate<JSONObject> condition, long limitMillis) throws Exception {
        long deadline = SystemClock.elapsedRealtime()+limitMillis;
        JSONObject report = new JSONObject();
        do {
            File file = new File(root, "progress.json");
            if (file.isFile()) {
                try { report = new JSONObject(read(file)); } catch (org.json.JSONException transientWrite) { continue; }
                if (condition.test(report)) return report;
                if (java.util.Arrays.asList("failed", "stopped").contains(report.optString("state"))) fail(report.toString(2));
            }
            Thread.sleep(100);
        } while (SystemClock.elapsedRealtime() < deadline);
        throw new AssertionError("Replay wait timed out: " + report);
    }
    static String shell(String command) throws Exception {
        ParcelFileDescriptor descriptor = InstrumentationRegistry.getInstrumentation().getUiAutomation().executeShellCommand(command);
        try (var input = new ParcelFileDescriptor.AutoCloseInputStream(descriptor)) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer = new byte[4096];
            for (int count; (count = input.read(buffer)) != -1;) bytes.write(buffer, 0, count);
            return bytes.toString(StandardCharsets.UTF_8.name()).trim();
        }
    }
    static void screenshot(File root, String name) throws Exception {
        var instrumentation = InstrumentationRegistry.getInstrumentation();
        instrumentation.waitForIdleSync();
        Thread.sleep(300); // takeScreenshot can otherwise capture the previous render-thread frame.
        Bitmap bitmap = InstrumentationRegistry.getInstrumentation().getUiAutomation().takeScreenshot();
        assertNotNull(bitmap);
        try (var output = new FileOutputStream(new File(root, name))) { assertTrue(bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)); }
        bitmap.recycle();
    }
    static int width(Activity activity) {
        java.util.concurrent.atomic.AtomicInteger width = new java.util.concurrent.atomic.AtomicInteger();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> width.set(activity.getWindow().getDecorView().getWidth()));
        return width.get();
    }
    static int height(Activity activity) {
        java.util.concurrent.atomic.AtomicInteger height = new java.util.concurrent.atomic.AtomicInteger();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> height.set(activity.getWindow().getDecorView().getHeight()));
        return height.get();
    }
    static void awaitOrientation(Activity activity, boolean landscape) throws Exception {
        long deadline = SystemClock.elapsedRealtime()+10000;
        while ((width(activity) > height(activity)) != landscape && SystemClock.elapsedRealtime() < deadline) Thread.sleep(50);
        assertEquals("Dashboard did not adopt the requested window orientation", landscape, width(activity) > height(activity));
    }
    static void assertLandscapeDashboard(Activity activity) {
        InstrumentationRegistry.getInstrumentation().runOnMainSync(() -> {
            View root = activity.getWindow().getDecorView();
            android.graphics.Rect camera = new android.graphics.Rect(), panel = new android.graphics.Rect();
            assertTrue(root.findViewWithTag("simulation-camera").getGlobalVisibleRect(camera));
            assertTrue(root.findViewWithTag("simulation-panel").getGlobalVisibleRect(panel));
            assertTrue("Camera and dashboard panel must be side by side", camera.right <= panel.left);
            for (String label : new String[]{"Start", "Stop", "Reset", "Export"}) {
                Button control = button(root, label);
                android.graphics.Rect visible = new android.graphics.Rect();
                assertNotNull(label, control);
                assertTrue(label + " is off screen", control.getGlobalVisibleRect(visible));
                assertEquals(label + " is clipped horizontally", control.getWidth(), visible.width());
                assertEquals(label + " is clipped vertically", control.getHeight(), visible.height());
                assertEquals(label + " wraps", 1, control.getLineCount());
            }
        });
    }
    static void fold(File root, String phase) throws Exception {
        File request = new File(context.getFilesDir(), "fold-request.json");
        JSONObject value = new JSONObject().put("session", root.getName()).put("phase", phase);
        Files.write(request.toPath(), value.toString().getBytes(StandardCharsets.UTF_8));
        File acknowledgement = new File(context.getFilesDir(), "fold-ack-"+root.getName()+"-"+phase);
        long deadline = SystemClock.elapsedRealtime()+30000;
        while (!acknowledgement.isFile() && SystemClock.elapsedRealtime() < deadline) Thread.sleep(50);
        assertTrue("Use tools/android/test-emulator.ps1 for emulator console fold commands", acknowledgement.isFile());
    }
    static void finish(Activity activity) {
        InstrumentationRegistry.getInstrumentation().runOnMainSync(activity::finish);
        InstrumentationRegistry.getInstrumentation().waitForIdleSync();
    }
    static void assertWorkersStopped() throws Exception {
        ActivityManager manager = (ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);
        long deadline = SystemClock.elapsedRealtime()+10000;
        String remaining;
        do {
            StringBuilder names = new StringBuilder();
            var processes = manager.getRunningAppProcesses();
            if (processes != null) for (var process : processes) {
                if (process.processName.startsWith(context.getPackageName()+":")) names.append(process.processName).append(' ');
            }
            remaining = names.toString();
            if (remaining.isEmpty()) return;
            Thread.sleep(50);
        } while (SystemClock.elapsedRealtime() < deadline);
        fail("Orphan Android worker processes: " + remaining);
    }
}
