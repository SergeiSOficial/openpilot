package ai.comma.openpilot.sim;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.location.GnssCapabilities;
import android.location.GnssMeasurement;
import android.location.GnssMeasurementsEvent;
import android.location.GnssStatus;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.SystemClock;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.ArrayDeque;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Bounded diagnostics and session-owned live collection; never attached to replay. */
public final class HardwareSensors implements AutoCloseable {
    private static final int PERIOD_US = 10_000, MAX_SAMPLES = 4096;
    private final Context context;
    private final Object lock = new Object();
    private final SensorManager sensors;
    private final LocationManager locations;
    private final CountDownLatch stopped = new CountDownLatch(1);
    private final JSONArray errors = new JSONArray(), fixes = new JSONArray(), bands = new JSONArray();
    private final Set<String> seenBands = new HashSet<>();
    private final JSONObject gnss = new JSONObject();
    private final Stream acceleration, gyroscope;
    private HandlerThread thread;
    private Handler handler;
    private boolean started, active, closed, sensorRegistered, locationRegistered, statusRegistered, rawRegistered;
    private long startedNs, stoppedNs, durationMs, lastFixNs;
    private int rawBatches, statusCallbacks, invalidFixes, nonmonotonicFixes;
    private JSONArray satellites = new JSONArray();
    private boolean continuous;
    private final ArrayDeque<JSONObject> liveFixes = new ArrayDeque<>();

    private static final class Stream {
        final Sensor sensor;
        final String units;
        final boolean bias;
        final JSONArray samples = new JSONArray();
        final ArrayDeque<JSONObject> pending = new ArrayDeque<>();
        int stale, overflow;
        long firstNs, lastNs;
        int received, invalidValues, nonmonotonic, dropped;
        boolean registered;
        Stream(Sensor sensor, String units, boolean bias) { this.sensor=sensor; this.units=units; this.bias=bias; }
        JSONObject json() throws JSONException {
            JSONObject result=new JSONObject().put("available",sensor!=null).put("registered_successfully",registered)
                .put("units",units).put("bias_fields",bias).put("requested_period_us",PERIOD_US)
                .put("received",received).put("invalid_values",invalidValues).put("nonmonotonic_timestamps",nonmonotonic)
                .put("dropped_at_capacity",dropped).put("first_timestamp_ns",firstNs).put("last_timestamp_ns",lastNs)
                .put("stale_rejected",stale).put("queue_overflow",overflow).put("queue_depth",pending.size())
                .put("measured_hz",received>1 && lastNs>firstNs ? (received-1)*1e9/(lastNs-firstNs) : JSONObject.NULL)
                .put("samples",samples);
            if(sensor!=null)result.put("name",sensor.getName()).put("vendor",sensor.getVendor())
                .put("version",sensor.getVersion()).put("min_delay_us",sensor.getMinDelay())
                .put("resolution",sensor.getResolution()).put("maximum_range",sensor.getMaximumRange());
            return result;
        }
    }

    public HardwareSensors(Context context) {
        this.context=context.getApplicationContext();
        sensors=this.context.getSystemService(SensorManager.class);
        locations=this.context.getSystemService(LocationManager.class);
        acceleration=new Stream(sensors==null ? null : sensors.getDefaultSensor(Sensor.TYPE_ACCELEROMETER),"m/s^2",false);
        gyroscope=new Stream(sensors==null ? null : sensors.getDefaultSensor(Sensor.TYPE_GYROSCOPE_UNCALIBRATED),"rad/s",true);
    }

    public void start(long collectionMs) {
        if(collectionMs<1 || collectionMs>15_000)throw new IllegalArgumentException("Collection must be 1..15000 ms");
        synchronized(lock) {
            if(started || closed)throw new IllegalStateException("Diagnostic is single-use");
            started=true;active=true;durationMs=collectionMs;startedNs=SystemClock.elapsedRealtimeNanos();
            thread=new HandlerThread("openpilot-hardware-diagnostic");thread.start();handler=new Handler(thread.getLooper());
            handler.post(this::registerOnWorker);handler.postDelayed(this::stopOnWorker,collectionMs);
        }
    }

