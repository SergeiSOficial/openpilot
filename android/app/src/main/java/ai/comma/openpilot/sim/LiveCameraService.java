package ai.comma.openpilot.sim;

import android.app.Service;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.ImageFormat;
import android.graphics.Rect;
import android.hardware.HardwareBuffer;
import android.hardware.camera2.*;
import android.hardware.camera2.params.*;
import android.media.Image;
import android.media.ImageReader;
import android.os.*;
import android.util.Range;
import android.util.SizeF;
import android.view.Surface;
import dalvik.system.PathClassLoader;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.*;
import org.json.*;

/** Capture only. Vehicle interfaces and controls are never started by this service. */
public final class LiveCameraService extends Service {
    private HandlerThread thread;
    private Handler handler;
    private CameraManager manager;
    private final Map<String,CameraDevice> devices = new HashMap<>();
    private final List<CameraCaptureSession> sessions = new ArrayList<>();
    private final List<ImageReader> readers = new ArrayList<>();
    private final List<HandlerThread> captureThreads = new ArrayList<>();
    private final boolean[] probed = new boolean[3];
    private final boolean[] timestampRealtime = new boolean[3];
    private final long[] lastTimestamp = new long[3];
    private volatile String report = "{\"state\":\"idle\"}";
    private JSONObject state;
    private File root;
    private Surface roadPreview, cabinPreview;
    private boolean cabinOnly, cabinDisabled, rearConfigPending, combinedTried, combinedActive;
    private volatile boolean stopped=true;
    private int rotation, retries;
    private volatile int generation;
    private long started;
    private long headroomAt;
    private Object thermalHeadroom=JSONObject.NULL;
    private static final String BASE = "samsungcamera=true;factorytest=false;sw-vdis=false;video-beautyface=false;vtmode=0;operation_mode=none;ssm_shot_mode=0;recording_dr_mode=sdr;sw-super_vdis=false;stream_type=0;";

