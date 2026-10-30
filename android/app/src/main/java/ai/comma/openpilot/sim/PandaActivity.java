package ai.comma.openpilot.sim;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.PendingIntent;
import android.content.*;
import android.hardware.usb.*;
import android.os.*;
import android.widget.*;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;

/** Explicit USB permission and passive Panda diagnostics. No engagement/firmware actions. */
public final class PandaActivity extends Activity {
    private static final String PERMISSION="ai.comma.openpilot.sim.USB_PERMISSION";
    private final java.util.concurrent.ExecutorService executor=Executors.newSingleThreadExecutor();
    private final AtomicInteger generation=new AtomicInteger();
    private final Object reportLock=new Object();
    private UsbManager manager;
    private TextView status;
    private volatile PandaMonitor monitor;
    private volatile boolean foreground;
    private String pendingDevice;
    private int pendingGeneration;
    private final BroadcastReceiver receiver=new BroadcastReceiver() {
        @Override public void onReceive(Context context,Intent intent) {
            UsbDevice device=intent.getParcelableExtra(UsbManager.EXTRA_DEVICE);
            if(UsbManager.ACTION_USB_DEVICE_DETACHED.equals(intent.getAction())) { disconnect("USB device detached"); return; }
            if(PERMISSION.equals(intent.getAction()) && foreground && device!=null
                    && device.getDeviceName().equals(pendingDevice) && pendingGeneration==generation.get()) {
                pendingDevice=null;
                if(intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED,false) && manager.hasPermission(device)) open(device);
                else show("USB permission denied. No device was opened.");
            }
        }
    };
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved); manager=(UsbManager)getSystemService(USB_SERVICE);
        LinearLayout root=new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);
        int pad=Math.round(10*getResources().getDisplayMetrics().density);
        root.setOnApplyWindowInsetsListener((view,insets)->{
            var bars=insets.getInsets(android.view.WindowInsets.Type.systemBars());
            view.setPadding(pad+bars.left,pad+bars.top,pad+bars.right,pad+bars.bottom); return insets;
        });
        TextView title=new TextView(this); title.setText("Red panda · Ioniq PHEV 2018"); title.setTextSize(20); root.addView(title);
        status=new TextView(this); status.setTextSize(14); status.setTextIsSelectable(true);
        ScrollView scroll=new ScrollView(this); scroll.addView(status); root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        LinearLayout controls=new LinearLayout(this);
        button(controls,"Connect / monitor",this::connect); button(controls,"Disconnect",()->disconnect("Disconnected"));
        button(controls,"Simulation",this::finish); root.addView(controls); setContentView(root);
        IntentFilter filter=new IntentFilter(PERMISSION); filter.addAction(UsbManager.ACTION_USB_DEVICE_DETACHED);
        if(Build.VERSION.SDK_INT>=33) registerReceiver(receiver,filter,Context.RECEIVER_NOT_EXPORTED); else registerReceiver(receiver,filter);
        show("Connect red panda directly to this phone using USB OTG or a powered hub.\n\nUSB host supported: "
            +getPackageManager().hasSystemFeature("android.hardware.usb.host"));
    }
    private void button(LinearLayout row,String label,Runnable action) {
        Button button=new Button(this); button.setText(label); button.setAllCaps(false); button.setSingleLine(true);
        button.setOnClickListener(view->action.run()); row.addView(button,new LinearLayout.LayoutParams(0,-2,1));
    }
    private void show(String text) {
        runOnUiThread(()->status.setText(text+"\n\nVehicle control is not enabled.\nLive vehicle identification, real-time model/camera input,"
            +" vehicle safety configuration and physical CAN tests are still required.\nRecorded simulation CAN never reaches USB."));
    }
    private void connect() {
        disconnect("Looking for red panda…");
        ArrayList<UsbDevice> devices=new ArrayList<>();
        for(UsbDevice device:manager.getDeviceList().values()) if(PandaUsbConnection.matches(device)) devices.add(device);
        if(devices.isEmpty()) { show("No red panda attached to the phone. Connect its USB cable through OTG or a powered hub."); return; }
        if(devices.size()>1) {
            String[] names=devices.stream().map(UsbDevice::getDeviceName).toArray(String[]::new);
            new AlertDialog.Builder(this).setTitle("Select red panda").setItems(names,(dialog,index)->permission(devices.get(index))).show();
        } else permission(devices.get(0));
    }
    private void permission(UsbDevice device) {
        if(manager.hasPermission(device)) { open(device); return; }
        pendingDevice=device.getDeviceName(); pendingGeneration=generation.get();
        PendingIntent callback=PendingIntent.getBroadcast(this,pendingGeneration,
            new Intent(PERMISSION).setPackage(getPackageName()),PendingIntent.FLAG_UPDATE_CURRENT|PendingIntent.FLAG_IMMUTABLE);
        manager.requestPermission(device,callback);
    }
    private void open(UsbDevice device) {
        final int token=generation.get();
        executor.submit(()->{
            PandaMonitor current=null;
            try {
                if(!foreground || token!=generation.get()) return;
                current=new PandaMonitor(new PandaProtocol(this),new PandaUsbConnection(manager,device)); monitor=current;
                if(!foreground || token!=generation.get()) return;
                JSONObject result=current.open(); long lastPublish=0;
                while(foreground && token==generation.get()) {
                    // Drain CAN continuously. UI/report updates are throttled independently.
                    long now=System.nanoTime();
                    if(now-lastPublish>=500_000_000L) {
                        synchronized(reportLock) {
                            if(!foreground || token!=generation.get()) break;
                            save(result);
                        }
                        final String text="Read-only USB link · protocol matched\nCAN frames: "+result.getLong("can_frames")
                            +"\nBus counts: "+result.getJSONArray("bus_counts")+"\nHealth: "+result.getJSONObject("health").toString(2);
                        runOnUiThread(()->{if(foreground && token==generation.get()) show(text);});
                        lastPublish=now;
                    }
                    result=current.poll();
                }
            } catch(Exception failure) {
                if(foreground && token==generation.get()) { show("Panda connection stopped: "+failure.getMessage());
                    try { synchronized(reportLock) { if(token==generation.get()) save(new JSONObject().put("state","failed").put("error",failure.toString()).put("actuation_allowed",false)); } } catch(Exception ignored) {} }
            } finally { if(current!=null) current.close(); if(monitor==current) monitor=null; }
        });
    }
    private void save(JSONObject result) throws Exception {
        File directory=new File(getFilesDir(),"panda"); if(!directory.isDirectory() && !directory.mkdirs()) throw new IllegalStateException("Cannot save Panda report");
        java.nio.file.Path temporary=new File(directory,"latest.tmp").toPath();
        Files.write(temporary,result.toString().getBytes(StandardCharsets.UTF_8));
        Files.move(temporary,new File(directory,"latest.json").toPath(),java.nio.file.StandardCopyOption.REPLACE_EXISTING);
    }
    private void disconnect(String reason) {
        generation.incrementAndGet(); pendingDevice=null;
        PandaMonitor current=monitor; monitor=null; if(current!=null) current.close();
        try { synchronized(reportLock) { save(new JSONObject().put("state","disconnected").put("reason",reason).put("actuation_allowed",false)); } } catch(Exception failure) { android.util.Log.e("PandaUsb","Cannot save disconnect report",failure); }
        show(reason);
    }
    @Override protected void onStart() { super.onStart(); foreground=true; }
    @Override protected void onStop() { foreground=false; disconnect("Backgrounded · USB connection closed"); super.onStop(); }
    @Override protected void onDestroy() { unregisterReceiver(receiver); executor.shutdownNow(); super.onDestroy(); }
}