    public void startContinuous() {
        synchronized(lock) {
            if(started || closed)throw new IllegalStateException("Collector is single-use");
            continuous=true;started=true;active=true;startedNs=SystemClock.elapsedRealtimeNanos();
            thread=new HandlerThread("openpilot-live-sensors");thread.start();handler=new Handler(thread.getLooper());
            handler.post(this::registerOnWorker);
        }
    }

    public String drain() {
        synchronized(lock) {
            try {
                JSONArray acc=new JSONArray(),gyro=new JSONArray(),gps=new JSONArray();
                while(!acceleration.pending.isEmpty())acc.put(acceleration.pending.removeFirst());
                while(!gyroscope.pending.isEmpty())gyro.put(gyroscope.pending.removeFirst());
                while(!liveFixes.isEmpty())gps.put(liveFixes.removeFirst());
                return new JSONObject().put("accelerometer",acc).put("gyroscope",gyro).put("gps",gps).toString();
            } catch(JSONException error) {throw new IllegalStateException(error);}
        }
    }

    private final SensorEventListener sensorListener=new SensorEventListener() {
        @Override public void onAccuracyChanged(Sensor sensor,int accuracy) { }
        @Override public void onSensorChanged(SensorEvent event) {
            synchronized(lock) {
                if(!active)return;
                Stream stream=event.sensor.getType()==Sensor.TYPE_ACCELEROMETER ? acceleration : gyroscope;
                int fields=stream.bias ? 6 : 3;
                if(event.values.length<fields) {stream.invalidValues++;return;}
                for(int i=0;i<fields;i++)if(!Float.isFinite(event.values[i])) {stream.invalidValues++;return;}
                long receivedNs=SystemClock.elapsedRealtimeNanos();
                if(event.timestamp<=0 || event.timestamp<=stream.lastNs || event.timestamp>receivedNs) {stream.nonmonotonic++;return;}
                if(receivedNs-event.timestamp>100_000_000L) {stream.stale++;return;}
                if(stream.received++==0)stream.firstNs=event.timestamp;
                stream.lastNs=event.timestamp;
                if(!continuous && stream.samples.length()>=MAX_SAMPLES) {stream.dropped++;return;}
                try {
                    JSONArray values=new JSONArray(),bias=new JSONArray();
                    for(int i=0;i<3;i++)values.put((double)event.values[i]);
                    JSONObject sample=new JSONObject().put("timestamp_ns",event.timestamp).put("received_elapsed_realtime_ns",receivedNs)
                        .put("accuracy",event.accuracy).put("value",values);
                    if(stream.bias) {for(int i=3;i<6;i++)bias.put((double)event.values[i]);sample.put("bias",bias);}
                    if(continuous) {
                        if(stream.pending.size()>=512) {stream.pending.removeFirst();stream.overflow++;}
                        stream.pending.addLast(sample);
                    } else stream.samples.put(sample);
                } catch(JSONException error) {recordError("sensor_sample",error);}
            }
        }
    };

    private final LocationListener locationListener=new LocationListener() {
        @Override public void onLocationChanged(Location location) { synchronized(lock) {if(active)recordFix(location);} }
        @Override public void onProviderEnabled(String provider) { synchronized(lock) {if(active) {putGnss("provider_enabled",true);putGnss("state","listening");}} }
        @Override public void onProviderDisabled(String provider) { synchronized(lock) {if(active) {putGnss("provider_enabled",false);putGnss("state","provider_disabled");}} }
        @Override public void onStatusChanged(String provider,int status,Bundle extras) { }
    };

