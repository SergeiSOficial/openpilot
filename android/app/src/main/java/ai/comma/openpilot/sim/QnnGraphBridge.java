package ai.comma.openpilot.sim;

import java.lang.reflect.*;
import java.nio.*;
import java.util.*;
import org.json.*;

/** Generic tensor diagnostics; never used by the default simulation backend. */
public final class QnnGraphBridge implements AutoCloseable {
    private static volatile java.lang.ref.WeakReference<android.app.Activity> foreground=new java.lang.ref.WeakReference<>(null);
    public static void attachActivity(android.app.Activity activity) {foreground=new java.lang.ref.WeakReference<>(activity);}
    public static int thermalStatus() {
        try {var activity=foreground.get();
            return activity==null?android.os.PowerManager.THERMAL_STATUS_SHUTDOWN:
                activity.getSystemService(android.os.PowerManager.class).getCurrentThermalStatus();
        } catch(RuntimeException failure) {return android.os.PowerManager.THERMAL_STATUS_SHUTDOWN;}
    }
    public static boolean foregroundVisible() throws InterruptedException {
        var done=new java.util.concurrent.CountDownLatch(1);var visible=new java.util.concurrent.atomic.AtomicBoolean();
        new android.os.Handler(android.os.Looper.getMainLooper()).post(() -> {
            try {var activity=foreground.get();visible.set(activity!=null && activity.hasWindowFocus()
                && activity.getSystemService(android.os.PowerManager.class).isInteractive()
                && !activity.getSystemService(android.app.KeyguardManager.class).isDeviceLocked());}finally {done.countDown();}
        });
        return done.await(2,java.util.concurrent.TimeUnit.SECONDS) && visible.get();
    }
    private Object environment,options,session,result;
    private Class<?> tensorClass,envClass,typeClass;
    private final Map<String,Object> owned=new LinkedHashMap<>(),inputs=new LinkedHashMap<>();
    private final Map<String,ByteBuffer> storage=new HashMap<>();
    private final Map<String,Object> infos=new LinkedHashMap<>();
    private boolean registered,environmentSet,closed;
    private String previousAdsp;
    private final String modelRole;

