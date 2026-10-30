package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.UUID;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

/** Opt-in complete-tensor numerical probe; never changes production operators. */
@RunWith(AndroidJUnit4.class)
public class CabinArithmeticTest {
    private static String fileSha256(File path) throws Exception {
        var digest=MessageDigest.getInstance("SHA-256");
        try(var input=new FileInputStream(path)) {
            byte[] block=new byte[65536];
            for(int count;(count=input.read(block))!=-1;)digest.update(block,0,count);
        }
        StringBuilder text=new StringBuilder();
        for(byte value:digest.digest())text.append(String.format("%02x",value&255));
        return text.toString();
    }

    @Test(timeout=120000) public void fp32Conv809IdenticalInputs() throws Exception { followup("node_Conv_809"); }
    @Test(timeout=120000) public void fp32Conv811IdenticalInputs() throws Exception { followup("node_Conv_811"); }

    @Test(timeout=180000) public void fp32DepthwiseIdenticalInputs() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        assumeTrue("Explicit arithmetic probe only","true".equals(InstrumentationRegistry.getArguments().getString("cabinArithmetic","false")));
        String node=InstrumentationRegistry.getArguments().getString("cabinDepthwiseNode","node_Conv_819");
        assertTrue("Bounded short or complete selection",node.equals("node_Conv_819")||node.equals("remaining")||node.equals("all"));
        if(!node.equals("node_Conv_819"))assumeTrue("Explicit depthwise batch only","true".equals(
            InstrumentationRegistry.getArguments().getString("cabinDepthwiseBatch","false")));
        var context=instrumentation.getTargetContext();
        assertEquals("Pinned original runtime application","com.samsung.android.openpilot.shadow",context.getPackageName());
        var files=context.getFilesDir();
        assertTrue(new File(files,"cabin-f32-depthwise.onnx").isFile());
        assertTrue(new File(files,"cabin-f32-depthwise.json").isFile());
        String attempt=InstrumentationRegistry.getArguments().getString("attemptId",UUID.randomUUID().toString().replace("-",""));
        assertTrue(attempt.matches("[a-f0-9]{32}"));
        File destination=new File(files,"gpu-cabin-f32-depthwise.json");
        Files.write(destination.toPath(),new JSONObject().put("attempt_id",attempt).put("completed",false).toString().getBytes(StandardCharsets.UTF_8));
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        File session=new File(files,"s/depthwise-"+attempt.substring(0,16));session.mkdirs();
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","cabin_arithmetic_diagnostic");
        try {
            byte[] source;
            try(var input=instrumentation.getContext().getAssets().open("cabin_arithmetic_diagnostic.py")) {source=input.readAllBytes();}
            python.getModule("builtins").callAttr("exec",new String(source,StandardCharsets.UTF_8),module.get("__dict__"));
            var result=module.callAttr("inspect_f32_depthwise",new File(files,"model").toString(),
                context.getApplicationInfo().nativeLibraryDir,session.toString(),attempt,node);
            var report=new JSONObject(python.getModule("json").callAttr("dumps",result).toString());
            StringBuilder digest=new StringBuilder();
            for(byte value:MessageDigest.getInstance("SHA-256").digest(source))digest.append(String.format("%02x",value&255));
            report.put("test_asset_sha256",digest.toString()).put("target_apk_sha256",fileSha256(new File(context.getApplicationInfo().sourceDir)))
                .put("test_class",getClass().getName()).put("timing_qualified",false);
            Files.write(destination.toPath(),report.toString(2).getBytes(StandardCharsets.UTF_8));
            assertTrue("Every complete diagnostic variant finished",report.getBoolean("completed"));
            assertTrue("Original 553 CPU outputs unchanged",report.getBoolean("original_cpu_outputs_unchanged"));
            assertTrue("Complete imported X/W/B bytes unchanged",report.getBoolean("all_input_bytes_equal"));
            int expectedCalls=node.equals("all")?11:node.equals("remaining")?10:1;
            assertEquals(expectedCalls,report.getInt("selected_count"));
            assertEquals(node.equals("all")?619968:node.equals("remaining")?553728:66240,report.getInt("completed_output_values"));
            assertTrue(report.getInt("all_reference_bound_bytes")<=16*1024*1024);
            assertTrue("Exact measured production guards selected",report.getBoolean("all_production_guards_selected"));
            assertTrue("Every production direct output matches CPU bits",report.getBoolean("all_production_direct_bit_equal"));
            assertTrue("Every installed dispatch output matches CPU bits",report.getBoolean("all_production_dispatch_bit_equal"));
            assertTrue("Every dispatch called the measured helper",report.getBoolean("all_production_dispatch_called"));
            assertEquals(expectedCalls,report.getInt("production_dispatch_call_count"));
            assertFalse(report.getBoolean("qualified"));
        } finally {DriverReference.close();}
    }

    @Test(timeout=180000) public void fp32RemainingFamilyIdenticalInputs() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        assumeTrue("Explicit arithmetic batch only","true".equals(InstrumentationRegistry.getArguments().getString("cabinArithmetic","false"))
            && "true".equals(InstrumentationRegistry.getArguments().getString("cabinFamilyBatch","false")));
        var context=instrumentation.getTargetContext();
        assertEquals("Pinned original runtime application","com.samsung.android.openpilot.shadow",context.getPackageName());
        var files=context.getFilesDir();
        assertTrue(new File(files,"cabin-f32-batch.onnx").isFile());
        assertTrue(new File(files,"cabin-f32-batch.json").isFile());
        String attempt=InstrumentationRegistry.getArguments().getString("attemptId",UUID.randomUUID().toString().replace("-",""));
        assertTrue(attempt.matches("[a-f0-9]{32}"));
        File destination=new File(files,"gpu-cabin-f32-batch.json");
        Files.write(destination.toPath(),new JSONObject().put("attempt_id",attempt).put("completed",false).toString().getBytes(StandardCharsets.UTF_8));
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        File session=new File(files,"s/f32batch-"+attempt.substring(0,16));session.mkdirs();
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","cabin_arithmetic_diagnostic");
        try {
            byte[] source;
            try(var input=instrumentation.getContext().getAssets().open("cabin_arithmetic_diagnostic.py")) {source=input.readAllBytes();}
            python.getModule("builtins").callAttr("exec",new String(source,StandardCharsets.UTF_8),module.get("__dict__"));
            var result=module.callAttr("inspect_f32_batch",new File(files,"model").toString(),
                context.getApplicationInfo().nativeLibraryDir,session.toString(),attempt);
            var report=new JSONObject(python.getModule("json").callAttr("dumps",result).toString());
            StringBuilder digest=new StringBuilder();
            for(byte value:MessageDigest.getInstance("SHA-256").digest(source))digest.append(String.format("%02x",value&255));
            report.put("test_asset_sha256",digest.toString()).put("target_apk_sha256",fileSha256(new File(context.getApplicationInfo().sourceDir)))
                .put("test_class",getClass().getName()).put("timing_qualified",false);
            Files.write(destination.toPath(),report.toString(2).getBytes(StandardCharsets.UTF_8));
            assertTrue("All nine complete tensor probes finished",report.getBoolean("completed"));
            assertEquals(37,report.getInt("cpu_reference_names"));
            assertTrue(report.getInt("cpu_transport_bound_bytes")<=16*1024*1024);
            assertEquals(9,report.getJSONObject("results").length());
            assertEquals(450720,report.getInt("completed_output_values"));
            assertTrue("Original 553 CPU bits must be unchanged",report.getBoolean("original_cpu_outputs_unchanged"));
            assertTrue("Every proposed output must match CPU bits",report.getBoolean("all_candidate_outputs_bit_equal"));
            assertTrue(report.getBoolean("all_candidate_outputs_tolerance_passed"));
            assertTrue("Only measured guards selected",report.getBoolean("production_measured_contracts_enabled"));
            assertTrue("Every complete imported X/W/B byte matches CPU",report.getBoolean("all_input_bytes_equal"));
            assertTrue("Every final production direct output matches CPU bits",report.getBoolean("all_production_direct_bit_equal"));
            assertTrue("Every final installed dispatch output matches CPU bits",report.getBoolean("all_production_dispatch_bit_equal"));
            assertTrue("Every installed dispatch called the measured helper",report.getBoolean("all_production_dispatch_called"));
            assertEquals(9,report.getInt("production_dispatch_call_count"));
            assertFalse(report.getBoolean("qualified"));
        } finally {DriverReference.close();}
    }

    private void followup(String node) throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        assumeTrue("Explicit diagnostic only","true".equals(InstrumentationRegistry.getArguments().getString("cabinArithmetic","false")));
        var context=instrumentation.getTargetContext();
        assertEquals("Pinned original runtime application","com.samsung.android.openpilot.shadow",context.getPackageName());
        File files=context.getFilesDir();
        assertTrue(new File(files,"cabin-conv809-811.onnx").isFile());
        assertTrue(new File(files,"cabin-conv809-811.json").isFile());
        String attempt=InstrumentationRegistry.getArguments().getString("attemptId",UUID.randomUUID().toString().replace("-",""));
        assertTrue(attempt.matches("[a-f0-9]{32}"));
        File destination=new File(files,"gpu-cabin-f32-"+node+".json");
        Files.write(destination.toPath(),new JSONObject().put("attempt_id",attempt).put("completed",false).toString().getBytes(StandardCharsets.UTF_8));
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        File session=new File(files,"s/"+node+"-"+attempt.substring(0,16));session.mkdirs();
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","cabin_arithmetic_diagnostic");
        try {
            byte[] source;
            try(var input=instrumentation.getContext().getAssets().open("cabin_arithmetic_diagnostic.py")) {source=input.readAllBytes();}
            python.getModule("builtins").callAttr("exec",new String(source,StandardCharsets.UTF_8),module.get("__dict__"));
            var result=module.callAttr("inspect_f32_followup",new File(files,"model").toString(),
                context.getApplicationInfo().nativeLibraryDir,session.toString(),attempt,node);
            var report=new JSONObject(python.getModule("json").callAttr("dumps",result).toString());
            StringBuilder digest=new StringBuilder();
            for(byte value:MessageDigest.getInstance("SHA-256").digest(source))digest.append(String.format("%02x",value&255));
            report.put("test_asset_sha256",digest.toString()).put("target_apk_sha256",fileSha256(new File(context.getApplicationInfo().sourceDir)))
                .put("test_class",getClass().getName()).put("timing_qualified",false);
            Files.write(destination.toPath(),report.toString(2).getBytes(StandardCharsets.UTF_8));
            assertTrue(report.getBoolean("completed"));
            assertTrue(report.getBoolean("original_cpu_outputs_unchanged"));
            assertTrue("Production helper is required",report.getBoolean("production_available"));
            assertTrue("Actual attributes must select the measured helper",report.getBoolean("production_guard"));
            assertTrue("Installed operator called the production helper",report.getBoolean("production_dispatch_called"));
            assertTrue(report.getJSONObject("results").getJSONObject("production_direct").getBoolean("bit_equal"));
            assertTrue(report.getJSONObject("results").getJSONObject("production_dispatch").getBoolean("bit_equal"));
            assertFalse(report.getBoolean("qualified"));
        } finally {DriverReference.close();}
    }

    @Test(timeout=300000) public void fp32Conv807IdenticalInputs() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        assumeTrue("Explicit diagnostic only", "true".equals(
            InstrumentationRegistry.getArguments().getString("cabinArithmetic","false")));
        var context=instrumentation.getTargetContext();
        assertEquals("Pinned original runtime application", "com.samsung.android.openpilot.shadow",context.getPackageName());
        var files=context.getFilesDir();
        boolean window="true".equals(InstrumentationRegistry.getArguments().getString("cabinWindow","false"));
        String graph=window?"cabin-arithmetic-nodes":"cabin-arithmetic-short";
        assertTrue("Prepared arithmetic graph is required",new File(files,graph+".onnx").isFile());
        assertTrue("Prepared arithmetic metadata is required",new File(files,graph+".json").isFile());
        String attempt=InstrumentationRegistry.getArguments().getString("attemptId",UUID.randomUUID().toString().replace("-",""));
        assertTrue("Diagnostic attempt identity",attempt.matches("[a-f0-9]{32}"));
        File destination=new File(files,"gpu-cabin-fp32-conv807.json");
        Files.write(destination.toPath(),new JSONObject().put("attempt_id",attempt).put("completed",false)
            .toString().getBytes(StandardCharsets.UTF_8));
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        File session=new File(files,"s/conv807-"+attempt.substring(0,16));session.mkdirs();
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","cabin_arithmetic_diagnostic");
        try {
            byte[] source;
            try(var input=instrumentation.getContext().getAssets().open("cabin_arithmetic_diagnostic.py")) {
                source=input.readAllBytes();
            }
            python.getModule("builtins").callAttr("exec",new String(source,StandardCharsets.UTF_8),module.get("__dict__"));
            var result=module.callAttr("inspect_fp32_conv",new File(files,"model").toString(),
                context.getApplicationInfo().nativeLibraryDir,session.toString(),attempt,window);
            var report=new JSONObject(python.getModule("json").callAttr("dumps",result).toString());
            StringBuilder digest=new StringBuilder();
            for(byte value:MessageDigest.getInstance("SHA-256").digest(source))digest.append(String.format("%02x",value&255));
            report.put("test_asset_sha256",digest.toString()).put("test_class",getClass().getName())
                .put("target_apk_sha256",fileSha256(new File(context.getApplicationInfo().sourceDir))).put("timing_qualified",false);
            Files.write(destination.toPath(),report.toString(2).getBytes(StandardCharsets.UTF_8));
            assertTrue("All arithmetic variants completed",report.getBoolean("completed"));
            assertTrue("Diagnostic must preserve all original 553 CPU output bits",report.getBoolean("original_cpu_outputs_unchanged"));
            if(window)assertTrue("Full forward diagnostic completed",report.getJSONObject("full_graph").getBoolean("completed"));
            // A completed diagnostic is not operator or whole-model qualification.
            assertFalse(report.getBoolean("qualified"));
        } finally {
            DriverReference.close();
        }
    }
}
