package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;
import android.app.Activity;
import android.content.Intent;
import android.os.SystemClock;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Public API/cleanup diagnostic only; no permission grants, vehicle data or calibration claims. */
@RunWith(AndroidJUnit4.class)
public class SensorsTest {
    @Test(timeout=30000) public void collectRawPhoneSensorsAndGnss() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        var context=instrumentation.getTargetContext();
        assumeTrue("Isolated diagnostic application only",context.getPackageName().equals("ai.comma.openpilot.acceleration"));
        Activity activity=null;
        HardwareSensors diagnostic=new HardwareSensors(context);
        JSONObject report;
        try {
            // Foreground GNSS callbacks are allowed; this activity does not press Start or open cameras.
            activity=instrumentation.startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            diagnostic.start(10_000);
            assertTrue("Automatic collection deadline",diagnostic.awaitStopped(12_000));
        } finally {
            try {diagnostic.close();} finally {
                try {diagnostic.writeReport();} finally {
                    if(activity!=null) {Activity finished=activity;instrumentation.runOnMainSync(finished::finish);}
                }
            }
        }
        report=diagnostic.snapshot();
        JSONObject cleanup=report.getJSONObject("cleanup");
        assertTrue("Closed",cleanup.getBoolean("closed"));
        for(String key:new String[]{"thread_alive","sensor_listener_registered","location_listener_registered","status_callback_registered","raw_callback_registered"})
            assertFalse(key,cleanup.getBoolean(key));
        assertFalse(report.getBoolean("mount_calibrated"));assertFalse(report.getBoolean("locationd_validated"));
        for(String name:new String[]{"accelerometer","gyroscope_uncalibrated"}) {
            JSONObject stream=report.getJSONObject(name);
            assertEquals(name+" finite values",0,stream.getInt("invalid_values"));
            assertEquals(name+" monotonic timestamps",0,stream.getInt("nonmonotonic_timestamps"));
            assertEquals(name+" bounded buffer",0,stream.getInt("dropped_at_capacity"));
            if(stream.optBoolean("registered_successfully"))assertTrue(name+" produced samples",stream.getInt("received")>0);
            JSONArray samples=stream.getJSONArray("samples");long previous=0;
            for(int i=0;i<samples.length();i++) {
                JSONObject sample=samples.getJSONObject(i);long timestamp=sample.getLong("timestamp_ns");
                assertTrue(name+" increasing",timestamp>previous);previous=timestamp;
                assertTrue(name+" measured clock",timestamp<=sample.getLong("received_elapsed_realtime_ns"));
                assertFinite(sample.getJSONArray("value"));
                if(name.equals("gyroscope_uncalibrated"))assertFinite(sample.getJSONArray("bias"));
            }
        }
        JSONObject gnss=report.getJSONObject("gnss");
        assertFalse(gnss.getBoolean("permission_requested"));
        assertEquals("Valid GPS fields",0,gnss.getInt("invalid_fixes"));
        assertEquals("GPS timestamps",0,gnss.getInt("nonmonotonic_fix_timestamps"));
        JSONArray fixes=gnss.getJSONArray("fixes");
        if(fixes.length()==0)assertEquals("No indoor GPS fix is a reported state","no_fix_received",gnss.getString("fix_state"));
        for(int i=0;i<fixes.length();i++) {
            JSONObject fix=fixes.getJSONObject(i);
            assertEquals("gps",fix.getString("provider"));
            assertTrue(Double.isFinite(fix.getDouble("latitude_deg")));assertTrue(Double.isFinite(fix.getDouble("longitude_deg")));
            assertTrue(fix.getLong("timestamp_ns")<=SystemClock.elapsedRealtimeNanos());
            assertTrue("Age is measured",Double.isFinite(fix.getDouble("age_ms")) && fix.getDouble("age_ms")>=0);
            assertTrue("Mock provenance retained",fix.has("mock"));
        }
        assertEquals("API errors retained in files/hardware/sensors.json",0,report.getJSONArray("errors").length());
    }

    private static void assertFinite(JSONArray vector) throws Exception {
        assertEquals(3,vector.length());for(int axis=0;axis<3;axis++)assertTrue(Double.isFinite(vector.getDouble(axis)));
    }
}