    public QnnGraphBridge(String model,String backend,String nativeDirectory,String profile) throws Exception {
        this(model,backend,nativeDirectory,profile,"road");
    }
    public QnnGraphBridge(String model,String backend,String nativeDirectory,String profile,String role) throws Exception {
        if(!Set.of("cpu","htp").contains(backend))throw new IllegalArgumentException("Unknown graph backend");
        if(!Set.of("road","cabin").contains(role))throw new IllegalArgumentException("Unknown model role");
        modelRole=role;
        try {
            envClass=Class.forName("ai.onnxruntime.OrtEnvironment");
            tensorClass=Class.forName("ai.onnxruntime.OnnxTensor");typeClass=Class.forName("ai.onnxruntime.OnnxJavaType");
            Class<?> optionClass=Class.forName("ai.onnxruntime.OrtSession$SessionOptions");
            environment=envClass.getMethod("getEnvironment").invoke(null);options=optionClass.getConstructor().newInstance();
            optionClass.getMethod("setIntraOpNumThreads",int.class).invoke(options,2);
            optionClass.getMethod("setInterOpNumThreads",int.class).invoke(options,1);
            optionClass.getMethod("setLoggerId",String.class).invoke(options,"openpilot-qnn-experiment-"+modelRole);
            if(backend.equals("htp")) {
                if(!envClass.getMethod("getVersion").invoke(environment).equals("1.29.0"))
                    throw new IllegalStateException("The isolated HTP experiment requires ORT1.29.0");
                Class<?> logging=Class.forName("ai.onnxruntime.OrtLoggingLevel");
                optionClass.getMethod("setSessionLogLevel",logging).invoke(options,logging.getField("ORT_LOGGING_LEVEL_VERBOSE").get(null));
                optionClass.getMethod("setSessionLogVerbosityLevel",int.class).invoke(options,1);
            }
            optionClass.getMethod("addConfigEntry",String.class,String.class).invoke(options,"session.intra_op.allow_spinning","0");
            Class<?> level=Class.forName("ai.onnxruntime.OrtSession$SessionOptions$OptLevel");
            optionClass.getMethod("setOptimizationLevel",level).invoke(options,level.getField("BASIC_OPT").get(null));
            if(backend.equals("htp")) {
                previousAdsp=android.system.Os.getenv("ADSP_LIBRARY_PATH");
                android.system.Os.setenv("ADSP_LIBRARY_PATH",nativeDirectory,true);environmentSet=true;
                envClass.getMethod("registerExecutionProviderLibrary",String.class,String.class)
                    .invoke(environment,"QNNExecutionProvider","libonnxruntime_providers_qnn.so");registered=true;
                List<Object> devices=new ArrayList<>();
                for(Object d:(Iterable<?>)envClass.getMethod("getEpDevices").invoke(environment))
                    if(d.getClass().getMethod("getEpName").invoke(d).equals("QNNExecutionProvider"))devices.add(d);
                if(devices.isEmpty())throw new IllegalStateException("No QNN device");
                optionClass.getMethod("addExecutionProvider",List.class,Map.class).invoke(options,devices,
                    Map.of("backend_type","htp","htp_arch","68","soc_model","30","offload_graph_io_quantization","0"));
                optionClass.getMethod("addConfigEntry",String.class,String.class).invoke(options,"session.disable_cpu_ep_fallback","1");
            } else optionClass.getMethod("addCPU",boolean.class).invoke(options,true);
            if(!profile.isEmpty())optionClass.getMethod("enableProfiling",String.class).invoke(options,profile);
            session=envClass.getMethod("createSession",String.class,optionClass).invoke(environment,model,options);
            for(var entry:((Map<?,?>)session.getClass().getMethod("getInputInfo").invoke(session)).entrySet())
                infos.put(entry.getKey().toString(),entry.getValue().getClass().getMethod("getInfo").invoke(entry.getValue()));
        } catch(Exception error) {
            try {close();}catch(Exception cleanup){error.addSuppressed(cleanup);}
            if(error instanceof InvocationTargetException && error.getCause() instanceof Exception)throw (Exception)error.getCause();
            throw error;
        }
    }
    public synchronized void setInput(String name,byte[] data) throws Exception {
        if(closed)throw new IllegalStateException("Closed graph");
        Object info=infos.get(name);if(info==null)throw new IllegalArgumentException("Unknown input "+name);
        if(!storage.containsKey(name)) {
            long[] shape=(long[])info.getClass().getMethod("getShape").invoke(info);
            Object type=info.getClass().getField("type").get(info);
            Object nativeType=info.getClass().getField("onnxType").get(info);
            Object createdType=nativeType.getClass().getMethod("mapFromJavaType",typeClass).invoke(null,type);
            if(!nativeType.equals(createdType))throw new IllegalArgumentException(
                "The public Java buffer factory cannot preserve "+nativeType+" input "+name);
            int size=(int)typeClass.getField("size").get(type);long bytes=size;
            for(long dimension:shape) {if(dimension<0)throw new IllegalArgumentException("Dynamic input");bytes=Math.multiplyExact(bytes,dimension);}
            if(bytes!=data.length)throw new IllegalArgumentException("Wrong input bytes "+name+": "+data.length+" != "+bytes);
            ByteBuffer buffer=ByteBuffer.allocateDirect(data.length).order(ByteOrder.nativeOrder());storage.put(name,buffer);
            owned.put(name,tensorClass.getMethod("createTensor",envClass,ByteBuffer.class,long[].class,typeClass)
                .invoke(null,environment,buffer,shape,type));
        }
        ByteBuffer buffer=storage.get(name);if(data.length!=buffer.capacity())throw new IllegalArgumentException("Input size changed");
        buffer.clear();buffer.put(data);buffer.clear();inputs.put(name,owned.get(name));
    }
    public synchronized void execute(String[] requested) throws Exception {
        if(closed || inputs.size()!=infos.size())throw new IllegalStateException("Missing graph inputs");
        Object next;
        if(requested.length==0)next=session.getClass().getMethod("run",Map.class).invoke(session,inputs);
        else next=session.getClass().getMethod("run",Map.class,Set.class).invoke(session,inputs,new LinkedHashSet<>(Arrays.asList(requested)));
        Object old=result;result=next;if(old!=null)((AutoCloseable)old).close();
    }
    public synchronized byte[] output(String name) throws Exception {
        Object value=((Optional<?>)result.getClass().getMethod("get",String.class).invoke(result,name)).orElseThrow();
        ByteBuffer buffer=(ByteBuffer)tensorClass.getMethod("getByteBuffer").invoke(value);
        byte[] data=new byte[buffer.remaining()];buffer.get(data);return data;
    }
    public synchronized void advanceStates() throws Exception {
        for(String name:infos.keySet())if(name.startsWith("state_")) {
            if(modelRole.equals("cabin"))throw new IllegalStateException("Cabin model must remain stateless");
            inputs.put(name,((Optional<?>)result.getClass().getMethod("get",String.class).invoke(result,"next_"+name)).orElseThrow());
        }
    }
    public String endProfiling() throws Exception {return session.getClass().getMethod("endProfiling").invoke(session).toString();}
    public synchronized void close() throws Exception {
        if(closed)return;closed=true;Exception failure=null;
        List<Object> objects=new ArrayList<>(owned.values());objects.add(result);objects.add(session);objects.add(options);
        for(Object object:objects)if(object instanceof AutoCloseable)try {((AutoCloseable)object).close();}catch(Exception e){if(failure==null)failure=e;else failure.addSuppressed(e);}
        try {if(registered)envClass.getMethod("unregisterExecutionProviderLibrary",String.class).invoke(environment,"QNNExecutionProvider");}
        catch(Exception e){if(failure==null)failure=e;else failure.addSuppressed(e);}
        finally {if(environmentSet) {if(previousAdsp==null)android.system.Os.unsetenv("ADSP_LIBRARY_PATH");else android.system.Os.setenv("ADSP_LIBRARY_PATH",previousAdsp,true);}}
        if(failure!=null)throw failure;
    }
}