    private final GnssStatus.Callback statusCallback=new GnssStatus.Callback() {
        @Override public void onStarted() { synchronized(lock) {if(active)putGnss("engine_started",true);} }
        @Override public void onStopped() { synchronized(lock) {if(active)putGnss("engine_started",false);} }
        @Override public void onSatelliteStatusChanged(GnssStatus status) {
            synchronized(lock) {
                if(!active)return;
                statusCallbacks++;JSONArray latest=new JSONArray();
                try {
                    for(int i=0;i<Math.min(status.getSatelliteCount(),128);i++) {
                        JSONObject satellite=new JSONObject().put("svid",status.getSvid(i)).put("constellation_type",status.getConstellationType(i))
                            .put("used_in_fix",status.usedInFix(i)).put("cn0_dbhz",number(status.getCn0DbHz(i)));
                        satellite.put("carrier_frequency_hz",status.hasCarrierFrequencyHz(i) ? number(status.getCarrierFrequencyHz(i)) : JSONObject.NULL);
                        latest.put(satellite);
                    }
                    satellites=latest;
                } catch(JSONException error) {recordError("satellite_status",error);}
            }
        }
    };

    private final GnssMeasurementsEvent.Callback rawCallback=new GnssMeasurementsEvent.Callback() {
        @Override public void onGnssMeasurementsReceived(GnssMeasurementsEvent event) {
            synchronized(lock) {
                if(!active)return;
                rawBatches++;
                try {
                    putGnss("last_raw_received_elapsed_realtime_ns",SystemClock.elapsedRealtimeNanos());
                    for(GnssMeasurement measurement:event.getMeasurements()) {
                        Object frequency=measurement.hasCarrierFrequencyHz() ? number(measurement.getCarrierFrequencyHz()) : JSONObject.NULL;
                        String key=measurement.getConstellationType()+":"+frequency+":"+measurement.getCodeType();
                        if(seenBands.size()>=128 || !seenBands.add(key))continue;
                        bands.put(new JSONObject().put("constellation_type",measurement.getConstellationType())
                            .put("carrier_frequency_hz",frequency).put("code_type",measurement.getCodeType()));
                    }
                } catch(JSONException error) {recordError("raw_measurements",error);}
            }
        }
    };

