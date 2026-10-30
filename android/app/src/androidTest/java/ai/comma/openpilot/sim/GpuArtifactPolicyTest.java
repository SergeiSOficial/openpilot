package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.nio.charset.StandardCharsets;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class GpuArtifactPolicyTest {
    @Test public void cabinTanhContractionDiagnostic() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        var context=instrumentation.getTargetContext();
        org.junit.Assume.assumeTrue("Explicit cabin intermediate graph is required",
            new java.io.File(context.getFilesDir(),"cabin-cpu-nodes.onnx").isFile());
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        var session=new java.io.File(context.getFilesDir(),"s/gputanhprobe001");session.mkdirs();
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","gpu_address_diagnostic");
        try(var input=instrumentation.getContext().getAssets().open("gpu_address_diagnostic.py")) {
            python.getModule("builtins").callAttr("exec",new String(input.readAllBytes(),StandardCharsets.UTF_8),module.get("__dict__"));
        }
        var result=module.callAttr("inspect_cabin_tanh",new java.io.File(context.getFilesDir(),"model").toString(),
                                   context.getApplicationInfo().nativeLibraryDir,session.toString());
        var json=python.getModule("json").callAttr("dumps",result).toString();
        java.nio.file.Files.write(new java.io.File(context.getFilesDir(),"gpu-cabin-tanh.json").toPath(),json.getBytes(StandardCharsets.UTF_8));
        assertTrue(new org.json.JSONObject(json).getBoolean("passed"));
    }

    @Test public void retainedFixtureDiagnostic() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        var context=instrumentation.getTargetContext();
        org.junit.Assume.assumeTrue("Explicit recorded fixture capture is required for this diagnostic",
            new java.io.File(context.getFilesDir(),"gpu-frame-inputs.npz").isFile() &&
            new java.io.File(context.getFilesDir(),"gpu-frame-inputs.json").isFile());
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        var session=new java.io.File(context.getFilesDir(),"s/gpufixture001");session.mkdirs();
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","gpu_address_diagnostic");
        try(var input=instrumentation.getContext().getAssets().open("gpu_address_diagnostic.py")) {
            python.getModule("builtins").callAttr("exec",new String(input.readAllBytes(),StandardCharsets.UTF_8),module.get("__dict__"));
        }
        var result=module.callAttr("inspect_fixture_frame",new java.io.File(context.getFilesDir(),"model").toString(),
                                   context.getApplicationInfo().nativeLibraryDir,session.toString());
        var json=python.getModule("json").callAttr("dumps",result).toString();
        java.nio.file.Files.write(new java.io.File(context.getFilesDir(),"gpu-fixture-frame.json").toPath(),json.getBytes(StandardCharsets.UTF_8));
        assertTrue(new org.json.JSONObject(json).has("matched"));
    }

    @Test public void retainedKernelTimingDiagnostic() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        var context=instrumentation.getTargetContext();
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        var session=new java.io.File(context.getFilesDir(),"s/gpuprofile001");session.mkdirs();
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","gpu_address_diagnostic");
        try(var input=instrumentation.getContext().getAssets().open("gpu_address_diagnostic.py")) {
            python.getModule("builtins").callAttr("exec",new String(input.readAllBytes(),StandardCharsets.UTF_8),module.get("__dict__"));
        }
        var result=module.callAttr("profile_retained",new java.io.File(context.getFilesDir(),"model").toString(),
                                   context.getApplicationInfo().nativeLibraryDir,session.toString());
        var json=python.getModule("json").callAttr("dumps",result).toString();
        java.nio.file.Files.write(new java.io.File(context.getFilesDir(),"gpu-kernel-timing.json").toPath(),json.getBytes(StandardCharsets.UTF_8));
        assertTrue(new org.json.JSONObject(json).getBoolean("passed"));
    }

    @Test public void recurrentCopyDiagnostic() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        var context=instrumentation.getTargetContext();
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        var session=new java.io.File(context.getFilesDir(),"s/gpucopyprobe001");session.mkdirs();
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","gpu_address_diagnostic");
        try(var input=instrumentation.getContext().getAssets().open("gpu_address_diagnostic.py")) {
            python.getModule("builtins").callAttr("exec",new String(input.readAllBytes(),StandardCharsets.UTF_8),module.get("__dict__"));
        }
        var result=module.callAttr("inspect_recurrent_copy",new java.io.File(context.getFilesDir(),"model").toString(),
                                   context.getApplicationInfo().nativeLibraryDir,session.toString());
        var json=python.getModule("json").callAttr("dumps",result).toString();
        java.nio.file.Files.write(new java.io.File(context.getFilesDir(),"gpu-recurrent-copy.json").toPath(),json.getBytes(StandardCharsets.UTF_8));
        // Completion of this diagnostic is not numerical qualification.
        assertTrue(new org.json.JSONObject(json).has("matched"));
    }

    @Test public void recurrentAliasOwnership() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        var context=instrumentation.getTargetContext();
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        var session=new java.io.File(context.getFilesDir(),"s/gpualiases001");session.mkdirs();
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","gpu_address_diagnostic");
        try(var input=instrumentation.getContext().getAssets().open("gpu_address_diagnostic.py")) {
            python.getModule("builtins").callAttr("exec",new String(input.readAllBytes(),StandardCharsets.UTF_8),module.get("__dict__"));
        }
        var result=module.callAttr("check_state_alias",new java.io.File(context.getFilesDir(),"model").toString(),
                                   context.getApplicationInfo().nativeLibraryDir,session.toString());
        assertTrue(result.asMap().get(com.chaquo.python.PyObject.fromJava("passed")).toBoolean());
    }

    @Test public void retainedModelProofDiagnostic() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        var context=instrumentation.getTargetContext();
        ModelAssets.extract(context);ModelAssets.extractLive(context);
        var session=new java.io.File(context.getFilesDir(),"s/gpuaddresses001");session.mkdirs();
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","gpu_address_diagnostic");
        try(var input=instrumentation.getContext().getAssets().open("gpu_address_diagnostic.py")) {
            python.getModule("builtins").callAttr("exec",new String(input.readAllBytes(),StandardCharsets.UTF_8),module.get("__dict__"));
        }
        var result=module.callAttr("inspect_model",new java.io.File(context.getFilesDir(),"model").toString(),
                                   context.getApplicationInfo().nativeLibraryDir,session.toString());
        var json=python.getModule("json").callAttr("dumps",result).toString();
        java.nio.file.Files.write(new java.io.File(context.getFilesDir(),"gpu-kernel-proof.json").toPath(),json.getBytes(StandardCharsets.UTF_8));
        assertTrue(new org.json.JSONObject(json).getBoolean("passed"));
    }

    @Test public void realUopViewsAndIndependentLoops() throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        if(!Python.isStarted())Python.start(new AndroidPlatform(instrumentation.getTargetContext()));
        var python=Python.getInstance();
        var module=python.getModule("types").callAttr("ModuleType","gpu_address_diagnostic");
        try(var input=instrumentation.getContext().getAssets().open("gpu_address_diagnostic.py")) {
            python.getModule("builtins").callAttr("exec",new String(input.readAllBytes(),StandardCharsets.UTF_8),module.get("__dict__"));
        }
        assertTrue(module.callAttr("check").asMap().get(com.chaquo.python.PyObject.fromJava("passed")).toBoolean());
    }
}
