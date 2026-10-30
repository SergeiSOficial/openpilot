package ai.comma.openpilot.sim;

import android.content.Context;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.json.JSONArray;
import org.json.JSONObject;

/** Pinned Panda wire format. This parser never configures safety or transmits CAN. */
final class PandaProtocol {
    final JSONObject metadata;
    final int healthSize;
    private final int[] lengths = {0,1,2,3,4,5,6,7,8,12,16,20,24,32,48,64};
    PandaProtocol(Context context) throws Exception {
        try (var in = context.getAssets().open("panda/protocol.json")) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer = new byte[4096];
            for (int n; (n = in.read(buffer)) != -1;) bytes.write(buffer,0,n);
            metadata = new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
        }
        healthSize = metadata.getInt("health_size");
    }
    void versions(byte[] raw) throws Exception {
        if (raw.length != 8) throw new IllegalStateException("Unsupported Panda protocol version response; firmware maintenance required");
        ByteBuffer data = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN);
        long health = Integer.toUnsignedLong(data.getInt()), can = Integer.toUnsignedLong(data.getInt());
        if (health != metadata.getLong("health_version") || can != metadata.getLong("can_version"))
            throw new IllegalStateException("Panda firmware protocol differs from this checkout; no automatic flashing");
    }
    JSONObject health(byte[] raw) throws Exception {
        if (raw.length != healthSize) throw new IllegalStateException("Truncated Panda health packet");
        JSONObject out = new JSONObject();
        ByteBuffer data = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN);
        JSONArray fields = metadata.getJSONArray("health_fields");
        for (int i=0;i<fields.length();i++) {
            JSONObject field = fields.getJSONObject(i); int offset = field.getInt("offset");
            long value = switch(field.getInt("bytes")) {
                case 1 -> Byte.toUnsignedLong(raw[offset]);
                case 2 -> Short.toUnsignedLong(data.getShort(offset));
                case 4 -> Integer.toUnsignedLong(data.getInt(offset));
                default -> throw new IllegalStateException("Unsupported health field width");
            };
            out.put(field.getString("name"), value);
        }
        long flags = out.getLong("flags_pkt");
        out.put("controls_allowed", (flags & 4) != 0).put("heartbeat_lost", (flags & 16) != 0)
            .put("safety_rx_checks_invalid", (flags & 32) != 0);
        return out;
    }
    void requirePassive(JSONObject health) throws Exception {
        long mode = health.getLong("safety_mode_pkt");
        if (health.getBoolean("controls_allowed") || (mode != 0 && mode != 19))
            throw new IllegalStateException("Panda has an active safety session; CAN monitoring stopped");
    }
    byte[] encode(long address, byte[] data, int bus, boolean fd) {
        int dlc = -1; for(int i=0;i<lengths.length;i++) if(lengths[i]==data.length) dlc=i;
        if (address<0 || address>0x1fffffffL || bus<0 || bus>2 || dlc<0 || (!fd && data.length>8))
            throw new IllegalArgumentException("Invalid CAN address, bus or payload");
        byte[] wire = new byte[6+data.length];
        wire[0]=(byte)((dlc<<4)|(bus<<1)|(fd?1:0));
        long word=(address<<3)|(address>=0x800?4:0);
        for(int i=0;i<4;i++) wire[i+1]=(byte)(word>>>(i*8));
        System.arraycopy(data,0,wire,6,data.length);
        byte checksum=0; for(byte value:wire) checksum^=value; wire[5]=checksum;
        return wire;
    }
    final class CanStream {
        private byte[] pending = new byte[0];
        JSONArray accept(byte[] chunk) throws Exception {
            if (chunk.length>16384) throw new IllegalStateException("Oversized USB CAN transfer");
            byte[] bytes=Arrays.copyOf(pending,pending.length+chunk.length);
            System.arraycopy(chunk,0,bytes,pending.length,chunk.length);
            JSONArray frames=new JSONArray(); int offset=0;
            while(bytes.length-offset>=6) {
                int size=6+lengths[(bytes[offset]&255)>>>4];
                if(bytes.length-offset<size) break;
                byte checksum=0; for(int i=0;i<size;i++) checksum^=bytes[offset+i];
                if(checksum!=0) { pending=new byte[0]; throw new IllegalStateException("CAN packet checksum mismatch"); }
                int bus=(bytes[offset]>>>1)&7;
                if(bus>2) throw new IllegalStateException("Invalid Red Panda bus index");
                long word=Integer.toUnsignedLong(ByteBuffer.wrap(bytes,offset+1,4).order(ByteOrder.LITTLE_ENDIAN).getInt());
                frames.put(new JSONObject().put("address",word>>>3).put("bus",bus).put("returned",(word&2)!=0)
                    .put("rejected",(word&1)!=0).put("fd",(bytes[offset]&1)!=0)
                    .put("data",hex(Arrays.copyOfRange(bytes,offset+6,offset+size))));
                offset+=size;
            }
            pending=Arrays.copyOfRange(bytes,offset,bytes.length);
            return frames;
        }
    }
    static String hex(byte[] bytes) { StringBuilder text=new StringBuilder(); for(byte b:bytes) text.append(String.format(java.util.Locale.ROOT,"%02x",b&255)); return text.toString(); }
    static byte[] unhex(String text) { byte[] data=new byte[text.length()/2]; for(int i=0;i<data.length;i++) data[i]=(byte)Integer.parseInt(text.substring(i*2,i*2+2),16); return data; }
}
