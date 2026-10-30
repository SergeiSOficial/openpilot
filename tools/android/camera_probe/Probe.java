package ai.comma.cameraprobe;

import android.app.Activity;
import android.content.Intent;
import android.graphics.ImageFormat;
import android.graphics.Bitmap;
import android.hardware.camera2.*;
import android.hardware.camera2.params.*;
import android.media.Image;
import android.media.ImageReader;
import android.os.*;
import android.util.Range;
import android.util.Size;
import android.widget.TextView;
import android.widget.LinearLayout;
import android.widget.ImageView;
import android.view.SurfaceView;
import dalvik.system.PathClassLoader;
import java.io.*;
import java.lang.reflect.*;
import java.nio.ByteBuffer;
import java.util.*;

/** On-device only. Receives and discards frames; writes text diagnostics, never images. */
public class Probe extends Activity {
  private final Handler handler = new Handler(Looper.getMainLooper());
  private CameraManager manager;
  private CameraDevice device;
  private CameraCaptureSession session;
  private final List<ImageReader> readers = new ArrayList<>();
  private final List<List<Long>> timestamps = new ArrayList<>();
  private final List<Set<Integer>> lumaHashes = new ArrayList<>();
  private final List<Long> sampleSeconds = new ArrayList<>();
  private long streamingStarted;
  private TextView text;
  private SurfaceView previewView;
  private final ImageView[] streamViews = new ImageView[2];
  private String logical, layout, format, vendor;
  private int width, height, fps, seconds, shooting, sessionType;
  private boolean closed, metadataSeen;
  private int failedCaptures;

  private void log(String value) {
    android.util.Log.i("FoldCameraProbe", value);
    try (FileWriter out = new FileWriter(new File(getFilesDir(), "result.txt"), true)) {
      out.write(value + "\n");
    } catch (IOException e) { android.util.Log.e("FoldCameraProbe", "Log write failed", e); }
    text.append(value + "\n");
  }

