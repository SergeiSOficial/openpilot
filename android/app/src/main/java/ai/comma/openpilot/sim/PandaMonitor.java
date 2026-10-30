package ai.comma.openpilot.sim;

import org.json.JSONArray;
import org.json.JSONObject;

/** Preflight/RX monitor, isolated from replay, sendcan and vehicle engagement. */
final class PandaMonitor implements AutoCloseable {
    interface Input extends AutoCloseable {
        byte[] controlIn(int request,int length) throws Exception;
        byte[] canRead() throws Exception;
        @Override void close();
    }
    private final PandaProtocol protocol;
    private final Input input;
    private final PandaProtocol.CanStream stream;
    private long frames;
    private final long[] buses=new long[3];
    private volatile boolean opened;
    PandaMonitor(PandaProtocol protocol,Input input) { this.protocol=protocol; this.input=input; stream=protocol.new CanStream(); }
    JSONObject open() throws Exception {
        try {
            byte[] type=input.controlIn(0xc1,1);
            if(type.length!=1 || type[0]!=7) throw new IllegalStateException("Selected USB device is not a Red Panda");
            protocol.versions(input.controlIn(0xdd,8));
            JSONObject health=protocol.health(input.controlIn(0xd2,protocol.healthSize));
            protocol.requirePassive(health); opened=true;
            return status(health);
        } catch(Exception failure) { close(); throw failure; }
    }
    JSONObject poll() throws Exception {
        if(!opened) throw new IllegalStateException("Panda monitor is closed");
        try {
            JSONObject health=protocol.health(input.controlIn(0xd2,protocol.healthSize)); protocol.requirePassive(health);
            JSONArray received=stream.accept(input.canRead());
            for(int i=0;i<received.length();i++) { frames++; buses[received.getJSONObject(i).getInt("bus")]++; }
            JSONObject result=status(health);
            if(received.length()>0) result.put("last_frame",received.getJSONObject(received.length()-1));
            return result;
        } catch(Exception failure) { close(); throw failure; }
    }
    private JSONObject status(JSONObject health) throws Exception {
        return new JSONObject().put("state","monitoring").put("hardware_type",7).put("protocol_match",true)
            .put("health",health).put("can_frames",frames).put("bus_counts",new JSONArray(buses))
            .put("vehicle_target","Hyundai Ioniq PHEV 2018").put("vehicle_identified",false)
            .put("actuation_allowed",false).put("physical_can_tx_tested",false).put("firmware_signature_verified",false);
    }
    @Override public void close() { opened=false; input.close(); }
}
