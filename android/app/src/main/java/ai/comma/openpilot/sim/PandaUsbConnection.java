package ai.comma.openpilot.sim;

import android.hardware.usb.*;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.util.Arrays;
import java.util.concurrent.TimeoutException;

/** Unrooted Android USB host access. Only IN transfers are exposed to this APK. */
final class PandaUsbConnection implements PandaMonitor.Input {
    private UsbDeviceConnection connection;
    private final UsbInterface face;
    private final UsbEndpoint input;
    static boolean matches(UsbDevice device) {
        return (device.getVendorId()==0x3801 || device.getVendorId()==0xbbaa) && device.getProductId()==0xddcc;
    }
    PandaUsbConnection(UsbManager manager, UsbDevice device) throws Exception {
        if(!matches(device) || !manager.hasPermission(device)) throw new SecurityException("Red Panda USB permission is required");
        UsbInterface selected=null; UsbEndpoint rx=null; boolean output=false;
        for(int i=0;i<device.getInterfaceCount();i++) {
            UsbInterface candidate=device.getInterface(i);
            if(candidate.getId()!=0 || candidate.getAlternateSetting()!=0 || candidate.getInterfaceClass()!=255) continue;
            for(int j=0;j<candidate.getEndpointCount();j++) {
                UsbEndpoint endpoint=candidate.getEndpoint(j);
                if(endpoint.getType()!=UsbConstants.USB_ENDPOINT_XFER_BULK) continue;
                if(endpoint.getAddress()==0x81) rx=endpoint;
                if(endpoint.getAddress()==0x03) output=true;
            }
            selected=candidate;
        }
        if(selected==null || rx==null || !output) throw new IOException("Unexpected Panda USB interface/endpoints");
        face=selected; input=rx;
        connection=manager.openDevice(device);
        if(connection==null) throw new IOException("Cannot open permitted Red Panda USB device");
        if(!connection.claimInterface(face,false)) { close(); throw new IOException("Red Panda interface is already owned or unavailable"); }
    }
    @Override public synchronized byte[] controlIn(int request,int length) throws Exception {
        if(connection==null) throw new IOException("Panda USB connection is closed");
        if(request!=0xc1 && request!=0xdd && request!=0xd2) throw new SecurityException("Unsupported read-only Panda request");
        if(length<1 || length>256) throw new IllegalArgumentException("Invalid control read length");
        byte[] data=new byte[length];
        int count=connection.controlTransfer(0xc0,request,0,0,data,length,250);
        if(count<0) { close(); throw new IOException("Panda control IN transfer failed"); }
        return Arrays.copyOf(data,count);
    }
    @Override public synchronized byte[] canRead() throws Exception {
        if(connection==null) throw new IOException("Panda USB connection is closed");
        ByteBuffer buffer=ByteBuffer.allocate(16384); UsbRequest request=new UsbRequest();
        try {
            if(!request.initialize(connection,input) || !request.queue(buffer)) throw new IOException("Cannot queue Panda CAN read");
            try {
                if(connection.requestWait(100)!=request) throw new IOException("Panda disconnected during CAN read");
            } catch(TimeoutException idle) {
                if(!request.cancel()) throw new IOException("Cannot cancel idle Panda CAN read");
                try {
                    if(connection.requestWait(100)!=request) throw new IOException("Panda CAN cancellation did not complete");
                } catch(TimeoutException failedCancel) { close(); throw new IOException("Panda CAN read cancellation timed out",failedCancel); }
            }
            return Arrays.copyOf(buffer.array(),buffer.position());
        } catch(Exception failure) { close(); throw failure; }
        finally { request.close(); }
    }
    @Override public synchronized void close() {
        if(connection!=null) { connection.releaseInterface(face); connection.close(); connection=null; }
    }
}
