package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.nio.file.Files;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class CpuQualificationTest {
    @Test public void corruptNativeQualificationIsRejected() throws Exception {
        var context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        File models=ModelAssets.extract(context),certificate=new File(models,"cpu-qualification.json");
        assertTrue("Qualified CPU build required",certificate.isFile());
        byte[] original=Files.readAllBytes(certificate.toPath());
        if(!Python.isStarted())Python.start(new AndroidPlatform(context));
        var python=Python.getInstance();
        var session=new File(context.getFilesDir(),"s/00000000000000ac");session.mkdirs();
        python.getModule("android_runtime.worker").callAttr("configure",session.getAbsolutePath());
        try {
            JSONObject changed=new JSONObject(new String(original));
            for(var names=changed.getJSONObject("libraries_sha256").keys();names.hasNext();)
                changed.getJSONObject("libraries_sha256").put(names.next(),"0".repeat(64));
            Files.write(certificate.toPath(),changed.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            try {
                python.getModule("android_runtime.cpu_backend").callAttr("select",context.getApplicationInfo().nativeLibraryDir+"/libopenpilot_kernels.so");
                fail("Corrupt qualification selected a native library");
            } catch(com.chaquo.python.PyException expected) {assertTrue(expected.toString(),expected.toString().contains("hash differs"));}
        } finally {Files.write(certificate.toPath(),original);}
    }
}
