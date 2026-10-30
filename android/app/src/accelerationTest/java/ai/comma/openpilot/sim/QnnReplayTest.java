package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;
import android.os.SystemClock;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Explicit experimental replay. Hardware proof does not imply original-model accuracy. */
@RunWith(AndroidJUnit4.class)
public class QnnReplayTest {
    @Test(timeout=1920000) public void measuredQuantizedModelRunsThroughRecordedDaemons() throws Exception {
        var context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assumeTrue("Isolated QNN application only",context.getPackageName().equals("ai.comma.openpilot.qnn"));
        File app=context.getFilesDir();
        String session=UUID.randomUUID().toString().replace("-","").substring(0,16);
        File root=new File(app,"s/"+session);assertTrue(root.isDirectory() || root.mkdirs());
        File request=new File(app,"qnn-replay-request.json");
        RuntimeTest.BoundWorker bound=null;
        boolean requestWritten=false;
        JSONObject result=new JSONObject().put("schema",1).put("experimental",true).put("session",session)
            .put("backend","qnn_quantized").put("hardware_execution",false).put("accuracy_comparison_passed",false)
            .put("physical_vehicle_control_enabled",false).put("scope","Recorded simulation; hardware execution and accuracy are separate");
        try {
            File manifestFile=new File(app,"model/qnn-graph-manifest.json");
            JSONObject manifest=read(manifestFile);
            assertTrue("Stage the separately measured-calibrated graph first",manifest.getBoolean("quantized_model_calibrated"));
            JSONObject model=manifest.getJSONObject("models").getJSONObject("quantized");
            String filename=model.getString("file");assertEquals(filename,new File(filename).getName());
            String executed=manifest.getJSONObject("sha256").getString(filename);
            assertEquals("Staged quantized graph integrity",executed,sha256(new File(app,"model/"+filename)));
            JSONObject gate=read(new File(app,"acceleration/qnn-quantized-execution.json"));
            assertTrue("Run the 60-frame QNN teacher/free diagnostic first",gate.getBoolean("hardware_execution"));
            assertEquals("Hardware gate model",executed,gate.getString("model_sha256"));
            result.put("executed_model_sha256",executed).put("source_model_sha256",manifest.getJSONObject("source").getString("sha256"));
            JSONObject selection=new JSONObject().put("session",session).put("backend","qnn_quantized")
                .put("executed_model_sha256",executed).put("measured_calibrated",true)
                .put("created_elapsed_ms",SystemClock.elapsedRealtime());
            Files.write(request.toPath(),selection.toString().getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
            requestWritten=true;
            Files.write(new File(app,"last-replay-session.txt").toPath(),session.getBytes(StandardCharsets.UTF_8));
            Files.write(new File(app,"last-qnn-replay-session.txt").toPath(),session.getBytes(StandardCharsets.UTF_8));
            bound=new RuntimeTest.BoundWorker(WorkerService.Replay.class);
            IWorker worker=bound.get();worker.start(session,"replay");
            long deadline=SystemClock.elapsedRealtime()+1800000;
            JSONObject state;
            do {
                Thread.sleep(500);state=new JSONObject(worker.status());
                if(state.getString("state").equals("finished") || state.getString("state").equals("failed") || state.getString("state").equals("stopped"))break;
            } while(SystemClock.elapsedRealtime()<deadline);
            result.put("worker_terminal",state);
            assertTrue("30-minute replay deadline exceeded",state.getString("state").equals("finished") || state.getString("state").equals("failed"));
            JSONObject verification=read(new File(root,"verification.json"));
            JSONObject backend=read(new File(root,"qnn-backend.json"));
            result.put("backend_report",backend).put("counts",verification.getJSONObject("counts"));
            JSONObject actual=new JSONObject().put("backend","qnn_quantized").put("experimental",true)
                .put("executed_model_file",filename).put("executed_model_sha256",executed)
                .put("source_model_sha256",manifest.getJSONObject("source").getString("sha256"))
                .put("measured_calibrated",true).put("graph_manifest_sha256",sha256(manifestFile))
                .put("backend_report_sha256",sha256(new File(root,"qnn-backend.json")));
            // comparison.json remains untouched: its model hash identifies the reference.
            verification.put("executed_model",actual).put("executed_model_sha256",executed)
                .put("model_sha256",executed).put("executed_backend","qnn_quantized").put("experimental",true)
                .put("comparison_reference_model_sha256",manifest.getJSONObject("source").getString("sha256"));
            write(new File(root,"verification.json"),verification);
            result.put("executed_model",actual);
            JSONObject counts=verification.getJSONObject("counts");
            assertEquals("60 recorded model messages",60,counts.optInt("modelV2"));
            assertEquals("60 recorded plans",60,counts.optInt("longitudinalPlan"));
            assertEquals("60 recorded frame pairs",60,verification.getInt("frames"));
            assertTrue("Computed controls required",counts.optInt("carControl")>0);
            assertTrue("Simulated sendcan required",counts.optInt("sendcan")>0);
            assertEquals(executed,backend.getString("executed_model_sha256"));
            assertTrue(backend.getBoolean("experimental"));assertTrue(backend.getBoolean("cpu_fallback_disabled"));
            assertTrue(backend.getBoolean("hardware_execution"));assertTrue(backend.getBoolean("finite_outputs"));
            assertTrue(backend.getBoolean("state_aliases_preserved"));assertTrue(backend.getBoolean("native_resources_closed"));
            assertEquals(60,backend.getInt("frames"));
            verifyProfile(root,backend.getJSONObject("profile"));
            result.put("hardware_execution",true).put("api_execution_checks_passed",true);
            File comparisonFile=new File(root,"comparison.json");
            JSONObject comparison=read(comparisonFile);
            result.put("accuracy_comparison_passed",comparison.getBoolean("passed"))
                .put("accuracy_comparison",comparison).put("comparison_file_sha256",sha256(comparisonFile));
            // Deliberately no assertion that quantization matches original precision.
        } catch(Throwable failure) {
            result.put("error",failure.toString());throw failure;
        } finally {
            try {if(bound!=null)bound.close();} finally {
                try {
                    if(requestWritten && request.isFile() && read(request).optString("session").equals(session))Files.deleteIfExists(request.toPath());
                    Files.deleteIfExists(new File(root,"qnn-replay-request.json").toPath());
                } finally {write(new File(root,"qnn-replay.json"),result);}
            }
            SimulationTestSupport.assertWorkersStopped();
        }
    }

    private static void verifyProfile(File root,JSONObject profile) throws Exception {
        File path=new File(profile.getString("path"));
        assertTrue("Private session trace",path.getCanonicalPath().startsWith(root.getCanonicalPath()+File.separator));
        assertEquals("Provider trace integrity",profile.getString("sha256"),sha256(path));
        JSONArray events=new JSONArray(new String(Files.readAllBytes(path.toPath()),StandardCharsets.UTF_8));
        int attributed=0;
        for(int i=0;i<events.length();i++) {
            JSONObject args=events.getJSONObject(i).optJSONObject("args");
            String provider=args==null ? "" : args.optString("provider");
            if(!provider.isEmpty()) {assertEquals("No CPU provider fallback", "QNNExecutionProvider",provider);attributed++;}
        }
        assertTrue("All 60 calls need provider attribution",attributed>=60);
    }
    private static JSONObject read(File file) throws Exception {
        return new JSONObject(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));
    }
    private static void write(File file,JSONObject value) throws Exception {
        File temporary=new File(file.getParentFile(),file.getName()+".qnn.tmp");
        Files.write(temporary.toPath(),value.toString(2).getBytes(StandardCharsets.UTF_8));
        try {Files.move(temporary.toPath(),file.toPath(),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);}
        catch(AtomicMoveNotSupportedException unsupported) {Files.move(temporary.toPath(),file.toPath(),StandardCopyOption.REPLACE_EXISTING);}
    }
    private static String sha256(File file) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(var input=Files.newInputStream(file.toPath())) {byte[] data=new byte[65536];for(int n;(n=input.read(data))!=-1;)digest.update(data,0,n);}
        StringBuilder result=new StringBuilder();for(byte b:digest.digest())result.append(String.format("%02x",b&255));return result.toString();
    }
}
