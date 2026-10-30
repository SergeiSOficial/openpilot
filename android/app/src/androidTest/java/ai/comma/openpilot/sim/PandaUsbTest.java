package ai.comma.openpilot.sim;

import static org.junit.Assert.*;
import static ai.comma.openpilot.sim.SimulationTestSupport.*;
import android.app.Activity;
import android.content.Intent;
import android.hardware.usb.UsbManager;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.File;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.util.Arrays;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class PandaUsbTest {
    private static final class FakeInput implements PandaMonitor.Input {
        final PandaProtocol protocol;
        byte[] health, versions, can=new byte[0];
        byte hardware=7;
        boolean closed;
        int reads;
        FakeInput(PandaProtocol protocol) throws Exception {
            this.protocol=protocol; health=new byte[protocol.healthSize];
            versions=ByteBuffer.allocate(8).order(ByteOrder.LITTLE_ENDIAN)
                .putInt((int)protocol.metadata.getLong("health_version")).putInt((int)protocol.metadata.getLong("can_version")).array();
            field("safety_mode_pkt",19);
        }
        void field(String name,int value) throws Exception {
            JSONArray fields=protocol.metadata.getJSONArray("health_fields");
            for(int i=0;i<fields.length();i++) {
                JSONObject item=fields.getJSONObject(i);
                if(item.getString("name").equals(name)) for(int j=0;j<item.getInt("bytes");j++) health[item.getInt("offset")+j]=(byte)(value>>>(j*8));
            }
        }
        @Override public byte[] controlIn(int request,int length) {
            if(closed) throw new IllegalStateException("Closed");
            return switch(request) { case 0xc1 -> new byte[]{hardware}; case 0xdd -> versions; case 0xd2 -> health;
                default -> throw new AssertionError("Unexpected USB request"); };
        }
        @Override public byte[] canRead() { reads++; byte[] value=can; can=new byte[0]; return value; }
        @Override public void close() { closed=true; }
    }
    @Test public void goldenCanPacketsAndSplitTransfersMatchPinnedPanda() throws Exception {
        PandaProtocol protocol=new PandaProtocol(context);
        JSONArray vectors=protocol.metadata.getJSONArray("golden_vectors");
        for(int i=0;i<vectors.length();i++) {
            JSONObject vector=vectors.getJSONObject(i); byte[] wire=PandaProtocol.unhex(vector.getString("wire"));
            assertArrayEquals(wire,protocol.encode(vector.getLong("address"),PandaProtocol.unhex(vector.getString("data")),vector.getInt("bus"),vector.getBoolean("fd")));
            PandaProtocol.CanStream stream=protocol.new CanStream();
            assertEquals(0,stream.accept(Arrays.copyOf(wire,5)).length());
            JSONObject frame=stream.accept(Arrays.copyOfRange(wire,5,wire.length)).getJSONObject(0);
            assertEquals(vector.getLong("address"),frame.getLong("address"));
            assertEquals(vector.getString("data"),frame.getString("data"));
            assertEquals(vector.getInt("bus"),frame.getInt("bus"));
            wire[1]|=1; wire[5]^=1;
            assertTrue(protocol.new CanStream().accept(wire).getJSONObject(0).getBoolean("rejected"));
            wire[5]^=1;
            try { protocol.new CanStream().accept(wire); fail("Corrupted CAN packet accepted"); }
            catch(IllegalStateException expected) { assertTrue(expected.getMessage().contains("checksum")); }
        }
    }
    @Test public void hardwareProtocolHealthAndSafetyFailuresCloseWithoutReadingCan() throws Exception {
        PandaProtocol protocol=new PandaProtocol(context);
        for(int scenario=0;scenario<5;scenario++) {
            FakeInput input=new FakeInput(protocol);
            switch(scenario) {
                case 0 -> input.hardware=9;
                case 1 -> input.versions[0]^=1;
                case 2 -> input.versions=new byte[3];
                case 3 -> input.health=new byte[protocol.healthSize-1];
                case 4 -> input.field("safety_mode_pkt",8);
            }
            try { new PandaMonitor(protocol,input).open(); fail("Invalid Panda was accepted"); }
            catch(IllegalStateException expected) { assertTrue(input.closed); assertEquals(0,input.reads); }
        }
        FakeInput input=new FakeInput(protocol);
        try(PandaMonitor monitor=new PandaMonitor(protocol,input)) {
            assertFalse(monitor.open().getBoolean("actuation_allowed"));
            input.field("flags_pkt",4);
            try { monitor.poll(); fail("Controls-allowed state was accepted"); }
            catch(IllegalStateException expected) { assertTrue(input.closed); assertEquals(0,input.reads); }
        }
        FakeInput badCan=new FakeInput(protocol);
        try(PandaMonitor monitor=new PandaMonitor(protocol,badCan)) {
            monitor.open(); badCan.can=protocol.encode(0x123,new byte[]{1,2,3},0,false); badCan.can[5]^=1;
            try { monitor.poll(); fail("Bad CAN checksum was accepted"); }
            catch(IllegalStateException expected) { assertTrue(badCan.closed); }
        }
    }
    @Test public void noAttachedPandaIsReportedWithoutRequestingPermissionOrEnablingControl() throws Exception {
        UsbManager usb=(UsbManager)context.getSystemService(android.content.Context.USB_SERVICE);
        boolean attached=usb.getDeviceList().values().stream().anyMatch(PandaUsbConnection::matches);
        org.junit.Assume.assumeFalse("This absent-device case requires no physical Panda",attached);
        Activity activity=InstrumentationRegistry.getInstrumentation().startActivitySync(new Intent(context,PandaActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK|Intent.FLAG_ACTIVITY_CLEAR_TASK));
        try {
            awaitText(activity,"USB host supported:"); press(activity,"Connect / monitor");
            awaitText(activity,"No red panda attached"); awaitText(activity,"Vehicle control is not enabled");
            File root=new File(context.getFilesDir(),"panda"); screenshot(root,"usb-readiness.png");
            JSONObject evidence=new JSONObject().put("android_model",android.os.Build.MODEL)
                .put("usb_host_supported",context.getPackageManager().hasSystemFeature("android.hardware.usb.host"))
                .put("panda_attached",false).put("physical_usb_transfers_tested",false).put("vehicle_control_verified",false)
                .put("software_protocol_tests_only",true);
            Files.write(new File(root,"usb-test-evidence.json").toPath(),evidence.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        } finally { finish(activity); assertWorkersStopped(); }
    }
}
