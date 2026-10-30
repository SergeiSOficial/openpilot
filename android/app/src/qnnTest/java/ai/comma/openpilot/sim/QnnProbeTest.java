package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import ai.onnxruntime.*;
import android.content.Intent;
import android.system.Os;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.nio.*;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.*;
import org.json.*;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Real HTP execution probe, not a driving-model or quantization certificate. */
@RunWith(AndroidJUnit4.class)
public class QnnProbeTest {
    private static String sha(byte[] data) throws Exception {
        var digest=MessageDigest.getInstance("SHA-256");StringBuilder value=new StringBuilder();
        for(byte item:digest.digest(data))value.append(String.format("%02x",item&255));return value.toString();
    }
    private static byte[] expected(byte[] input) {
        byte[] output=new byte[9];
        for(int y=0;y<3;y++)for(int x=0;x<3;x++) {
            int total=128;
            for(int dy=0;dy<3;dy++)for(int dx=0;dx<3;dx++)total+=(input[(y+dy)*5+x+dx]&255)-128;
            output[y*3+x]=(byte)Math.max(0,Math.min(255,total));
        }
        return output;
    }
    private static byte[] run(OrtEnvironment environment,OrtSession session,byte[] data) throws Exception {
        var storage=ByteBuffer.allocateDirect(25).order(ByteOrder.nativeOrder());storage.put(data);storage.clear();
        try(var input=OnnxTensor.createTensor(environment,storage,new long[]{1,1,5,5},OnnxJavaType.UINT8);
            var result=session.run(Map.of("X",input))) {
            var tensor=(OnnxTensor)result.get("Y").orElseThrow();
            var buffer=tensor.getByteBuffer();byte[] output=new byte[buffer.remaining()];buffer.get(output);return output;
        }
    }
    @Test(timeout=120000) public void quantizedConvolutionExecutesOnHtpWithoutCpuFallback() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();var context=instrumentation.getTargetContext();
        assertEquals("ai.comma.openpilot.acceleration",context.getPackageName());
        var directory=new File(context.getFilesDir(),"hardware");directory.mkdirs();
        var report=new JSONObject().put("schema",1).put("passed",false).put("htp_execution_verified",false)
            .put("attempt_id",InstrumentationRegistry.getArguments().getString("attemptId",""))
            .put("driving_model_accelerated",false).put("vehicle_control_enabled",false)
            .put("device",android.os.Build.MODEL).put("soc",android.os.Build.SOC_MODEL)
            .put("ort_version_expected","1.29.0").put("qnn_plugin","2.7.0").put("qnn_runtime","2.51.0")
            .put("cpu_fallback_disabled",true).put("scope","tiny symmetric quantized Conv probe only");
        var activity=instrumentation.startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        String previous=Os.getenv("ADSP_LIBRARY_PATH");boolean registered=false;OrtEnvironment environment=null;
        long start=android.os.SystemClock.elapsedRealtimeNanos();
        try {
            byte[] data,manifest;
            try(var input=context.getAssets().open("acceleration/qnn_probe.onnx")) {data=input.readAllBytes();}
            try(var input=context.getAssets().open("acceleration/qnn-probe.json")) {manifest=input.readAllBytes();}
            var metadata=new JSONObject(new String(manifest,java.nio.charset.StandardCharsets.UTF_8));
            assertEquals(metadata.getJSONObject("sha256").getString("qnn_probe.onnx"),sha(data));
            var model=new File(directory,"qnn_probe.onnx");Files.write(model.toPath(),data);
            report.put("model_sha256",sha(data)).put("runtime_manifest_sha256",sha(manifest));
            Os.setenv("ADSP_LIBRARY_PATH",context.getApplicationInfo().nativeLibraryDir,true);
            environment=OrtEnvironment.getEnvironment();report.put("ort_version",environment.getVersion());
            assertEquals("1.29.0",environment.getVersion());
            environment.registerExecutionProviderLibrary("QNNExecutionProvider","libonnxruntime_providers_qnn.so");registered=true;
            List<OrtEpDevice> devices=new ArrayList<>();JSONArray inventory=new JSONArray();
            for(var device:environment.getEpDevices()) {
                inventory.put(new JSONObject().put("provider",device.getEpName()).put("type",device.getDevice().getType().toString())
                    .put("vendor",device.getDevice().getVendor()).put("device_id",device.getDevice().getDeviceId()));
                if(device.getEpName().equals("QNNExecutionProvider"))devices.add(device);
            }
            report.put("devices",inventory);assertFalse("QNN did not enumerate a usable device",devices.isEmpty());
            try(var options=new OrtSession.SessionOptions()) {
                options.addExecutionProvider(devices,Map.of("backend_type","htp","htp_arch","68","soc_model","30"));
                options.addConfigEntry("session.disable_cpu_ep_fallback","1");
                options.setIntraOpNumThreads(1);options.setInterOpNumThreads(1);
                options.enableProfiling(new File(directory,"qnn-profile").getAbsolutePath());
                try(var session=environment.createSession(model.getAbsolutePath(),options)) {
                    JSONArray cases=new JSONArray();
                    for(int pattern=0;pattern<4;pattern++) {
                        byte[] input=new byte[25];
                        for(int i=0;i<25;i++)input[i]=(byte)(pattern<3 ? 127+pattern : 128+(((i/5)*3+(i%5)*2)%5)-2);
                        byte[] actual=run(environment,session,input);assertArrayEquals("QNN integer oracle",expected(input),actual);
                        cases.put(new JSONObject().put("pattern",pattern).put("output_sha256",sha(actual)));
                    }
                    JSONArray times=new JSONArray();byte[] input=new byte[25];Arrays.fill(input,(byte)129);
                    for(int i=0;i<100;i++) {
                        long before=android.os.SystemClock.elapsedRealtimeNanos();
                        assertArrayEquals(expected(input),run(environment,session,input));
                        times.put((android.os.SystemClock.elapsedRealtimeNanos()-before)/1e6);
                    }
                    String profile=session.endProfiling();
                    report.put("profile_file",profile).put("cases",cases).put("samples_ms",times);
                }
            }
            report.put("passed",true).put("htp_execution_verified",true);
        } catch(Throwable error) {
            report.put("error",android.util.Log.getStackTraceString(error));
        } finally {
            try {if(registered)environment.unregisterExecutionProviderLibrary("QNNExecutionProvider");}
            catch(Exception cleanup) {report.put("provider_cleanup_error",cleanup.toString());report.put("passed",false);}
            if(previous==null)Os.unsetenv("ADSP_LIBRARY_PATH");else Os.setenv("ADSP_LIBRARY_PATH",previous,true);
            report.put("elapsed_seconds",(android.os.SystemClock.elapsedRealtimeNanos()-start)/1e9);
            Files.write(new File(directory,"qnn.json").toPath(),report.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8));
            instrumentation.runOnMainSync(activity::finish);
        }
        assertTrue(report.toString(),report.getBoolean("passed"));
    }
}
