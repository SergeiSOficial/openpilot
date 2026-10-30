package ai.comma.openpilot.sim;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.IBinder;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;

/** Android owns worker processes. Python only schedules messages and waits for IPC events. */
public final class DaemonSupervisor implements AutoCloseable {
    private final Context context;
    private final String session;
    private final Map<String, Binding> workers = new LinkedHashMap<>();
    private volatile boolean closing;

    DaemonSupervisor(Context context, String session) { this.context = context; this.session = session; }

    private static Class<?> service(String daemon) {
        return switch (daemon) {
            case "modeld" -> WorkerService.Model.class;
            case "sensord" -> WorkerService.Sensors.class;
            case "card" -> WorkerService.Car.class;
            case "radard" -> WorkerService.Radar.class;
            case "plannerd" -> WorkerService.Planner.class;
            case "controlsd" -> WorkerService.Controls.class;
            case "selfdrived" -> WorkerService.Selfdrive.class;
            case "calibrationd" -> WorkerService.Calibration.class;
            case "locationd" -> WorkerService.Location.class;
            case "paramsd" -> WorkerService.Params.class;
            case "lagd" -> WorkerService.Lag.class;
            case "torqued" -> WorkerService.Torque.class;
            case "dmonitoringd" -> WorkerService.Monitoring.class;
            default -> throw new IllegalArgumentException("Daemon is not in the Android simulation allowlist: " + daemon);
        };
    }

    private static final class Binding implements ServiceConnection {
        final CompletableFuture<IWorker> connected = new CompletableFuture<>();
        volatile boolean died;
        volatile boolean stopped;
        @Override public void onServiceConnected(ComponentName name, IBinder binder) {
            connected.complete(IWorker.Stub.asInterface(binder));
        }
        @Override public void onServiceDisconnected(ComponentName name) { died = true; }
        @Override public void onBindingDied(ComponentName name) { died = true; }
        @Override public void onNullBinding(ComponentName name) {
            connected.completeExceptionally(new IllegalStateException("Worker returned no Binder"));
        }
    }

    public int startWorker(String daemon, String environment) throws Exception {
        Binding binding = new Binding();
        synchronized (workers) {
            if (closing || workers.containsKey(daemon)) throw new IllegalStateException("Worker already started or session stopped");
            workers.put(daemon, binding);
        }
        if (!context.bindService(new Intent(context, service(daemon)), binding, Context.BIND_AUTO_CREATE)) {
            throw new IllegalStateException("Cannot bind " + daemon);
        }
        IWorker worker = binding.connected.get(30, TimeUnit.SECONDS);
        if (closing) throw new IllegalStateException("Session stopped during worker startup");
        worker.startConfigured(session, daemon, environment);
        return new JSONObject(worker.status()).getInt("pid");
    }

    public String workerStatus(String daemon) throws Exception {
        Binding binding;
        synchronized (workers) { binding = workers.get(daemon); }
        if (binding == null || binding.stopped || binding.died) {
            return new JSONObject().put("state", binding != null && binding.stopped ? "stopped" : "dead").put("daemon", daemon).toString();
        }
        try { return binding.connected.get(30, TimeUnit.SECONDS).status(); }
        catch (android.os.RemoteException failure) {
            binding.died = true;
            return new JSONObject().put("state", "dead").put("daemon", daemon).put("error", failure.toString()).toString();
        }
    }

    public String health() throws Exception {
        JSONObject result = new JSONObject();
        String[] names;
        synchronized (workers) { names = workers.keySet().toArray(new String[0]); }
        for (String name : names) result.put(name, new JSONObject(workerStatus(name)));
        return result.toString();
    }

    public boolean isStopping() { return closing; }

    public void stopWorker(String daemon) {
        Binding binding;
        synchronized (workers) { binding = workers.get(daemon); }
        if (binding == null || binding.stopped) return;
        binding.stopped = true;
        IWorker worker = binding.connected.getNow(null);
        if (worker != null) {
            try { worker.stop(); } catch (Exception ignored) { /* Killing a service closes its Binder. */ }
        }
        try { context.unbindService(binding); } catch (IllegalArgumentException ignored) {}
    }

    @Override public void close() {
        closing = true;
        String[] names;
        synchronized (workers) { names = workers.keySet().toArray(new String[0]); }
        for (String name : names) stopWorker(name);
    }
}