  @Override public void onCreate(Bundle saved) {
    super.onCreate(saved);
    Intent initial = getIntent();
    if (!initial.hasExtra("logical") && !initial.getBooleanExtra("inspect", false)) {
      initial.putExtra("logical", "20").putExtra("layout", "vendor").putExtra("preview", true)
          .putExtra("jpeg", true).putExtra("twophase", true).putExtra("width", 1920)
          .putExtra("height", 1080).putExtra("seconds", 60).putExtra("usecase0", 65536)
          .putExtra("usecase1", 16842752).putExtra("vendor", "first-entrance=false;samsungcamera=true;factorytest=false;shootingmode=3;recording-fps=30;sw-vdis=false;video-beautyface=false;vtmode=0;operation_mode=none;ssm_shot_mode=0;recording_dr_mode=sdr;sw-super_vdis=false;stream_type=0;");
    }
    text = new TextView(this);
    if (getIntent().getBooleanExtra("preview", false)) {
      LinearLayout column = new LinearLayout(this);
      column.setOrientation(LinearLayout.VERTICAL);
      column.addView(text, new LinearLayout.LayoutParams(-1, 0, 1));
      previewView = new SurfaceView(this);
      column.addView(previewView, new LinearLayout.LayoutParams(-1, 160));
      for (int i = 0; i < 2; i++) {
        TextView label = new TextView(this);
        label.setText("Stream " + i + (i == 0 ? " (middle rear lens)" : " (bottom rear lens)"));
        column.addView(label);
        streamViews[i] = new ImageView(this);
        streamViews[i].setScaleType(ImageView.ScaleType.FIT_CENTER);
        column.addView(streamViews[i], new LinearLayout.LayoutParams(-1, 180));
      }
      setContentView(column);
    } else setContentView(text);
    getWindow().addFlags(128);
    new File(getFilesDir(), "result.txt").delete();
    Intent args = getIntent();
    logical = args.getStringExtra("logical");
    if (logical == null) logical = "23";
    layout = args.getStringExtra("layout");
    if (layout == null) layout = "physical";
    format = args.getStringExtra("format");
    if (format == null) format = "yuv";
    vendor = args.getStringExtra("vendor");
    width = args.getIntExtra("width", 640);
    height = args.getIntExtra("height", 480);
    if (previewView != null) previewView.getHolder().setFixedSize(width, height);
    fps = args.getIntExtra("fps", 30);
    seconds = args.getIntExtra("seconds", 5);
    shooting = args.getIntExtra("shooting", -1);
    sessionType = args.getIntExtra("sessiontype", SessionConfiguration.SESSION_REGULAR);
    manager = getSystemService(CameraManager.class);
    log("MODEL=" + Build.MODEL + " SDK=" + Build.VERSION.SDK_INT + " PACKAGE=" + getPackageName());
    log("BUILD=" + Build.FINGERPRINT);
    log("TEST logical=" + logical + " layout=" + layout + " format=" + format
        + " size=" + width + "x" + height + " fps=" + fps + " seconds=" + seconds
        + " shooting=" + shooting + " sessiontype=" + sessionType + " vendor=" + vendor);
    try {
      log("PUBLIC_IDS=" + Arrays.toString(manager.getCameraIdList()) + " CONCURRENT=" + manager.getConcurrentCameraIds());
      CameraCharacteristics c = manager.getCameraCharacteristics(logical);
      log("PHYSICAL_IDS=" + c.getPhysicalCameraIds() + " SYNC=" + c.get(CameraCharacteristics.LOGICAL_MULTI_CAMERA_SENSOR_SYNC_TYPE));
      log("FPS_RANGES=" + Arrays.toString(c.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES)));
      log("REQUEST_KEYS=" + c.getAvailableCaptureRequestKeys());
      log("SESSION_KEYS=" + c.getAvailableSessionKeys());
      log("PHYSICAL_REQUEST_KEYS=" + c.getAvailablePhysicalCameraRequestKeys());
      for (CameraCharacteristics.Key<?> key : c.getKeys()) {
        if (key.getName().startsWith("samsung.") && (key.getName().contains("availableFeatures")
            || key.getName().contains("availableShooting") || key.getName().contains("availableMulti")
            || key.getName().contains("availableSession") || key.getName().contains("physical"))) {
          log("VENDOR_CHARACTERISTIC " + key.getName() + "=" + printable(c.get(key)));
        }
      }
      for (String id : c.getPhysicalCameraIds()) {
        CameraCharacteristics pc = manager.getCameraCharacteristics(id);
        StreamConfigurationMap sm = pc.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        log("PHYSICAL " + id + " focal=" + Arrays.toString(pc.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS))
            + " yuv=" + Arrays.toString(sm.getOutputSizes(ImageFormat.YUV_420_888)));
      }
      if (args.getBooleanExtra("inspect", false)) { inspectPrivateInterface(); log("DONE_INSPECT"); return; }
      handler.postDelayed(() -> finishTest("TIMEOUT"), (seconds + 15) * 1000L);
      manager.openCamera(logical, new CameraDevice.StateCallback() {
        @Override public void onOpened(CameraDevice value) {
          device = value;
          log("OPENED");
          if (getIntent().getBooleanExtra("twophase", false)) {
            try {
              String init = "first-entrance=true;samsungcamera=true;factorytest=false;shootingmode=0;recording-fps=0;sw-vdis=false;video-beautyface=false;vtmode=0;operation_mode=none;ssm_shot_mode=0;recording_dr_mode=sdr;sw-super_vdis=false;stream_type=0;";
              samsungHelper().getMethod("setSamsungParameter", CameraDevice.class, String.class).invoke(null, device, init);
              log("FIRST_PHASE_SENT");
              handler.postDelayed(() -> configure(), 250);
            } catch (Exception e) { finishTest("FIRST_PHASE_EXCEPTION=" + e); }
          } else configure();
        }
        @Override public void onDisconnected(CameraDevice value) { value.close(); finishTest("DISCONNECTED"); }
        @Override public void onError(CameraDevice value, int error) { value.close(); finishTest("OPEN_ERROR=" + error); }
      }, handler);
    } catch (Exception e) { finishTest("START_EXCEPTION=" + e); }
  }

  private static String printable(Object value) {
    if (value == null) return "null";
    if (!value.getClass().isArray()) return value.toString();
    List<String> result = new ArrayList<>();
    int length = Array.getLength(value);
    for (int i = 0; i < Math.min(120, length); i++) result.add(String.valueOf(Array.get(value, i)));
    return result + (length > 120 ? " ... length=" + length : "");
  }

  private Class<?> samsungHelper() throws Exception {
    ClassLoader loader = new PathClassLoader("/system/framework/scamera_sdk_util.jar", getClassLoader());
    return Class.forName("com.samsung.android.sdk.camera.impl.internal.CustomInterfaceHelper", true, loader);
  }

  private void inspectPrivateInterface() {
    try {
      for (Method m : samsungHelper().getDeclaredMethods()) log("SDK_METHOD=" + m);
      for (Method m : CameraDevice.class.getDeclaredMethods()) {
        if (m.getName().toLowerCase().matches(".*(samsung|parameter|session).*")) log("DEVICE_METHOD=" + m);
      }
      for (Method m : OutputConfiguration.class.getDeclaredMethods()) {
        if (m.getName().toLowerCase().matches(".*(samsung|parameter|physical|sensor).*")) log("OUTPUT_METHOD=" + m);
      }
    } catch (Exception e) { log("INSPECT_EXCEPTION=" + e); }
  }

  private void configure() {
    if (closed) return;
    if (previewView != null && !previewView.getHolder().getSurface().isValid()) {
      handler.postDelayed(() -> configure(), 100);
      return;
    }
    try {
      if (vendor != null && !vendor.isEmpty()) {
        try {
          samsungHelper().getMethod("setSamsungParameter", CameraDevice.class, String.class).invoke(null, device, vendor);
          log("VENDOR_PARAMETERS_SENT");
        } catch (InvocationTargetException e) { finishTest("VENDOR_EXCEPTION=" + e.getCause()); return; }
      }
      List<String> bindings = layout.equals("single") ? Arrays.asList((String)null)
          : layout.equals("vendor") ? Arrays.asList(null, null)
          : layout.equals("logicalplus") ? Arrays.asList(null, "2")
          : layout.equals("physicalmain") ? Arrays.asList("0")
          : layout.equals("physicalwide") ? Arrays.asList("2")
          : Arrays.asList("0", "2");
      List<OutputConfiguration> outputs = new ArrayList<>();
      CaptureRequest.Builder request = device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);
      if (previewView != null) {
        OutputConfiguration preview = new OutputConfiguration(previewView.getHolder().getSurface());
        preview.setStreamUseCase(65536);
        outputs.add(preview);
        request.addTarget(previewView.getHolder().getSurface());
        log("DISPLAY_PREVIEW_ADDED");
      }
      for (int i = 0; i < bindings.size(); i++) {
        final int stream = i;
        int imageFormat = format.equals("private") || (format.equals("mixed") && i == 0)
            ? ImageFormat.PRIVATE : ImageFormat.YUV_420_888;
        ImageReader reader = ImageReader.newInstance(width, height, imageFormat, 4);
        readers.add(reader);
        timestamps.add(new ArrayList<>());
        lumaHashes.add(new HashSet<>());
        sampleSeconds.add(-1L);
        reader.setOnImageAvailableListener(r -> {
          try (Image image = r.acquireNextImage()) {
            if (image != null) {
              timestamps.get(stream).add(image.getTimestamp());
              if (image.getFormat() == ImageFormat.YUV_420_888) {
                ByteBuffer data = image.getPlanes()[0].getBuffer();
                int hash = 1;
                long sum = 0;
                int minimum = 255, maximum = 0, samples = 0;
                Image.Plane plane = image.getPlanes()[0];
                for (int y = 0; y < image.getHeight(); y += Math.max(1, image.getHeight()/16)) {
                  for (int x = 0; x < image.getWidth(); x += Math.max(1, image.getWidth()/16)) {
                    int p = y * plane.getRowStride() + x * plane.getPixelStride();
                    int v = data.get(p) & 255;
                    hash = 31 * hash + v;
                    sum += v; samples++;
                    minimum = Math.min(minimum, v); maximum = Math.max(maximum, v);
                  }
                }
                lumaHashes.get(stream).add(hash);
                long second = (SystemClock.elapsedRealtime() - streamingStarted) / 1000;
                if (sampleSeconds.get(stream) != second) {
                  sampleSeconds.set(stream, second);
                  log("LUMA second=" + second + " stream=" + stream + " frames=" + timestamps.get(stream).size()
                      + " mean=" + (double)sum/samples + " min=" + minimum + " max=" + maximum + " hash=" + hash);
                  if (streamViews[stream] != null) {
                    int[] pixels = new int[160 * 90];
                    for (int y = 0; y < 90; y++) for (int x = 0; x < 160; x++) {
                      int v = data.get((y * image.getHeight()/90) * plane.getRowStride()
                          + (x * image.getWidth()/160) * plane.getPixelStride()) & 255;
                      pixels[y * 160 + x] = 0xff000000 | v << 16 | v << 8 | v;
                    }
                    streamViews[stream].setImageBitmap(Bitmap.createBitmap(pixels, 160, 90, Bitmap.Config.ARGB_8888));
                  }
                }
              }
            }
          } catch (Exception e) { finishTest("IMAGE_EXCEPTION=" + e); }
        }, handler);
        OutputConfiguration out = new OutputConfiguration(reader.getSurface());
        if (bindings.get(i) != null) out.setPhysicalCameraId(bindings.get(i));
        int useCase = getIntent().getIntExtra("usecase" + i, 0);
        if (useCase != 0) {
          out.setStreamUseCase(useCase);
          log("OUTPUT stream=" + i + " usecase=" + useCase);
        }
        outputs.add(out);
        request.addTarget(reader.getSurface());
      }
      if (getIntent().getBooleanExtra("jpeg", false)) {
        ImageReader jpeg = ImageReader.newInstance(4000, 2252, ImageFormat.JPEG, 2);
        readers.add(jpeg);
        OutputConfiguration out = new OutputConfiguration(jpeg.getSurface());
        out.setStreamUseCase(131072);
        outputs.add(out);
        log("PASSIVE_JPEG_OUTPUT_ADDED");
      }
      if (fps > 0) request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, new Range<Integer>(fps, fps));
      if (shooting >= 0) {
        request.set(new CaptureRequest.Key<Integer>("samsung.android.control.shootingMode", Integer.class), shooting);
        request.set(new CaptureRequest.Key<Boolean>("samsung.android.control.dualCameraDisable", Boolean.class), false);
        log("VENDOR_SESSION_KEYS_SET");
      }
      SessionConfiguration config = new SessionConfiguration(sessionType, outputs, getMainExecutor(), new CameraCaptureSession.StateCallback() {
        @Override public void onConfigured(CameraCaptureSession value) {
          if (closed) { value.close(); return; }
          session = value;
          log("CONFIGURED");
          try {
            value.setRepeatingRequest(request.build(), new CameraCaptureSession.CaptureCallback() {
              @Override public void onCaptureCompleted(CameraCaptureSession s, CaptureRequest r, TotalCaptureResult result) {
                if (!metadataSeen) {
                  metadataSeen = true;
                  log("METADATA active=" + result.get(CaptureResult.LOGICAL_MULTI_CAMERA_ACTIVE_PHYSICAL_ID)
                      + " focal=" + result.get(CaptureResult.LENS_FOCAL_LENGTH)
                      + " physical_results=" + result.getPhysicalCameraResults().keySet());
                  for (Map.Entry<String, CaptureResult> p : result.getPhysicalCameraResults().entrySet()) {
                    log("PHYSICAL_RESULT id=" + p.getKey() + " focal=" + p.getValue().get(CaptureResult.LENS_FOCAL_LENGTH));
                  }
                  for (CaptureResult.Key<?> key : result.getKeys()) {
                    String name = key.getName().toLowerCase();
                    if (name.contains("physical") || name.contains("cameraid") || name.contains("lowpower") || name.contains("multicamera")) {
                      try { log("RESULT_KEY " + key.getName() + "=" + printable(result.get(key))); }
                      catch (Exception e) { log("RESULT_KEY_EXCEPTION=" + key.getName() + " " + e); }
                    }
                  }
                }
              }
              @Override public void onCaptureFailed(CameraCaptureSession s, CaptureRequest r, CaptureFailure failure) {
                if (++failedCaptures < 4) log("CAPTURE_FAILED=" + failure.getReason());
              }
            }, handler);
            streamingStarted = SystemClock.elapsedRealtime();
            log("STREAMING");
            handler.postDelayed(() -> finishTest("COMPLETE"), seconds * 1000L);
          } catch (Exception e) { finishTest("REPEATING_EXCEPTION=" + e); }
        }
        @Override public void onConfigureFailed(CameraCaptureSession value) { value.close(); finishTest("CONFIGURE_FAILED"); }
      });
      config.setSessionParameters(request.build());
      try { log("SESSION_SUPPORTED=" + device.isSessionConfigurationSupported(config)); }
      catch (Exception e) { log("SUPPORT_QUERY_EXCEPTION=" + e); }
      device.createCaptureSession(config);
    } catch (Exception e) { finishTest("CONFIGURE_EXCEPTION=" + e); }
  }

  private void finishTest(String reason) {
    if (closed) return;
    log("END=" + reason + " capture_failures=" + failedCaptures);
    for (int i = 0; i < timestamps.size(); i++) {
      List<Long> ts = timestamps.get(i);
      double span = ts.size() > 1 ? (ts.get(ts.size()-1) - ts.get(0)) / 1e9 : 0;
      long maxGap = 0;
      int nonMonotonic = 0;
      for (int j = 1; j < ts.size(); j++) {
        long gap = ts.get(j) - ts.get(j-1);
        maxGap = Math.max(maxGap, gap);
        if (gap <= 0) nonMonotonic++;
      }
      log("RESULT stream=" + i + " frames=" + ts.size() + " span_s=" + span
          + " fps=" + (span > 0 ? (ts.size()-1)/span : 0) + " max_gap_ms=" + maxGap/1e6
          + " nonmonotonic=" + nonMonotonic + " distinct_luma_hashes=" + lumaHashes.get(i).size());
    }
    if (timestamps.size() == 2 && !timestamps.get(0).isEmpty() && !timestamps.get(1).isEmpty()) {
      List<Long> a = timestamps.get(0), b = timestamps.get(1);
      List<Long> offsets = new ArrayList<>();
      for (long t : a) {
        if (t < b.get(0) || t > b.get(b.size()-1)) continue;
        long nearest = Long.MAX_VALUE;
        for (long u : b) nearest = Math.min(nearest, Math.abs(t-u));
        offsets.add(nearest);
      }
      Collections.sort(offsets);
      if (!offsets.isEmpty()) log("PAIR nearest_timestamp_median_ms=" + offsets.get(offsets.size()/2)/1e6
          + " max_ms=" + offsets.get(offsets.size()-1)/1e6 + " matched=" + offsets.size());
    }
    close();
    log("DONE");
  }

  private void close() {
    closed = true;
    handler.removeCallbacksAndMessages(null);
    if (session != null) { session.close(); session = null; }
    if (device != null) { device.close(); device = null; }
    for (ImageReader reader : readers) reader.close();
    readers.clear();
  }

  @Override protected void onDestroy() { close(); super.onDestroy(); }
}
