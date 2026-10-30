package ai.comma.openpilot.sim;

import android.content.Context;

/** Process-local bridge: Python drains only the sensord service's bounded queues. */
public final class LiveSensorBridge {
    private static HardwareSensors collector;
    public static synchronized void start(Context context) {
        if(collector!=null)throw new IllegalStateException("Sensor collector already exists");
        collector=new HardwareSensors(context);collector.startContinuous();
    }
    public static synchronized String drain() {return collector.drain();}
    public static synchronized String status() {return collector.snapshot().toString();}
    public static synchronized void stop() {if(collector!=null)collector.close();}
    public static synchronized void saveCleanup(java.io.File root) {
        if(collector==null||root==null)return;
        try {java.nio.file.Files.write(new java.io.File(root,"sensor-cleanup.json").toPath(),status().getBytes(java.nio.charset.StandardCharsets.UTF_8));}
        catch(java.io.IOException error) {android.util.Log.e("OpenpilotSensors","Cleanup report",error);}
    }
}
