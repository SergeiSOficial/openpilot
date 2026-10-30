package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.IBinder;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class RuntimeTest {
    static final class BoundWorker implements AutoCloseable, ServiceConnection {
        private final Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        private final CompletableFuture<IWorker> future = new CompletableFuture<>();
        BoundWorker(Class<?> type) {
            assertTrue(context.bindService(new Intent(context, type), this, Context.BIND_AUTO_CREATE));
        }
        IWorker get() throws Exception { return future.get(30, TimeUnit.SECONDS); }
        @Override public void onServiceConnected(ComponentName name, IBinder binder) { future.complete(IWorker.Stub.asInterface(binder)); }
        @Override public void onServiceDisconnected(ComponentName name) {}
        @Override public void close() throws Exception {
            IWorker worker = future.getNow(null);
            context.unbindService(this);
            if (worker != null) { try { worker.stop(); } catch (android.os.RemoteException ignored) {} }
        }
    }
    @Test public void pythonAndNativeIpcRunInSeparateAndroidProcesses() throws Exception {
        String session = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        try (BoundWorker one = new BoundWorker(WorkerService.Replay.class); BoundWorker two = new BoundWorker(WorkerService.Model.class)) {
            IWorker publisher = one.get(), subscriber = two.get();
            assertTrue(new JSONObject(publisher.probeSchema(session)).getBoolean("passed"));
            JSONObject first = new JSONObject(publisher.checkRuntime(session));
            JSONObject second = new JSONObject(subscriber.checkRuntime(session));
            assertTrue(first.toString(2), first.getBoolean("ready"));
            assertTrue(second.toString(2), second.getBoolean("ready"));
            assertTrue(first.getString("python").startsWith("3.12."));
            assertNotEquals(first.getInt("pid"), second.getInt("pid"));
            CompletableFuture<String> sent = CompletableFuture.supplyAsync(() -> {
                try { return publisher.probeIpc(session, true); }
                catch (Exception failure) { throw new RuntimeException(failure); }
            });
            assertTrue(subscriber.probeIpc(session, false).contains("passed"));
            assertTrue(sent.get(30, TimeUnit.SECONDS).contains("passed"));
        }
    }
    @Test public void physicalTransportCannotStartAsASimulationWorker() throws Exception {
        String session = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        try (BoundWorker bound = new BoundWorker(WorkerService.Car.class)) {
            IWorker worker = bound.get();
            worker.start(session, "pandad");
            long deadline = android.os.SystemClock.elapsedRealtime() + 10000;
            JSONObject status;
            do {
                status = new JSONObject(worker.status());
                if (status.getString("state").equals("failed")) break;
                Thread.sleep(25);
            } while (android.os.SystemClock.elapsedRealtime() < deadline);
            assertEquals("failed", status.getString("state"));
            assertTrue(status.getString("error").contains("allowlist"));
        }
    }

    @Test public void missingIpcPeerHasABoundedStartupTimeout() throws Exception {
        String session = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        try (BoundWorker bound = new BoundWorker(WorkerService.Model.class)) {
            long start = android.os.SystemClock.elapsedRealtime();
            try { bound.get().probeIpc(session, false); fail("Missing peer was accepted"); }
            catch (IllegalStateException expected) { assertTrue(expected.getMessage().contains("Timed out")); }
            assertTrue("Startup timeout was not bounded", android.os.SystemClock.elapsedRealtime()-start < 30000);
        }
    }
}
