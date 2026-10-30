package ai.comma.openpilot.sim;

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import android.os.Process;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** One interpreter per Android process; daemon execution never occupies the Binder or UI thread. */
public abstract class WorkerService extends Service {
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private volatile String state = "idle";
    private volatile String error = "";
    private volatile String daemonName = "";
    private volatile DaemonSupervisor supervisor;
    private volatile File currentRoot;
    private volatile boolean stopping;
    private volatile Future<?> running;

    private void saveTerminalReport(String terminalState) {
        File root = currentRoot;
        if (root == null || !(daemonName.equals("replay") || daemonName.equals("live"))) return;
        try {
            File progress = new File(root, "progress.json");
            JSONObject report = progress.isFile()
                ? new JSONObject(new String(java.nio.file.Files.readAllBytes(progress.toPath()), java.nio.charset.StandardCharsets.UTF_8))
                : new JSONObject().put("schema", 1).put("frames", 0);
            if(!report.optString("state").equals("failed"))report.put("state", terminalState);
            if(error!=null&&!error.isEmpty())report.put("error", error);
            report.put("verification_passed", false);
            byte[] bytes = report.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
            java.nio.file.Files.write(new File(root, "verification.json").toPath(), bytes);
            java.nio.file.Files.write(progress.toPath(), bytes);
        } catch (Exception failure) { android.util.Log.e("OpenpilotWorker", "Cannot save terminal report", failure); }
    }

    private synchronized void terminate() {
        boolean interrupted = !state.equals("finished") && !state.equals("failed");
        stopping = true;
        try {
          if(daemonName.equals("sensord"))cleanupSensors();
          if(daemonName.equals("live"))LivePerformance.close();
          if (supervisor != null) supervisor.close();
          if (interrupted) {
            // Let replay observe intentional shutdown and finish its report before
            // the service dies. Startup/native waits remain bounded by this join.
            Future<?> task = running;
            if (task != null && daemonName.equals("replay")) {
                try { task.get(2, TimeUnit.SECONDS); } catch (Exception ignored) {}
            }
            state = error.isEmpty()?"stopped":"failed";
            saveTerminalReport(state);
          }
        } finally {Process.killProcess(Process.myPid());}
    }

    private void cleanupSensors() {
        try {LiveSensorBridge.stop();}
        catch(Throwable failure){error="Sensor cleanup failed: "+failure;state="failed";android.util.Log.e("OpenpilotSensors",error,failure);}
        finally {LiveSensorBridge.saveCleanup(currentRoot);}
    }

    private synchronized Python python() {
        if (!Python.isStarted()) Python.start(new AndroidPlatform(this));
        return Python.getInstance();
    }

    private File sessionRoot(String session) {
        if (!session.matches("[a-f0-9]{16}")) throw new IllegalArgumentException("Invalid session identifier");
        File root = new File(getFilesDir(), "s/" + session);
        if (!root.isDirectory() && !root.mkdirs()) throw new IllegalStateException("Cannot create session directory");
        return root;
    }

    private final IWorker.Stub binder = new IWorker.Stub() {
        @Override public synchronized void start(String session, String daemon) {
            startConfigured(session, daemon, "{}");
        }
        @Override public synchronized void startConfigured(String session, String daemon, String environment) {
            if (!state.equals("idle")) throw new IllegalStateException("Start requires a fresh worker");
            final String root = sessionRoot(session).getAbsolutePath();
            currentRoot = new File(root);
            daemonName = daemon;
            state = "starting";
            running = executor.submit(() -> {
                try {
                    if(daemon.equals("sensord"))LiveSensorBridge.start(WorkerService.this);
                    if (daemon.equals("modeld") || daemon.equals("replay") || daemon.equals("live")) ModelAssets.extract(WorkerService.this);
                    if (daemon.equals("live")) {
                        LivePerformance.initialize(WorkerService.this);
                        ModelAssets.extractLive(WorkerService.this);
                        if(new JSONObject(environment).optString("OPENPILOT_ANDROID_MODE").equals("drivergpucheck"))FixtureAssets.extract(WorkerService.this);
                        supervisor = new DaemonSupervisor(WorkerService.this, session);
                    }
                    if (daemon.equals("replay")) {
                        FixtureAssets.extract(WorkerService.this);
                        supervisor = new DaemonSupervisor(WorkerService.this, session);
                    }
                    state = "running";
                    python().getModule("android_runtime.worker").callAttr("run", root, daemon,
                        getApplicationInfo().nativeLibraryDir, environment, supervisor);
                    state = stopping ? "stopped" : "finished";
                } catch (Throwable failure) {
                    if (!stopping) {
                        android.util.Log.e("OpenpilotWorker", "Worker failed: " + daemon, failure);
                        error = failure.toString();
                        state = "failed";
                        if (!new File(root, "verification.json").isFile()) saveTerminalReport("failed");
                    }
                } finally {
                    if(daemon.equals("sensord"))cleanupSensors();
                    if(daemon.equals("live")){LivePerformance.close();DriverReference.close();}
                    if (supervisor != null) supervisor.close();
                }
            });
        }
        @Override public String status() {
            try {
                return new JSONObject().put("pid", Process.myPid()).put("daemon", daemonName)
                    .put("state", state).put("error", error).toString();
            } catch (Exception failure) {
                throw new IllegalStateException(failure);
            }
        }
        @Override public String checkRuntime(String session) {
            try { ModelAssets.extract(WorkerService.this); }
            catch (Exception failure) { throw new IllegalStateException(failure); }
            return python().getModule("android_runtime.worker").callAttr("check", sessionRoot(session).getAbsolutePath(), getApplicationInfo().nativeLibraryDir).toString();
        }
        @Override public String probeIpc(String session, boolean publisher) {
            return NativeBridge.ipc(sessionRoot(session).getAbsolutePath(), publisher);
        }
        @Override public String probeModel(String session) {
            try {
                python().getModule("android_runtime.worker").callAttr("configure", sessionRoot(session).getAbsolutePath());
                return python().getModule("android_runtime.model_probe").callAttr("run",
                    ModelAssets.extract(WorkerService.this).getAbsolutePath(), getApplicationInfo().nativeLibraryDir).toString();
            } catch (Exception failure) {
                android.util.Log.e("OpenpilotWorker", "Model probe failed", failure);
                throw new IllegalStateException(failure);
            }
        }
        @Override public String probeSchema(String session) {
            try { ModelAssets.extract(WorkerService.this); }
            catch (Exception failure) { throw new IllegalStateException(failure); }
            return python().getModule("android_runtime.worker").callAttr("schema_probe",
                sessionRoot(session).getAbsolutePath(), getApplicationInfo().nativeLibraryDir).toString();
        }
        @Override public void stop() {
            terminate();
        }
    };

    @Override public IBinder onBind(Intent intent) { return binder; }
    @Override public boolean onUnbind(Intent intent) {
        terminate();
        return false;
    }
    @Override public void onDestroy() { executor.shutdownNow(); super.onDestroy(); }

    public static class Replay extends WorkerService {}
    public static class Live extends WorkerService {}
    public static class Sensors extends WorkerService {}
    public static class Model extends WorkerService {}
    public static class Car extends WorkerService {}
    public static class Radar extends WorkerService {}
    public static class Planner extends WorkerService {}
    public static class Controls extends WorkerService {}
    public static class Selfdrive extends WorkerService {}
    public static class Calibration extends WorkerService {}
    public static class Location extends WorkerService {}
    public static class Params extends WorkerService {}
    public static class Lag extends WorkerService {}
    public static class Torque extends WorkerService {}
    public static class Monitoring extends WorkerService {}
}
