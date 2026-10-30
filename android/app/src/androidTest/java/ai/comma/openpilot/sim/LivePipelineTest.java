package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Android-target tests only: no host-generated native helper is executed. */
@RunWith(AndroidJUnit4.class)
public class LivePipelineTest {
    @Test(timeout=30000) public void sensorWorkerPublishesRealMessagesAndStops() throws Exception {
        var context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        String session=UUID.randomUUID().toString().replace("-","").substring(0,16);
        File root=new File(context.getFilesDir(),"s/"+session);
        JSONObject report=null;
        try(RuntimeTest.BoundWorker bound=new RuntimeTest.BoundWorker(WorkerService.Sensors.class)) {
            IWorker worker=bound.get();worker.start(session,"sensord");
            long deadline=android.os.SystemClock.elapsedRealtime()+20000;
            while(android.os.SystemClock.elapsedRealtime()<deadline) {
                JSONObject state=new JSONObject(worker.status());assertNotEquals(state.toString(),"failed",state.getString("state"));
                File result=new File(root,"sensors.json");
                if(result.isFile()) {
                    report=new JSONObject(new String(Files.readAllBytes(result.toPath()),StandardCharsets.UTF_8));
                    if(report.getJSONObject("published").getInt("gyroscope")>=50)break;
                }
                Thread.sleep(100);
            }
            assertNotNull("Sensor worker never wrote a report",report);
            assertTrue(report.toString(),report.getJSONObject("published").getInt("accelerometer")>=50);
            assertTrue(report.toString(),report.getJSONObject("published").getInt("gyroscope")>=50);
            assertFalse(report.getBoolean("locationd_validated"));
        }
        JSONObject cleanup=new JSONObject(new String(Files.readAllBytes(new File(root,"sensor-cleanup.json").toPath()),StandardCharsets.UTF_8));
        assertTrue(cleanup.toString(),cleanup.getJSONObject("cleanup").getBoolean("closed"));
        Files.write(new File(context.getFilesDir(),"last-sensor-test-session.txt").toPath(),session.getBytes(StandardCharsets.UTF_8));
    }
    @Test(timeout=10000) public void continuousSensorsDrainAndReleaseListeners() throws Exception {
        var context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        HardwareSensors sensors=new HardwareSensors(context);
        try {
            sensors.startContinuous();Thread.sleep(1200);
            JSONObject first=new JSONObject(sensors.drain());
            assertTrue(first.toString(),first.getJSONArray("accelerometer").length()>50);
            assertTrue(first.toString(),first.getJSONArray("gyroscope").length()>50);
            assertTrue(first.getJSONArray("accelerometer").length()<=512);
            long last=first.getJSONArray("gyroscope").getJSONObject(first.getJSONArray("gyroscope").length()-1).getLong("timestamp_ns");
            Thread.sleep(100);
            JSONObject second=new JSONObject(sensors.drain());
            assertTrue(second.getJSONArray("gyroscope").getJSONObject(0).getLong("timestamp_ns")>last);
        } finally {sensors.close();}
        JSONObject cleanup=sensors.snapshot().getJSONObject("cleanup");
        assertTrue(cleanup.toString(),cleanup.getBoolean("closed"));
        for(String key:new String[]{"thread_alive","sensor_listener_registered","location_listener_registered","status_callback_registered","raw_callback_registered"})
            assertFalse(cleanup.toString(),cleanup.getBoolean(key));
    }
    @Test(timeout=15000) public void nativeNv12AndBoundedIpcPoolPreserveOwnership() throws Exception {
        var context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        File root=new File(context.getFilesDir(),"s/"+UUID.randomUUID().toString().replace("-","").substring(0,16));
        new File(root,"shm").mkdirs();
        JSONObject layout=new JSONObject(NativeBridge.captureSelfTest());
        JSONObject pool=new JSONObject(NativeBridge.capturePoolTest(root.getAbsolutePath()));
        assertTrue(layout.toString(),layout.getBoolean("passed"));
        assertTrue(pool.toString(),pool.getBoolean("passed"));
        JSONObject report=new JSONObject().put("layout",layout).put("pool",pool).put("android_target",android.os.Build.MODEL);
        Files.write(new File(root,"native-live-tests.json").toPath(),report.toString().getBytes(StandardCharsets.UTF_8));
        Files.write(new File(context.getFilesDir(),"last-native-live-test.txt").toPath(),root.getName().getBytes(StandardCharsets.UTF_8));
    }
}
