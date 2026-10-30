package ai.comma.openpilot.sim;

import android.Manifest;
import android.app.Activity;
import android.content.*;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.os.*;
import android.view.*;
import android.widget.*;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;
import java.util.Arrays;
import java.util.concurrent.*;
import org.json.*;

/** Parked, disengaged live-camera diagnostics; no vehicle transport is instantiated. */
public final class LiveActivity extends Activity {
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService executor=Executors.newSingleThreadExecutor();
    private ILiveCamera camera;
    private IWorker worker;
    private SurfaceView roadSurface,cabinSurface;
    private final ImageView[] thumbnails=new ImageView[3];
    private TextView status;
    private Spinner modes,seats;
    private String session;
    private boolean cameraBound,workerBound,busy,autoStart;
    private volatile boolean active,polling;
    private volatile int runGeneration;
    private boolean measurementStarted;
    private File root;
    private int captureRotation=-1;
    private final android.hardware.display.DisplayManager.DisplayListener displayListener=new android.hardware.display.DisplayManager.DisplayListener(){
        public void onDisplayAdded(int id){}
        public void onDisplayRemoved(int id){}
        public void onDisplayChanged(int id){if(active&&usesCamera()&&getDisplay()!=null&&id==getDisplay().getDisplayId()&&getDisplay().getRotation()!=captureRotation)stopRun("Display rotated; restart after checking camera orientation");}
    };
    private final ServiceConnection cameraConnection=new ServiceConnection(){
        public void onServiceConnected(ComponentName name,IBinder binder){camera=ILiveCamera.Stub.asInterface(binder);maybeAutoStart();}
        public void onServiceDisconnected(ComponentName name){camera=null;if(active)failRun("Capture process disconnected",true);}
        public void onBindingDied(ComponentName name){camera=null;if(active)failRun("Capture process died",true);}
    };
    private final ServiceConnection workerConnection=new ServiceConnection(){
        public void onServiceConnected(ComponentName name,IBinder binder){worker=IWorker.Stub.asInterface(binder);maybeAutoStart();}
        public void onServiceDisconnected(ComponentName name){worker=null;if(active)failRun("Inference worker disconnected",false);}
        public void onBindingDied(ComponentName name){worker=null;if(active)failRun("Inference worker died",false);}
    };
    @Override public void onCreate(Bundle saved){
        super.onCreate(saved);getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout column=new LinearLayout(this);column.setOrientation(LinearLayout.VERTICAL);
        column.setPadding(dp(8),dp(8),dp(8),dp(8));
        column.setOnApplyWindowInsetsListener((v,insets)->{android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars());v.setPadding(dp(8)+bars.left,dp(8)+bars.top,dp(8)+bars.right,dp(8)+bars.bottom);return insets;});
        TextView title=new TextView(this);title.setText("openpilot · Live shadow · Stationary inputs · No vehicle control");title.setTextSize(15);column.addView(title);
        LinearLayout toolbar=new LinearLayout(this);
        modes=new Spinner(this);modes.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"Live Shadow","Cabin Diagnostic","Road GPU validation","Rear Capture Diagnostic","Cabin GPU validation"}));toolbar.addView(modes,new LinearLayout.LayoutParams(0,-2,1));
        seats=new Spinner(this);seats.setAdapter(new ArrayAdapter<>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"Seat not configured","Left-hand drive","Right-hand drive"}));toolbar.addView(seats,new LinearLayout.LayoutParams(0,-2,1));
        addButton(toolbar,"Start",this::startRun);addButton(toolbar,"Stop",()->stopRun("Stopped"));addButton(toolbar,"Recorded",()->{stopRun("Recorded mode");finish();});column.addView(toolbar);
        LinearLayout previews=new LinearLayout(this);
        roadSurface=new SurfaceView(this);roadSurface.getHolder().setFixedSize(1920,1080);previews.addView(roadSurface,new LinearLayout.LayoutParams(0,dp(92),2));
        cabinSurface=new SurfaceView(this);cabinSurface.getHolder().setFixedSize(1280,720);previews.addView(cabinSurface,new LinearLayout.LayoutParams(0,dp(92),1));column.addView(previews);
        LinearLayout body=new LinearLayout(this);
        LinearLayout images=new LinearLayout(this);images.setOrientation(LinearLayout.VERTICAL);
        for(int n=0;n<3;n++){TextView label=new TextView(this);label.setText(new String[]{"Road · middle lens","Cabin · cover camera","Road · bottom lens"}[n]);images.addView(label);thumbnails[n]=new ImageView(this);thumbnails[n].setScaleType(ImageView.ScaleType.FIT_CENTER);images.addView(thumbnails[n],new LinearLayout.LayoutParams(-1,dp(72)));}
        body.addView(images,new LinearLayout.LayoutParams(0,-1,1));
        ScrollView scroll=new ScrollView(this);status=new TextView(this);status.setTextSize(12);status.setText("Ready. Live outputs are bench diagnostics. Calibration and timing are not validated.");scroll.addView(status);body.addView(scroll,new LinearLayout.LayoutParams(0,-1,2));column.addView(body,new LinearLayout.LayoutParams(-1,0,1));setContentView(column);
        String mode=getIntent().getStringExtra("mode");if("cabin".equals(mode))modes.setSelection(1);else if("gpucheck".equals(mode))modes.setSelection(2);else if("capture".equals(mode))modes.setSelection(3);else if("drivergpucheck".equals(mode))modes.setSelection(4);
        String configuredSeat=getIntent().getStringExtra("driver_seat");
        if(configuredSeat==null)configuredSeat=getPreferences(MODE_PRIVATE).getString("driver_seat","unset");
        seats.setSelection("right".equals(configuredSeat)?2:"left".equals(configuredSeat)?1:0);
        autoStart=getIntent().getBooleanExtra("autostart",false);
        SurfaceHolder.Callback callback=new SurfaceHolder.Callback(){public void surfaceCreated(SurfaceHolder h){maybeAutoStart();}public void surfaceChanged(SurfaceHolder h,int f,int w,int x){maybeAutoStart();}public void surfaceDestroyed(SurfaceHolder h){if(active&&usesCamera())stopRun("Preview surface lost");}};
        roadSurface.getHolder().addCallback(callback);cabinSurface.getHolder().addCallback(callback);
        if(checkSelfPermission(Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED)requestPermissions(new String[]{Manifest.permission.CAMERA},1);
        else if(checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)!=PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.ACCESS_COARSE_LOCATION,Manifest.permission.ACCESS_FINE_LOCATION},2);
    }
    private int dp(int value){return Math.round(value*getResources().getDisplayMetrics().density);}
    private boolean usesCamera(){return modes!=null&&modes.getSelectedItemPosition()!=2&&modes.getSelectedItemPosition()!=4;}
    private void addButton(LinearLayout row,String title,Runnable action){Button b=new Button(this);b.setText(title);b.setAllCaps(false);b.setMinWidth(0);b.setTextSize(12);b.setOnClickListener(v->action.run());row.addView(b);}
    private void show(String text){runOnUiThread(()->status.setText(text));}
    private void bind(){
        if(!cameraBound)cameraBound=bindService(new Intent(this,LiveCameraService.class),cameraConnection,BIND_AUTO_CREATE);
        if(!workerBound)workerBound=bindService(new Intent(this,WorkerService.Live.class),workerConnection,BIND_AUTO_CREATE);
    }
    private void maybeAutoStart(){
        if(autoStart&&!active&&camera!=null&&worker!=null&&roadSurface.getHolder().getSurface().isValid()&&cabinSurface.getHolder().getSurface().isValid()&&checkSelfPermission(Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED){autoStart=false;startRun();}
    }
    private void startRun(){
        if(active)return;
        if(camera==null||worker==null){autoStart=true;bind();return;}
        if(checkSelfPermission(Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{Manifest.permission.CAMERA},1);return;}
        String mode=new String[]{"live","cabin","gpucheck","capture","drivergpucheck"}[modes.getSelectedItemPosition()];
        final boolean gpuCheck=mode.equals("gpucheck")||mode.equals("drivergpucheck");
        if(!gpuCheck&&(!roadSurface.getHolder().getSurface().isValid()||!cabinSurface.getHolder().getSurface().isValid())){show("Waiting for preview surfaces");return;}
        session=UUID.randomUUID().toString().replace("-","").substring(0,16);root=new File(getFilesDir(),"s/"+session);root.mkdirs();new File(root,"shm").mkdirs();
        final String currentSession=session;final int generation=++runGeneration;
        active=true;measurementStarted=false;modes.setEnabled(false);seats.setEnabled(false);
        final String seat=new String[]{"unset","left","right"}[seats.getSelectedItemPosition()];
        getPreferences(MODE_PRIVATE).edit().putString("driver_seat",seat).apply();
        final ILiveCamera currentCamera=camera;final IWorker currentWorker=worker;
        final Surface road=roadSurface.getHolder().getSurface(),cabin=cabinSurface.getHolder().getSurface();
        final String captureMode=mode;
        captureRotation=getDisplay().getRotation();final int rotation=captureRotation*90;
        final int seconds=Math.max(5,Math.min(1200,getIntent().getIntExtra("seconds",1200)));
        executor.submit(()->{
            try{
                if(!active||!polling||generation!=runGeneration)return;
                Files.write(new File(getFilesDir(),"last-live-session.txt").toPath(),currentSession.getBytes(StandardCharsets.UTF_8));
                if(!gpuCheck)currentCamera.start(currentSession,captureMode,road,cabin,rotation);
                if(!active||!polling||generation!=runGeneration){currentCamera.stop();return;}
                JSONObject environment=new JSONObject().put("OPENPILOT_ANDROID_MODE",mode).put("OPENPILOT_ANDROID_SEAT",seat).put("OPENPILOT_ANDROID_DURATION",Integer.toString(seconds));
                currentWorker.startConfigured(currentSession,"live",environment.toString());
                if(!active||!polling||generation!=runGeneration){currentCamera.stop();currentWorker.stop();}
            }catch(Exception e){show("Live startup failed: "+e);runOnUiThread(()->stopRun("Startup failed"));}
        });show("Starting "+mode+". Collecting cameras and sensors; road inference requires sustained qualification.");
    }
    private void stopRun(String why){
        android.util.Log.i("OpenpilotLive","Stop: "+why);
        boolean wasActive=active;active=false;runGeneration++;modes.setEnabled(true);seats.setEnabled(true);
        ILiveCamera c=camera;IWorker w=worker;worker=null;
        if(c!=null)try{c.stop();}catch(Exception ignored){}
        if(w!=null)executor.submit(()->{try{w.stop();}catch(Exception ignored){}});
        if(workerBound){try{unbindService(workerConnection);}catch(Exception ignored){}workerBound=false;}
        if(wasActive)show(why+". Start creates a fresh session.");
        if(polling)handler.postDelayed(this::bind,250);
    }
    private void failRun(String why,boolean captureFailure){
        final File failedRoot=root;stopRun(why);
        if(failedRoot!=null)executor.submit(()->{
            try{
                for(String name:captureFailure?new String[]{"progress.json","verification.json","camera.json"}:new String[]{"progress.json","verification.json"}){
                    File target=new File(failedRoot,name);
                    JSONObject value=target.isFile()?new JSONObject(new String(Files.readAllBytes(target.toPath()),StandardCharsets.UTF_8)):new JSONObject();
                    value.put("state","failed").put("error",why).put("verification_passed",false).put("driver_monitoring_available",false);
                    if(name.equals("camera.json"))value.put("rear_available",false).put("cabin_available",false);
                    File temp=new File(failedRoot,name+".failure-tmp");Files.write(temp.toPath(),value.toString().getBytes(StandardCharsets.UTF_8));
                    Files.move(temp.toPath(),target.toPath(),java.nio.file.StandardCopyOption.REPLACE_EXISTING);
                }
            }catch(Exception e){android.util.Log.e("OpenpilotLive","Failure report",e);}
        });
    }
    private final Runnable poll=new Runnable(){public void run(){
        if(!polling)return;
        if(active&&!busy){busy=true;final File current=root;final ILiveCamera c=camera;executor.submit(()->{
            try{
                JSONObject cameraReport=c==null?new JSONObject():new JSONObject(c.status());
                IWorker currentWorker=worker;
                if(currentWorker==null)throw new IllegalStateException("Inference worker unavailable");
                JSONObject workerState=new JSONObject(currentWorker.status());
                if(Arrays.asList("failed","dead","stopped").contains(workerState.optString("state")))
                    throw new IllegalStateException("Inference worker stopped: "+workerState);
                JSONObject gpu=new JSONObject();File progress=new File(current,"progress.json");if(progress.isFile())gpu=new JSONObject(new String(Files.readAllBytes(progress.toPath()),StandardCharsets.UTF_8));
                if(c!=null&&usesCamera()&&!measurementStarted&&gpu.optString("stage").equals("live_inference")){c.resetCounters();measurementStarted=true;}
                StringBuilder text=new StringBuilder("STATIONARY / DISENGAGED · No vehicle connection\nCalibration provisional · No road-path overlay\n\n");
                text.append("Capture: ").append(cameraReport.optString("state","not started")).append('\n');
                if(cameraReport.has("error"))text.append(cameraReport.optString("error")).append('\n');
                text.append("Cabin: ").append(cameraReport.optBoolean("cabin_available")?"capturing":"unavailable").append(' ').append(cameraReport.optString("cabin_unavailable_reason","")).append('\n');
                text.append("Pipeline: ").append(gpu.optString("pipeline_state","initializing")).append('\n');
                text.append("Road inference: ").append(gpu.optBoolean("road_inference_available")?"qualified":"blocked").append(' ').append(gpu.optString("road_model_unavailable_reason","")).append('\n');
                JSONObject sensorReport=gpu.optJSONObject("sensors");
                if(sensorReport!=null)text.append("Sensors: ").append(sensorReport.optJSONObject("published")).append(" · mount calibrated ").append(sensorReport.optBoolean("mount_calibrated")).append('\n');
                JSONObject driverInfo=gpu.optJSONObject("driver_initialization");
                text.append("Driver backend: ").append(driverInfo==null?"unavailable":driverInfo.optString("backend")).append(" · seat ").append(gpu.optString("driver_seat","unset")).append('\n');
                text.append("Monitoring unavailable: ").append(gpu.optString("driver_monitoring_reason","initializing")).append('\n');
                text.append(String.format(java.util.Locale.ROOT,"Fresh outputs: road %.1f Hz · driver %.1f Hz (%d in last second)\n",gpu.optDouble("road_model_fps",0),gpu.optDouble("driver_model_fps",0),gpu.optInt("driver_fresh_outputs_last_second",0)));
                JSONObject driverOutput=gpu.optJSONObject("driver");
                if(driverOutput!=null){
                    text.append(String.format(java.util.Locale.ROOT,"Face %.2f · eyes %.2f / %.2f · blink %.2f / %.2f\n",driverOutput.optDouble("face_probability"),driverOutput.optDouble("left_eye_probability"),driverOutput.optDouble("right_eye_probability"),driverOutput.optDouble("left_blink_probability"),driverOutput.optDouble("right_blink_probability")));
                    text.append("Head pose: ").append(driverOutput.optJSONArray("head_orientation")).append(" · ").append(gpu.optString("driver_visibility")).append('\n');
                }
                for(String pipeline:new String[]{"road","driver"}){
                    JSONObject timing=gpu.optJSONObject(pipeline+"_timing");
                    if(timing!=null&&timing.optInt("samples")>0)text.append(String.format(java.util.Locale.ROOT,"%s cycle p95 %.1f ms · max %.1f ms\n",pipeline,timing.optDouble("p95_ms"),timing.optDouble("max_ms")));
                }
                text.append(String.format(java.util.Locale.ROOT,"Driver frame age %.1f ms · discarded %d · thermal %d\n",gpu.optDouble("driver_frame_age_ms",0),gpu.optInt("driver_frames_discarded",0),cameraReport.optInt("thermal_status",0)));
                JSONObject nativeStats=cameraReport.optJSONObject("native");if(nativeStats!=null)text.append(nativeStats.toString(1)).append('\n');
                text.append("\nInference:\n").append(gpu.toString(1));show(text.toString());
                if(c!=null&&usesCamera()&&cameraReport.optInt("thermal_status",0)<3)for(int n=0;n<3;n++){final int stream=n;android.graphics.Bitmap bitmap=c.thumbnail(n);if(bitmap!=null)runOnUiThread(()->thumbnails[stream].setImageBitmap(bitmap));}
                if(usesCamera()&&cameraReport.optString("state").equals("failed"))runOnUiThread(()->stopRun("Camera failed"));
                if(Arrays.asList("completed","failed").contains(gpu.optString("state"))){if(c!=null)c.stop();final String finished=text.toString();runOnUiThread(()->{stopRun("Session finished");show(finished);});}
            }catch(Exception e){runOnUiThread(()->{stopRun("Worker or capture failure");show("Capture released after worker/capture failure: "+e);});}finally{busy=false;}
        });}handler.postDelayed(this,1000);
    }};
    @Override public void onRequestPermissionsResult(int r,String[] p,int[] g){super.onRequestPermissionsResult(r,p,g);if(r==2){show("Location permission updated; unavailable GNSS remains explicitly reported.");maybeAutoStart();}else if(g.length>0&&g[0]==PackageManager.PERMISSION_GRANTED)maybeAutoStart();else show("Camera permission denied. Recorded mode remains available.");}
    @Override public void onConfigurationChanged(Configuration c){super.onConfigurationChanged(c);if(active&&usesCamera())stopRun("Rotation changed; restart after checking camera orientation");}
    @Override protected void onStart(){super.onStart();getSystemService(android.hardware.display.DisplayManager.class).registerDisplayListener(displayListener,handler);polling=true;bind();handler.post(poll);}
    @Override protected void onStop(){getSystemService(android.hardware.display.DisplayManager.class).unregisterDisplayListener(displayListener);polling=false;handler.removeCallbacks(poll);stopRun("Backgrounded");if(cameraBound){try{unbindService(cameraConnection);}catch(Exception ignored){}cameraBound=false;}super.onStop();}
    @Override protected void onDestroy(){executor.shutdown();super.onDestroy();}
}