    @Override public void onCreate() {
        super.onCreate(); thread=new HandlerThread("openpilot-camera");thread.start();
        handler=new Handler(thread.getLooper());manager=getSystemService(CameraManager.class);
        // Android can kill the capture process on permission revocation, then
        // rebind an idle service. Reconcile the previous session before binding.
        try{
            File marker=new File(getFilesDir(),"last-live-session.txt");
            if(marker.isFile()){
                String previous=new String(Files.readAllBytes(marker.toPath()),StandardCharsets.UTF_8).trim();
                if(previous.matches("[a-f0-9]{16}")){
                    File target=new File(getFilesDir(),"s/"+previous+"/camera.json");
                    if(target.isFile()){
                        JSONObject old=new JSONObject(new String(Files.readAllBytes(target.toPath()),StandardCharsets.UTF_8));
                        if(!Arrays.asList("stopped","failed").contains(old.optString("state"))){
                            old.put("state","failed").put("rear_available",false).put("cabin_available",false)
                               .put("error","Capture process restarted; previous camera ownership ended");
                            write(target,old);report=old.toString();
                        }
                    }
                }
            }
        }catch(Exception e){android.util.Log.e("OpenpilotLive","Previous capture reconciliation",e);}
    }
    private static void write(File target,JSONObject value) throws Exception {
        File tmp=new File(target.getParentFile(),target.getName()+".tmp");
        Files.write(tmp.toPath(),value.toString().getBytes(StandardCharsets.UTF_8));
        Files.move(tmp.toPath(),target.toPath(),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);
    }
    private void publish() {
        try {
            state.put("elapsed_seconds",(SystemClock.elapsedRealtime()-started)/1000.0);
            state.put("report_monotonic_ns",System.nanoTime());
            state.put("native",new JSONObject(NativeBridge.captureStats()));
            state.put("thermal_status",getSystemService(PowerManager.class).getCurrentThermalStatus());
            if(SystemClock.elapsedRealtime()-headroomAt>=10000){
                try {float value=getSystemService(PowerManager.class).getThermalHeadroom(10);
                    thermalHeadroom=Float.isFinite(value)?value:JSONObject.NULL;
                } catch(RuntimeException unavailable){thermalHeadroom=JSONObject.NULL;state.put("thermal_headroom_unavailable",unavailable.getClass().getSimpleName());}
                headroomAt=SystemClock.elapsedRealtime();
            }
            state.put("thermal_headroom",thermalHeadroom);
            state.put("capture_process_pss_kib",android.os.Debug.getPss());
            Intent battery=registerReceiver(null,new android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if(battery!=null&&battery.hasExtra(BatteryManager.EXTRA_TEMPERATURE))state.put("battery_temperature_c",battery.getIntExtra(BatteryManager.EXTRA_TEMPERATURE,0)/10.0);
            report=state.toString();write(new File(root,"camera.json"),state);
        } catch(Exception e) { android.util.Log.e("OpenpilotLive","Camera report",e); }
    }
    private final Runnable poll = new Runnable() { public void run() { if(!stopped){publish();
        if(getSystemService(PowerManager.class).getCurrentThermalStatus()>=PowerManager.THERMAL_STATUS_CRITICAL){error("thermal_critical",new IllegalStateException("Critical thermal status; restart explicitly after cooling"));return;}
        watchdog();if(!stopped)handler.postDelayed(this,1000);} } };
    private void watchdog(){
        try{
            if(!state.optString("state").equals("running")||!state.has("measurement_start_monotonic_ns"))return;
            if(System.nanoTime()-state.getLong("measurement_start_monotonic_ns")<2_000_000_000L)return;
            JSONArray streams=state.getJSONObject("native").getJSONArray("streams");
            for(int stream:cabinOnly?new int[]{1}:new int[]{0,2}){
                JSONObject sample=streams.getJSONObject(stream);
                if(sample.optLong("frames")==0||sample.optDouble("age_ms")>2000){recover(cabinOnly?"1":"20","delivery_timeout_stream_"+stream);return;}
            }
        }catch(Exception e){error("capture_watchdog",e);}
    }

    private void samsung(CameraDevice device,String values) throws Exception {
        ClassLoader loader=new PathClassLoader("/system/framework/scamera_sdk_util.jar",getClassLoader());
        Class<?> helper=Class.forName("com.samsung.android.sdk.camera.impl.internal.CustomInterfaceHelper",true,loader);
        helper.getMethod("setSamsungParameter",CameraDevice.class,String.class).invoke(null,device,values);
    }
    private void begin(String session,String mode,Surface road,Surface cabin,int displayRotation) {
        try {
            if(!stopped)throw new IllegalStateException("Stop the current capture first");
            if(!session.matches("[a-f0-9]{16}"))throw new IllegalArgumentException("Invalid session");
            root=new File(getFilesDir(),"s/"+session);new File(root,"shm").mkdirs();
            cabinOnly=mode.equals("cabin");roadPreview=road;cabinPreview=cabin;rotation=displayRotation;
            stopped=false;cabinDisabled=false;rearConfigPending=false;retries=0;generation++;started=SystemClock.elapsedRealtime();
            // This firmware already rejected the stock-style combined setup.
            // Retrying it is an explicit diagnostic option, never a normal-launch loop.
            combinedTried=!mode.equals("live-combined");combinedActive=false;
            Arrays.fill(probed,false);Arrays.fill(lastTimestamp,0);
            state=new JSONObject().put("schema",1).put("state","starting").put("mode",mode)
                .put("vehicle_connected",false).put("stationary_inputs",true).put("calibration_validated",false)
                .put("root_required",false).put("cabin_available",false).put("rear_available",false)
                .put("clock","CLOCK_MONOTONIC").put("readout_end_measured",false)
                .put("model",Build.MODEL).put("firmware",Build.FINGERPRINT).put("profiles",new JSONArray());
            if(getSystemService(PowerManager.class).getCurrentThermalStatus()>=PowerManager.THERMAL_STATUS_SEVERE)
                throw new IllegalStateException("Device must cool before capture startup");
            NativeBridge.captureStart(root.getAbsolutePath(),cabinOnly);
            state.put("native_layout_check",new JSONObject(NativeBridge.captureSelfTest()));
            publish();handler.post(poll);
            // Initialize advertised metadata inside the app, with no shell/dumpsys preflight.
            for(String id:manager.getCameraIdList())manager.getCameraCharacteristics(id);
            for(int n=0;n<android.hardware.Camera.getNumberOfCameras();n++)android.hardware.Camera.getCameraInfo(n,new android.hardware.Camera.CameraInfo());
            state.put("startup_preflight","in_app_public_camera_metadata");
            if(combinedTried)state.put("combined_attempt","manual_retry_only_previous_fold3_attempt_failed");
            if(cabinOnly)open("1",false);else prepareRear(0);
        } catch(Exception e){error("startup",e);}
    }
    private void prepareRear(int attempt) {
        if(stopped)return;
        try { manager.getCameraCharacteristics("20");open("20",false); }
        catch(Exception e) {
            if(attempt<8)handler.postDelayed(()->prepareRear(attempt+1),500);
            else error("hidden_camera_access",new IllegalStateException("Hidden rear camera unavailable without ADB preparation",e));
        }
    }
    private void open(String id,boolean optionalCabin) {
        final int current=generation;
        try {
            manager.openCamera(id,new CameraDevice.StateCallback(){
                public void onOpened(CameraDevice device){
                    if(stopped||current!=generation){device.close();return;}
                    devices.put(id,device);
                    try {
                        if(id.equals("20")){
                            samsung(device,"first-entrance=true;shootingmode=0;recording-fps=0;"+BASE);
                            // Open all devices before either session, as required for concurrent allocation.
                            if(combinedTried){cabinDisabled=true;state.put("cabin_unavailable_reason","separate_cabin_mode");configureRear();}
                            else open("1",true);
                        } else if(optionalCabin){configureRear();configureCabin(device);}
                        else configureCabin(device);
                    }catch(Exception e){error("open_configuration",e);}
                }
                public void onDisconnected(CameraDevice device){device.close();if(!stopped&&current==generation)recover(id,"disconnected");}
                public void onError(CameraDevice device,int code){
                    device.close();if(stopped||current!=generation)return;
                    if(optionalCabin){tryCombined("open_camera_"+code);}
                    else recover(id,"camera_error_"+code);
                }
            },handler);
        }catch(Exception e){if(optionalCabin){tryCombined(e.toString());}else error("open_camera_"+id,e);}
    }
    private void tryCombined(String directFailure){
        if(combinedTried){disableCabin(directFailure);configureRear();return;}
        combinedTried=true;combinedActive=true;generation++;closeDevices();rearConfigPending=false;
        try{state.put("direct_cabin_attempt",directFailure).put("combined_attempt","stock_multi_view_open_before_initialization");}catch(Exception ignored){}
        final int current=generation;
        handler.postDelayed(()->{
            if(stopped||current!=generation)return;
            // Samsung stock BACK_SEAMLESS_AND_FRONT opens device IDs 20 and 1.
            // Its callbacks send only first-entrance/samsungcamera before both opens finish.
            for(String id:new String[]{"20","1"})try{
                manager.openCamera(id,new CameraDevice.StateCallback(){
                    public void onOpened(CameraDevice d){
                        if(stopped||current!=generation){d.close();return;}devices.put(id,d);
                        try{
                            samsung(d,"first-entrance=true;samsungcamera=true;factorytest=false;");
                            if(devices.containsKey("20")&&devices.containsKey("1")){configureRear();configureCabin(devices.get("1"));}
                        }catch(Exception e){combinedFailed(e.toString());}
                    }
                    public void onDisconnected(CameraDevice d){d.close();if(!stopped&&current==generation)combinedFailed("disconnected_"+id);}
                    public void onError(CameraDevice d,int code){d.close();if(!stopped&&current==generation)combinedFailed("open_"+id+"_error_"+code);}
                },handler);
            }catch(Exception e){combinedFailed(e.toString());break;}
            handler.postDelayed(()->{if(!stopped&&current==generation&&!rearConfigPending)combinedFailed("combined_open_timeout");},6000);
        },700);
    }
    private void combinedFailed(String reason){
        if(!combinedActive)return;
        combinedActive=false;generation++;closeDevices();rearConfigPending=false;
        getSharedPreferences("live-camera",MODE_PRIVATE).edit().putString("combined_rejected_firmware",Build.FINGERPRINT).putString("combined_rejected_reason",reason).apply();
        disableCabin("Samsung combined front/rear rejected: "+reason);
        try{state.put("combined_attempt",reason).put("state","recovering_rear_pair");}catch(Exception ignored){}
        handler.postDelayed(()->{if(!stopped)prepareRearRecovery(0);},1500);
    }
    private void prepareRearRecovery(int attempt){
        if(stopped)return;
        try{
            for(String id:manager.getCameraIdList())manager.getCameraCharacteristics(id);
            for(int n=0;n<android.hardware.Camera.getNumberOfCameras();n++)android.hardware.Camera.getCameraInfo(n,new android.hardware.Camera.CameraInfo());
            manager.getCameraCharacteristics("20");openRearOnly();
        }catch(Exception e){if(attempt<8)handler.postDelayed(()->prepareRearRecovery(attempt+1),500);else error("rear_recovery",e);}
    }
    private void disableCabin(String why){
        cabinDisabled=true;
        try{state.put("cabin_available",false).put("cabin_unavailable_reason",why);}catch(JSONException ignored){}
        CameraDevice c=devices.remove("1");if(c!=null)c.close();publish();
    }
    private ImageReader reader(int stream,int width,int height) throws Exception {
        ImageReader reader=ImageReader.newInstance(width,height,ImageFormat.YUV_420_888,4);readers.add(reader);
        final int captureGeneration=generation;
        HandlerThread captureThread=new HandlerThread("capture-"+stream);captureThread.start();captureThreads.add(captureThread);
        reader.setOnImageAvailableListener(r->{
            if(stopped||captureGeneration!=generation)return;
            try(Image image=r.acquireLatestImage()){
                if(image==null)return;
                long rawTimestamp=image.getTimestamp();
                if(rawTimestamp<=0||rawTimestamp<=lastTimestamp[stream])throw new IllegalStateException("Nonmonotonic sensor timestamp");
                lastTimestamp[stream]=rawTimestamp;
                Rect crop=image.getCropRect();
                if(crop.width()!=width||crop.height()!=height)throw new IllegalStateException("Unexpected cropped camera dimensions");
                Image.Plane[] p=image.getPlanes();
                long ts=NativeBridge.captureFrame(stream,p[0].getBuffer().slice(),p[0].getRowStride(),p[0].getPixelStride(),
                    p[1].getBuffer().slice(),p[1].getRowStride(),p[1].getPixelStride(),p[2].getBuffer().slice(),p[2].getRowStride(),p[2].getPixelStride(),
                    width,height,crop.left,crop.top,rawTimestamp,timestampRealtime[stream]);
                if(!probed[stream]){
                    probed[stream]=true;
                    try(HardwareBuffer buffer=image.getHardwareBuffer()){
                        String probe=NativeBridge.hardwareBufferProbe(buffer);
                        handler.post(()->{try{state.put("hardware_buffer_"+stream,new JSONObject(probe));}catch(Exception ignored){}});
                    }
                }
            }catch(Exception e){if(!stopped&&captureGeneration==generation)handler.post(()->{if(!stopped&&captureGeneration==generation)error("capture_stream_"+stream,e);});}
        },new Handler(captureThread.getLooper()));return reader;
    }
    private OutputConfiguration output(Surface surface,int role){OutputConfiguration out=new OutputConfiguration(surface);out.setStreamUseCase(((long)role)<<16);return out;}
    private Range<Integer> fps(String id,int target) throws Exception {
        Range<Integer>[] ranges=manager.getCameraCharacteristics(id).get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES);
        if(ranges!=null)for(Range<Integer> r:ranges)if(r.getLower()==target&&r.getUpper()==target)return r;
        if(ranges!=null)for(Range<Integer> r:ranges)if(r.contains(target))return r;
        throw new IllegalStateException("No advertised capture rate for "+id);
    }
    private void profile(int stream,String id,int w,int h) throws Exception {
        CameraCharacteristics c=manager.getCameraCharacteristics(id);
        timestampRealtime[stream]=Objects.equals(c.get(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE),CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME);
        float[] k=c.get(CameraCharacteristics.LENS_INTRINSIC_CALIBRATION),f=c.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS);
        SizeF physical=c.get(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE);Rect active=c.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
        double aw=active.width(),ah=active.height(),cw=aw,ch=ah;
        if(aw/ah>(double)w/h)cw=ah*w/h;else ch=aw*h/w;
        double sx=w/cw,sy=h/ch,fx,fy,cx,cy;
        boolean factory=k!=null&&k.length>=4&&k[0]>0&&k[1]>0&&k[2]>active.left&&k[3]>active.top
            &&k[2]<active.right&&k[3]<active.bottom;
        if(factory){fx=k[0]*sx;fy=k[1]*sy;cx=(k[2]-active.left-(aw-cw)/2)*sx;cy=(k[3]-active.top-(ah-ch)/2)*sy;}
        else{fx=f[0]/physical.getWidth()*aw*sx;fy=f[0]/physical.getHeight()*ah*sy;cx=w/2.0;cy=h/2.0;}
        int sensor=c.get(CameraCharacteristics.SENSOR_ORIENTATION);
        int turn=stream==1?(sensor+rotation)%360:(sensor-rotation+360)%360;
        JSONObject p=new JSONObject().put("stream",stream).put("camera_id",id).put("width",w).put("height",h)
            .put("fx",fx).put("fy",fy).put("cx",cx).put("cy",cy).put("rotation_degrees",turn)
            .put("mirror_input",false).put("preview_mirrored",false).put("factory_intrinsics",factory)
            .put("timestamp_realtime",timestampRealtime[stream]).put("validated",false)
            .put("calibration_id","fold3-"+(factory?"factory":"nominal")+"-provisional-"+id+"-"+w+"x"+h+"-r"+turn+"-v1");
        state.getJSONArray("profiles").put(p);
    }
    private void configureRear(){
        if(stopped||rearConfigPending||!devices.containsKey("20"))return;
        rearConfigPending=true;
        final int current=generation;
        handler.postDelayed(()->{
            if(stopped||current!=generation)return;
            try {
                CameraDevice device=devices.get("20");
                samsung(device,"first-entrance=false;shootingmode="+(combinedActive?32:3)+";recording-fps=30;"+BASE);
                if(roadPreview==null||!roadPreview.isValid())throw new IllegalStateException("Display preview surface unavailable");
                profile(0,"0",1920,1080);profile(2,"2",1920,1080);
                List<OutputConfiguration> outputs=new ArrayList<>();outputs.add(output(roadPreview,1));
                CaptureRequest.Builder request=device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);request.addTarget(roadPreview);
                for(int n:new int[]{0,2}){ImageReader r=reader(n,1920,1080);outputs.add(output(r.getSurface(),n==0?1:0x101));request.addTarget(r.getSurface());}
                ImageReader jpeg=ImageReader.newInstance(4000,2252,ImageFormat.JPEG,2);readers.add(jpeg);outputs.add(output(jpeg.getSurface(),2));
                request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE,fps("20",30));
                session(device,outputs,request,false);
            }catch(Exception e){if(combinedActive)combinedFailed(e.toString());else error("rear_configuration",e);}
        },250);
    }
    private void configureCabin(CameraDevice device){
        try {
            if(combinedActive)samsung(device,"first-entrance=false;shootingmode=32;recording-fps=30;"+BASE);
            profile(1,"1",1280,720);
            ImageReader r=reader(1,1280,720);List<OutputConfiguration> outputs=new ArrayList<>();outputs.add(new OutputConfiguration(r.getSurface()));
            CaptureRequest.Builder request=device.createCaptureRequest(CameraDevice.TEMPLATE_PREVIEW);request.addTarget(r.getSurface());
            if(cabinPreview!=null&&cabinPreview.isValid()){outputs.add(new OutputConfiguration(cabinPreview));request.addTarget(cabinPreview);}
            request.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE,fps("1",30));
            session(device,outputs,request,true);
        }catch(Exception e){if(cabinOnly)error("cabin_configuration",e);else disableCabin(e.toString());}
    }
    private void session(CameraDevice device,List<OutputConfiguration> outputs,CaptureRequest.Builder request,boolean cabin) throws Exception {
        final int current=generation;
        SessionConfiguration config=new SessionConfiguration(SessionConfiguration.SESSION_REGULAR,outputs,command->handler.post(command),new CameraCaptureSession.StateCallback(){
            public void onConfigured(CameraCaptureSession s){
                if(stopped||current!=generation){s.close();return;}
                sessions.add(s);
                try{s.setRepeatingRequest(request.build(),null,handler);state.put(cabin?"cabin_available":"rear_available",true).put("state","running");publish();}
                catch(Exception e){if(cabin&&!cabinOnly)disableCabin(e.toString());else error("repeating",e);}
            }
            public void onConfigureFailed(CameraCaptureSession s){s.close();if(stopped||current!=generation)return;if(combinedActive)combinedFailed("session_configuration_failed");else if(cabin&&!cabinOnly)disableCabin("session_configuration_failed");else error("session_configuration",new IllegalStateException("Camera session rejected"));}
        });config.setSessionParameters(request.build());device.createCaptureSession(config);
    }
    private void recover(String camera,String why){
        if(combinedActive){combinedFailed(camera+": "+why);return;}
        if(camera.equals("1")&&!cabinOnly){disableCabin(why);return;}
        if(retries++==0){
            try{state.put("state","recovering").put("recovery_reason",why).put("rear_available",false).put("cabin_available",false);}catch(Exception ignored){}
            generation++;closeDevices();cabinDisabled=true;rearConfigPending=false;publish();
            handler.postDelayed(()->{if(!stopped){if(cabinOnly)open("1",false);else prepareRearRecovery(0);}},1500);
        }else error("camera_failure",new IllegalStateException(why));
    }
    private void openRearOnly(){
        final int current=generation;
        try{manager.openCamera("20",new CameraDevice.StateCallback(){
            public void onOpened(CameraDevice d){if(stopped||current!=generation){d.close();return;}devices.put("20",d);configureRear();}
            public void onDisconnected(CameraDevice d){d.close();if(!stopped)error("rear_recovery",new IllegalStateException("disconnected"));}
            public void onError(CameraDevice d,int e){d.close();if(!stopped)error("rear_recovery",new IllegalStateException("camera_error_"+e));}
        },handler);}catch(Exception e){error("rear_recovery",e);}
    }
    private void closeDevices(){
        for(ImageReader r:readers)try{r.setOnImageAvailableListener(null,null);}catch(Exception ignored){}
        for(CameraCaptureSession s:sessions)try{s.close();}catch(Exception ignored){}sessions.clear();
        for(CameraDevice d:devices.values())try{d.close();}catch(Exception ignored){}devices.clear();
        // Acquired Images own the direct plane pointers used by native packing.
        // Finish those callbacks before ImageReader.close invalidates the planes.
        for(HandlerThread t:captureThreads)t.quitSafely();
        for(HandlerThread t:captureThreads)try{t.join(2000);if(t.isAlive())throw new IllegalStateException("Capture callback failed to stop");}
            catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new IllegalStateException("Capture cleanup interrupted",interrupted);}
        captureThreads.clear();
        for(ImageReader r:readers)try{r.close();}catch(Exception ignored){}readers.clear();
    }
    private void error(String where,Exception failure){
        android.util.Log.e("OpenpilotLive",where,failure);
        try{if(state==null)state=new JSONObject();state.put("state","failed").put("error",where+": "+failure).put("rear_available",false).put("cabin_available",false);}catch(Exception ignored){}
        shutdown(false);
    }
    private void shutdown(boolean intentional){
        if(stopped)return;
        stopped=true;generation++;handler.removeCallbacksAndMessages(null);closeDevices();
        try{if(state!=null){if(intentional)state.put("state","stopped");publish();}}catch(Exception ignored){}
        NativeBridge.captureStop();
    }
    private final ILiveCamera.Stub binder=new ILiveCamera.Stub(){
        public void start(String session,String mode,Surface road,Surface cabin,int displayRotation){handler.post(()->begin(session,mode,road,cabin,displayRotation));}
        public String status(){return report;}
        public Bitmap thumbnail(int stream){Bitmap bitmap=Bitmap.createBitmap(320,180,Bitmap.Config.ARGB_8888);return NativeBridge.captureThumbnail(stream,bitmap)?bitmap:null;}
        public void stop(){handler.post(()->shutdown(true));}
        public void resetCounters(){handler.post(()->{if(!stopped){NativeBridge.captureResetCounters();try{state.put("measurement_start_monotonic_ns",System.nanoTime());}catch(Exception ignored){}publish();}});}
    };
    @Override public IBinder onBind(Intent intent){return binder;}
    @Override public boolean onUnbind(Intent intent){handler.post(()->shutdown(true));return false;}
    @Override public void onDestroy(){handler.post(()->{shutdown(true);thread.quitSafely();});super.onDestroy();}
}
