package ai.comma.openpilot.sim;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.res.Configuration;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.text.TextUtils;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.File;
import java.nio.file.Files;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.json.JSONObject;

public class MainActivity extends Activity {
    private TextView status;
    private SimulationView camera;
    private LinearLayout dashboard, panel;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private volatile IWorker worker;
    private boolean bound, polling, pendingStart, startRequested;
    private volatile boolean busy;
    private int displayedFrame = -1;
    private String session = newSession();
    private static String newSession() { return UUID.randomUUID().toString().replace("-", "").substring(0, 16); }
    private File sessionRoot() { return new File(getFilesDir(), "s/" + session); }
    private void show(String text) { runOnUiThread(() -> status.setText(text)); }

    private final ServiceConnection connection = new ServiceConnection() {
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            worker = IWorker.Stub.asInterface(binder);
            show("Ready. Start the 60-frame simulation.");
            if (pendingStart) { pendingStart = false; startSimulation(); }
        }
        @Override public void onServiceDisconnected(ComponentName name) { worker = null; }
        @Override public void onBindingDied(ComponentName name) { worker = null; }
    };

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (getIntent().hasExtra("mode")) {
            Intent live = new Intent(this, LiveActivity.class).putExtras(getIntent());
            getIntent().removeExtra("mode");
            startActivity(live);
        }
        if (state != null) session = state.getString("session", session);
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(10);
        layout.setPadding(pad, pad, pad, pad);
        layout.setOnApplyWindowInsetsListener((view, insets) -> {
            android.graphics.Insets bars = insets.getInsets(android.view.WindowInsets.Type.systemBars());
            view.setPadding(pad+bars.left, pad+bars.top, pad+bars.right, pad+bars.bottom);
            return insets;
        });
        TextView title = new TextView(this); title.setText("openpilot · Android simulation"); title.setTextSize(18);
        title.setSingleLine(true); title.setEllipsize(TextUtils.TruncateAt.END);
        LinearLayout toolbar = new LinearLayout(this); toolbar.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        if (BuildConfig.APPLICATION_ID.startsWith("com.samsung.")) {
            Button live = new Button(this); live.setText("Live shadow"); live.setAllCaps(false);
            live.setOnClickListener(view -> startActivity(new Intent(this, LiveActivity.class)));
            toolbar.addView(live);
        }
        Button panda = new Button(this); panda.setText("Red panda"); panda.setAllCaps(false);
        panda.setOnClickListener(view -> startActivity(new Intent(this, PandaActivity.class)));
        toolbar.addView(panda); layout.addView(toolbar);
        dashboard = new LinearLayout(this);
        layout.addView(dashboard, new LinearLayout.LayoutParams(-1, 0, 1));
        camera = new SimulationView(this);
        camera.setTag("simulation-camera");
        camera.setContentDescription("Recorded road camera and model path");
        dashboard.addView(camera);
        panel = new LinearLayout(this); panel.setOrientation(LinearLayout.VERTICAL); panel.setTag("simulation-panel");
        dashboard.addView(panel);
        status = new TextView(this); status.setTextIsSelectable(true); status.setTextSize(14);
        ScrollView details = new ScrollView(this); details.setFillViewport(true); details.addView(status);
        panel.addView(details, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout controls = new LinearLayout(this);
        button(controls, "Start", this::startSimulation); button(controls, "Stop", () -> stopWorker("Stopped"));
        button(controls, "Reset", () -> reset(false)); button(controls, "Export", this::exportReport);
        panel.addView(controls);
        arrangeDashboard(getResources().getConfiguration());
        setContentView(layout);
    }

    private int dp(int value) { return Math.round(value*getResources().getDisplayMetrics().density); }

    private void arrangeDashboard(Configuration configuration) {
        boolean landscape = configuration.orientation == Configuration.ORIENTATION_LANDSCAPE;
        dashboard.setOrientation(landscape ? LinearLayout.HORIZONTAL : LinearLayout.VERTICAL);
        camera.setLayoutParams(landscape ? new LinearLayout.LayoutParams(0, -1, 1.65f)
                                        : new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout.LayoutParams details = landscape ? new LinearLayout.LayoutParams(0, -1, 1)
                                                      : new LinearLayout.LayoutParams(-1, 0, 1);
        if (landscape) details.leftMargin = dp(10); else details.topMargin = dp(10);
        panel.setLayoutParams(details);
    }

    @Override public void onConfigurationChanged(Configuration configuration) {
        super.onConfigurationChanged(configuration);
        arrangeDashboard(configuration);
    }

    private void button(LinearLayout row, String label, Runnable action) {
        Button button = new Button(this); button.setText(label); button.setOnClickListener(view -> action.run());
        button.setAllCaps(false); button.setSingleLine(true); button.setTextSize(13); button.setMinWidth(0);
        button.setPadding(dp(4), 0, dp(4), 0);
        row.addView(button, new LinearLayout.LayoutParams(0, -2, 1));
    }

    private void startSimulation() {
        if (startRequested) { show("Simulation is already running."); return; }
        IWorker current = worker;
        if (current == null || new File(sessionRoot(), "progress.json").isFile()) { reset(true); return; }
        startRequested = true;
        executor.submit(() -> {
            try {
                Files.write(new File(getFilesDir(), "last-replay-session.txt").toPath(), session.getBytes(java.nio.charset.StandardCharsets.UTF_8));
                current.start(session, "replay");
            }
            catch (Exception failure) { show("Start failed: " + failure); }
        });
        show("Preparing verified model and recorded camera assets…");
    }

    private final Runnable poll = new Runnable() {
        @Override public void run() {
            if (!polling) return;
            if (!busy) {
                busy = true;
                executor.submit(() -> {
                    try {
                        File progress = new File(sessionRoot(), "progress.json");
                        if (progress.isFile()) {
                            JSONObject report = new JSONObject(new String(Files.readAllBytes(progress.toPath()), java.nio.charset.StandardCharsets.UTF_8));
                            if (java.util.Arrays.asList("completed", "failed", "stopped").contains(report.getString("state"))) {
                                runOnUiThread(() -> startRequested = false);
                            }
                            StringBuilder text = new StringBuilder(report.getString("state"));
                            text.append(" · ").append(report.optInt("frames")).append(" / 60 frames · ")
                                .append(Math.round(report.optDouble("elapsed_seconds"))).append(" s\n");
                            if (report.has("error")) text.append(report.getString("error")).append('\n');
                            if (report.optBoolean("verification_passed")) text.append("Desktop reference comparison passed\n");
                            JSONObject actuators = report.optJSONObject("actuators");
                            if (actuators != null) text.append(String.format(java.util.Locale.ROOT,
                                "Actuators · %s\nAcceleration %.3f m/s²   Torque %.3f\nCurvature %.6f 1/m\n",
                                actuators.optString("longControlState"), actuators.optDouble("accel"),
                                actuators.optDouble("torque"), actuators.optDouble("curvature")));
                            JSONObject counts = report.optJSONObject("counts");
                            if (counts != null) text.append(String.format(java.util.Locale.ROOT,
                                "Model %d → Plan %d → Control %d\nSimulated CAN messages: %d\n\n",
                                counts.optInt("modelV2"), counts.optInt("longitudinalPlan"), counts.optInt("carControl"), counts.optInt("sendcan")));
                            JSONObject workers = report.optJSONObject("workers");
                            if (workers != null) for (var names = workers.keys(); names.hasNext();) {
                                String name = names.next(); text.append(name).append(": ").append(workers.getJSONObject(name).getString("state")).append('\n');
                            }
                            show(text.toString());
                            int frame = report.optInt("frame_id", -1);
                            if (frame >= 0 && frame != displayedFrame) {
                                var image = SimulationView.loadFrame(getFilesDir(), frame);
                                displayedFrame = frame;
                                runOnUiThread(() -> camera.update(image, report.optJSONObject("path")));
                            }
                        } else if (worker != null) {
                            JSONObject state = new JSONObject(worker.status());
                            if (state.getString("state").equals("failed")) show(state.getString("error"));
                        }
                    } catch (Exception failure) { show("Dashboard: " + failure); }
                    finally { busy = false; }
                });
            }
            handler.postDelayed(this, 500);
        }
    };

    private void bindWorker() {
        if (!bound) bound = bindService(new Intent(this, WorkerService.Replay.class), connection, Context.BIND_AUTO_CREATE);
    }
    private void stopWorker(String reason) {
        startRequested = false;
        IWorker current = worker; worker = null;
        if (current != null) { try { current.stop(); } catch (Exception ignored) {} }
        if (bound) { unbindService(connection); bound = false; }
        show(reason + ". Reset for a new session.");
    }
    private static void deleteSession(File file, File allowed) throws Exception {
        if (Files.isSymbolicLink(file.toPath())) {
            if (!file.getAbsolutePath().startsWith(allowed.getAbsolutePath()+File.separator)) throw new IllegalStateException("Invalid session link");
            Files.delete(file.toPath());
            return;
        }
        if (!file.getCanonicalPath().startsWith(allowed.getCanonicalPath()+File.separator)) throw new IllegalStateException("Invalid session path");
        File[] children = file.listFiles();
        if (children != null) for (File child : children) deleteSession(child, allowed);
        Files.deleteIfExists(file.toPath());
    }
    private void reset(boolean restart) {
        IWorker current = worker;
        File previous = sessionRoot();
        stopWorker("Resetting");
        executor.submit(() -> {
            try {
                long deadline = android.os.SystemClock.elapsedRealtime()+5000;
                while (current != null && current.asBinder().pingBinder() && android.os.SystemClock.elapsedRealtime() < deadline) Thread.sleep(25);
                if (current != null && current.asBinder().pingBinder()) throw new IllegalStateException("Replay worker did not terminate");
                deleteSession(previous, new File(getFilesDir(), "s"));
                runOnUiThread(() -> { session = newSession(); displayedFrame = -1; camera.update(null, null); pendingStart = restart; bindWorker(); });
            } catch (Exception failure) { show("Reset failed: " + failure); }
        });
    }
    private void exportReport() {
        if (!new File(sessionRoot(), "verification.json").isFile()) { show("A verification report is available after the run finishes."); return; }
        Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/json")
            .addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE, "openpilot-"+session+".json");
        startActivityForResult(intent, 1);
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == 1 && result == RESULT_OK && data != null) {
            executor.submit(() -> {
                try (var output = getContentResolver().openOutputStream(data.getData())) {
                    output.write(Files.readAllBytes(new File(sessionRoot(), "verification.json").toPath()));
                    show("Verification report exported.");
                } catch (Exception failure) { show("Export failed: " + failure); }
            });
        }
    }
    @Override protected void onStart() { super.onStart(); bindWorker(); polling = true; handler.post(poll); }
    @Override protected void onStop() {
        polling = false; handler.removeCallbacks(poll);
        if (!isChangingConfigurations()) stopWorker("Backgrounded");
        super.onStop();
    }
    @Override protected void onSaveInstanceState(Bundle out) { out.putString("session", session); super.onSaveInstanceState(out); }
    @Override protected void onDestroy() { executor.shutdownNow(); super.onDestroy(); }
}
