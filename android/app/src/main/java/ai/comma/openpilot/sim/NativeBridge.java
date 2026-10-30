package ai.comma.openpilot.sim;

public final class NativeBridge {
    static { System.loadLibrary("openpilot_ipc"); }
    private NativeBridge() {}
    public static native String ipc(String root, boolean publisher);
    public static native void captureStart(String root, boolean cabinOnly);
    public static native long captureFrame(int stream, java.nio.ByteBuffer y, int yRow, int yPixel,
        java.nio.ByteBuffer u, int uRow, int uPixel, java.nio.ByteBuffer v, int vRow, int vPixel,
        int width, int height, int left, int top, long timestamp, boolean realtime);
    public static native String captureStats();
    public static native boolean captureThumbnail(int stream, android.graphics.Bitmap bitmap);
    public static native void captureStop();
    public static native void captureResetCounters();
    public static native String captureSelfTest();
    public static native String capturePoolTest(String root);
    public static native String hardwareBufferProbe(android.hardware.HardwareBuffer buffer);
    public static native java.nio.ByteBuffer copyGpuLuma(long queue,long memory,int bytes);
}