    private void registerOnWorker() {
        synchronized(lock) {
            if(!active)return;
            for(Stream stream:new Stream[]{acceleration,gyroscope})if(stream.sensor!=null) {
                try {stream.registered=sensors.registerListener(sensorListener,stream.sensor,PERIOD_US,0,handler);sensorRegistered|=stream.registered;}
                catch(RuntimeException error) {recordError("sensor_registration",error);}
            }
            boolean fine=context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION)==PackageManager.PERMISSION_GRANTED;
            putGnss("fine_permission_granted",fine);
            putGnss("coarse_permission_granted",context.checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION)==PackageManager.PERMISSION_GRANTED);
            putGnss("permission_requested",false);putGnss("fix_state","no_fix_received");
            putGnss("fix_registration_succeeded",false);putGnss("status_registration_succeeded",false);putGnss("raw_registration_succeeded",false);
            if(locations==null) {putGnss("state","location_service_unavailable");return;}
            try {
                boolean provider=locations.getAllProviders().contains(LocationManager.GPS_PROVIDER);
                putGnss("gps_provider_present",provider);putGnss("location_enabled",locations.isLocationEnabled());
                GnssCapabilities capability=locations.getGnssCapabilities();
                putGnss("raw_measurements_supported",capability.hasMeasurements());
                putGnss("navigation_messages_supported",capability.hasNavigationMessages());
                if(!provider) {putGnss("state","gps_provider_unavailable");return;}
                boolean enabled=locations.isProviderEnabled(LocationManager.GPS_PROVIDER);putGnss("provider_enabled",enabled);
                if(!fine) {putGnss("state","fine_permission_missing");return;}
                if(!enabled) {putGnss("state","provider_disabled");return;}
                locations.requestLocationUpdates(LocationManager.GPS_PROVIDER,1000,0,locationListener,handler.getLooper());
                locationRegistered=true;putGnss("fix_registration_succeeded",true);putGnss("state","listening");
                statusRegistered=locations.registerGnssStatusCallback(statusCallback,handler);
                if(capability.hasMeasurements())rawRegistered=locations.registerGnssMeasurementsCallback(rawCallback,handler);
                putGnss("status_registration_succeeded",statusRegistered);putGnss("raw_registration_succeeded",rawRegistered);
            } catch(RuntimeException error) {putGnss("state","registration_error");recordError("gnss_registration",error);}
        }
    }

    private void recordFix(Location location) {
        if(!LocationManager.GPS_PROVIDER.equals(location.getProvider())) {invalidFixes++;return;}
        if(!Double.isFinite(location.getLatitude()) || !Double.isFinite(location.getLongitude())
            || Math.abs(location.getLatitude())>90 || Math.abs(location.getLongitude())>180) {invalidFixes++;return;}
        long timestamp=location.getElapsedRealtimeNanos(),now=SystemClock.elapsedRealtimeNanos();
        if(timestamp<=0 || timestamp<=lastFixNs || timestamp>now) {nonmonotonicFixes++;return;}
        if(now-timestamp>2_000_000_000L || location.isFromMockProvider()) {invalidFixes++;return;}
        lastFixNs=timestamp;
        try {
            JSONObject fix=new JSONObject().put("provider",location.getProvider()).put("timestamp_ns",timestamp)
                .put("received_elapsed_realtime_ns",now).put("age_ms",(now-timestamp)/1e6)
                .put("latitude_deg",location.getLatitude()).put("longitude_deg",location.getLongitude())
                .put("utc_time_ms",location.getTime()).put("mock",location.isFromMockProvider())
                .put("horizontal_accuracy_m",location.hasAccuracy() ? number(location.getAccuracy()) : JSONObject.NULL)
                .put("altitude_wgs84_m",location.hasAltitude() ? number(location.getAltitude()) : JSONObject.NULL)
                .put("vertical_accuracy_m",location.hasVerticalAccuracy() ? number(location.getVerticalAccuracyMeters()) : JSONObject.NULL)
                .put("speed_m_s",location.hasSpeed() ? number(location.getSpeed()) : JSONObject.NULL)
                .put("speed_accuracy_m_s",location.hasSpeedAccuracy() ? number(location.getSpeedAccuracyMetersPerSecond()) : JSONObject.NULL)
                .put("bearing_deg",location.hasBearing() ? number(location.getBearing()) : JSONObject.NULL)
                .put("bearing_accuracy_deg",location.hasBearingAccuracy() ? number(location.getBearingAccuracyDegrees()) : JSONObject.NULL)
                .put("elapsed_realtime_uncertainty_ns",location.hasElapsedRealtimeUncertaintyNanos() ? number(location.getElapsedRealtimeUncertaintyNanos()) : JSONObject.NULL);
            if(continuous) {if(liveFixes.size()>=32)liveFixes.removeFirst();liveFixes.addLast(fix);}
            else if(fixes.length()<32)fixes.put(fix);
            putGnss("fix_state","fix_received_unvalidated");
        } catch(JSONException error) {invalidFixes++;recordError("gps_fix",error);}
    }

    private static Object number(double value) {return Double.isFinite(value) ? value : JSONObject.NULL;}
    private void putGnss(String key,Object value) {try {gnss.put(key,value);} catch(JSONException error) {throw new IllegalStateException(error);}}
    private void recordError(String operation,Exception error) {if(errors.length()<64)errors.put(operation+": "+error.getClass().getSimpleName()+": "+error.getMessage());}

    private void stopOnWorker() {
        synchronized(lock) {
            if(closed)return;
            active=false;handler.removeCallbacksAndMessages(null);
            if(sensorRegistered)try {sensors.unregisterListener(sensorListener);sensorRegistered=false;} catch(RuntimeException error) {recordError("sensor_cleanup",error);}
            if(locationRegistered)try {locations.removeUpdates(locationListener);locationRegistered=false;} catch(RuntimeException error) {recordError("location_cleanup",error);}
            if(statusRegistered)try {locations.unregisterGnssStatusCallback(statusCallback);statusRegistered=false;} catch(RuntimeException error) {recordError("status_cleanup",error);}
            if(rawRegistered)try {locations.unregisterGnssMeasurementsCallback(rawCallback);rawRegistered=false;} catch(RuntimeException error) {recordError("raw_cleanup",error);}
            stoppedNs=SystemClock.elapsedRealtimeNanos();closed=true;thread.quitSafely();stopped.countDown();
        }
    }

    public boolean awaitStopped(long timeoutMs) throws InterruptedException {return stopped.await(timeoutMs,TimeUnit.MILLISECONDS);}

    @Override public void close() {
        HandlerThread worker;
        synchronized(lock) {
            if(!started) {closed=true;stopped.countDown();return;}
            worker=thread;
            if(!closed)handler.post(this::stopOnWorker);
        }
        if(Thread.currentThread()==worker)return;
        try {
            if(!stopped.await(2000,TimeUnit.MILLISECONDS))throw new IllegalStateException("Sensor cleanup timed out");
            worker.join(2000);
            if(worker.isAlive())throw new IllegalStateException("Sensor diagnostic thread did not stop");
        } catch(InterruptedException error) {Thread.currentThread().interrupt();throw new IllegalStateException("Sensor cleanup interrupted",error);}
    }

    public JSONObject snapshot() {
        synchronized(lock) {
            try {
                long now=SystemClock.elapsedRealtimeNanos();
                String rawState=rawBatches>0 ? "measurements_received" : gnss.optBoolean("raw_registration_succeeded") ? "registered_no_measurements_received"
                    : gnss.has("raw_measurements_supported") && !gnss.optBoolean("raw_measurements_supported") ? "unsupported" : "not_registered";
                JSONObject result=new JSONObject().put("schema_version",1).put("purpose","local_hardware_diagnostic")
                    .put("model",Build.MODEL).put("requested_duration_ms",durationMs).put("started_elapsed_realtime_ns",startedNs)
                    .put("stopped_elapsed_realtime_ns",stoppedNs).put("report_elapsed_realtime_ns",now).put("running",active)
                    .put("coordinate_frame","raw Android phone axes: +X right, +Y top, +Z out of screen; natural orientation; no UI rotation or mounting transform")
                    .put("timebase","elapsedRealtimeNanos / BOOTTIME, includes suspend")
                    .put("accelerometer_includes_gravity",true).put("mount_calibrated",false).put("locationd_validated",false)
                    .put("fold_state","not_measured; operator must keep phone folded")
                    .put("accelerometer",acceleration.json()).put("gyroscope_uncalibrated",gyroscope.json())
                    .put("gnss",gnss.put("fixes",fixes).put("satellites",satellites).put("observed_signal_bands",bands)
                        .put("raw_batches",rawBatches).put("raw_measurement_state",rawState).put("status_callbacks",statusCallbacks).put("invalid_fixes",invalidFixes)
                        .put("last_fix_age_ms",lastFixNs>0 ? (now-lastFixNs)/1e6 : JSONObject.NULL)
                        .put("nonmonotonic_fix_timestamps",nonmonotonicFixes))
                    .put("cleanup",new JSONObject().put("closed",closed).put("thread_alive",thread!=null && thread.isAlive())
                        .put("sensor_listener_registered",sensorRegistered).put("location_listener_registered",locationRegistered)
                        .put("status_callback_registered",statusRegistered).put("raw_callback_registered",rawRegistered))
                    .put("errors",errors);
                return new JSONObject(result.toString());
            } catch(JSONException error) {throw new IllegalStateException(error);}
        }
    }

    public File writeReport() throws IOException {
        File directory=new File(context.getFilesDir(),"hardware");
        if(!directory.isDirectory() && !directory.mkdirs())throw new IOException("Cannot create hardware diagnostics directory");
        File result=new File(directory,"sensors.json");
        try(FileOutputStream output=new FileOutputStream(result)) {output.write(snapshot().toString().getBytes(StandardCharsets.UTF_8));}
        return result;
    }
}
