package ai.comma.openpilot.sim;

import java.lang.reflect.*;
import java.nio.*;
import java.util.*;

/** Android ORT runner with pooled inputs and native recurrent tensors.
 * Reflection keeps the CPU AOT APK independent of the optional ORT AAR.
 * No model, runtime or generated native executable runs on the build host.
 */
public final class OrtDrivingBridge implements AutoCloseable {
    private final Object environment, options, session;
    private final Class<?> tensorClass;
    private final Method runMethod, resultGet, floatView, byteView;
    private final Map<String,Object> inputs = new LinkedHashMap<>();
    private final Map<String,Object> initial = new LinkedHashMap<>();
    private final ByteBuffer image;
    private final Map<String,FloatBuffer> small = new HashMap<>();
    private Object previousResult;
    private boolean closed;
    private boolean qnnRegistered, qnnEnvironmentSet;
    private String previousAdsp;

    public OrtDrivingBridge(String path, String backend, int threads, String profile) throws Exception {
        this(path,backend,threads,profile,"");
    }

    public OrtDrivingBridge(String path, String backend, int threads, String profile, String nativeDirectory) throws Exception {
        if (!Set.of("cpu", "nnapi", "xnnpack", "qnn").contains(backend) || threads < 1 || threads > 4)
            throw new IllegalArgumentException("Invalid inference configuration");
        Class<?> environmentClass = Class.forName("ai.onnxruntime.OrtEnvironment");
        Class<?> optionsClass = Class.forName("ai.onnxruntime.OrtSession$SessionOptions");
        tensorClass = Class.forName("ai.onnxruntime.OnnxTensor");
        Class<?> typeClass = Class.forName("ai.onnxruntime.OnnxJavaType");
        environment = environmentClass.getMethod("getEnvironment").invoke(null);
        options = optionsClass.getConstructor().newInstance();
        Object createdSession = null;
        try {
            optionsClass.getMethod("setInterOpNumThreads", int.class).invoke(options, 1);
            optionsClass.getMethod("setIntraOpNumThreads", int.class).invoke(options, threads);
            // Disable idle spinning: modeld shares the SoC with planning/control.
            optionsClass.getMethod("addConfigEntry", String.class, String.class).invoke(options, "session.intra_op.allow_spinning", "0");
            Class<?> levelClass = Class.forName("ai.onnxruntime.OrtSession$SessionOptions$OptLevel");
            optionsClass.getMethod("setOptimizationLevel", levelClass).invoke(options, levelClass.getField("ALL_OPT").get(null));
            if (backend.equals("qnn")) {
                if (!new java.io.File(nativeDirectory).isDirectory())throw new IllegalArgumentException("QNN native directory is missing");
                previousAdsp=android.system.Os.getenv("ADSP_LIBRARY_PATH");
                android.system.Os.setenv("ADSP_LIBRARY_PATH",nativeDirectory,true);qnnEnvironmentSet=true;
                environmentClass.getMethod("registerExecutionProviderLibrary",String.class,String.class)
                    .invoke(environment,"QNNExecutionProvider","libonnxruntime_providers_qnn.so");
                qnnRegistered=true;
                List<Object> devices=new ArrayList<>();
                for(Object device:(Iterable<?>)environmentClass.getMethod("getEpDevices").invoke(environment))
                    if(device.getClass().getMethod("getEpName").invoke(device).equals("QNNExecutionProvider"))devices.add(device);
                if(devices.isEmpty())throw new IllegalStateException("QNN did not enumerate a usable device");
                optionsClass.getMethod("addExecutionProvider",List.class,Map.class)
                    .invoke(options,devices,Map.of("backend_type","htp","htp_arch","68","soc_model","30"));
                optionsClass.getMethod("addConfigEntry",String.class,String.class).invoke(options,"session.disable_cpu_ep_fallback","1");
            } else if (backend.equals("nnapi")) {
                Class<?> flagClass = Class.forName("ai.onnxruntime.providers.NNAPIFlags");
                @SuppressWarnings({"rawtypes","unchecked"})
                EnumSet<?> flags = EnumSet.of((Enum)flagClass.getField("CPU_DISABLED").get(null));
                optionsClass.getMethod("addNnapi", EnumSet.class).invoke(options, flags);
            } else if (backend.equals("xnnpack")) {
                optionsClass.getMethod("addXnnpack", Map.class).invoke(options, Map.of("intra_op_num_threads", Integer.toString(threads)));
            }
            if (!backend.equals("qnn")) optionsClass.getMethod("addCPU", boolean.class).invoke(options, true);
            if (profile != null && !profile.isEmpty()) optionsClass.getMethod("enableProfiling", String.class).invoke(options, profile);
            createdSession = environmentClass.getMethod("createSession", String.class, optionsClass).invoke(environment, path, options);
            image = bytes("new_img", new long[]{2,6,128,256}, typeClass.getField("UINT8").get(null), environmentClass, typeClass);
            bytes("state_img_q", new long[]{2,5,6,128,256}, typeClass.getField("UINT8").get(null), environmentClass, typeClass);
            floats("desire", new long[]{8}, environmentClass);
            floats("traffic_convention", new long[]{1,2}, environmentClass);
            floats("action_t", new long[]{1,2}, environmentClass);
            floats("state_desire_q", new long[]{100,1,8}, environmentClass);
            floats("state_feat_q", new long[]{96,1,512}, environmentClass);
            initial.putAll(inputs);
        } catch (Exception failure) {
            for (Object value : inputs.values()) closeResource(value);
            closeResource(createdSession); closeResource(options);
            try {closeQnn();}catch(Exception cleanup){failure.addSuppressed(cleanup);}
            if(failure instanceof InvocationTargetException && failure.getCause() instanceof Exception)
                throw (Exception)failure.getCause();
            throw failure;
        }
        session = createdSession;
        runMethod = session.getClass().getMethod("run", Map.class);
        Class<?> resultClass = Class.forName("ai.onnxruntime.OrtSession$Result");
        resultGet = resultClass.getMethod("get", String.class);
        floatView = tensorClass.getMethod("getFloatBuffer");
        byteView = tensorClass.getMethod("getByteBuffer");
    }

    private static int elements(long[] shape) {
        long count = 1; for (long value : shape) count = Math.multiplyExact(count,value);
        return Math.toIntExact(count);
    }
    private ByteBuffer bytes(String name, long[] shape, Object type, Class<?> envClass, Class<?> typeClass) throws Exception {
        ByteBuffer storage = ByteBuffer.allocateDirect(elements(shape)).order(ByteOrder.nativeOrder());
        inputs.put(name, tensorClass.getMethod("createTensor", envClass, ByteBuffer.class, long[].class, typeClass)
            .invoke(null, environment, storage, shape, type));
        return storage;
    }
    private void floats(String name, long[] shape, Class<?> envClass) throws Exception {
        FloatBuffer storage = ByteBuffer.allocateDirect(4*elements(shape)).order(ByteOrder.nativeOrder()).asFloatBuffer();
        inputs.put(name, tensorClass.getMethod("createTensor", envClass, FloatBuffer.class, long[].class)
            .invoke(null, environment, storage, shape));
        small.put(name,storage);
    }
    private Object output(String name) throws Exception {
        if (previousResult == null) throw new IllegalStateException("No inference output");
        return ((Optional<?>)resultGet.invoke(previousResult,name)).orElseThrow();
    }
    private void smallInput(String name, float[] values) {
        FloatBuffer target = small.get(name);
        if (values.length != target.capacity()) throw new IllegalArgumentException("Input shape differs: "+name);
        for (float value : values) if (!Float.isFinite(value)) throw new IllegalArgumentException("Non-finite input: "+name);
        target.clear(); target.put(values); target.clear();
    }
    public synchronized float[] run(byte[] pixels, float[] desire, float[] traffic, float[] action) throws Exception {
        if (closed) throw new IllegalStateException("Inference runner is closed");
        if (pixels.length != image.capacity()) throw new IllegalArgumentException("Invalid driving image size");
        image.clear(); image.put(pixels); image.clear();
        smallInput("desire",desire); smallInput("traffic_convention",traffic); smallInput("action_t",action);
        Object result = runMethod.invoke(session,inputs);
        Object oldResult = previousResult;
        previousResult = result;
        for (String name : List.of("state_img_q","state_desire_q","state_feat_q")) inputs.put(name,output("next_"+name));
        closeResource(oldResult);
        float[] raw = outputFloats("outputs");
        for (float value : raw) if (!Float.isFinite(value)) throw new IllegalStateException("Non-finite driving output");
        return raw;
    }
    public synchronized float[] outputFloats(String name) throws Exception {
        FloatBuffer source = (FloatBuffer)floatView.invoke(output(name));
        float[] values = new float[source.remaining()]; source.get(values); return values;
    }
    public synchronized byte[] outputBytes(String name) throws Exception {
        ByteBuffer source = (ByteBuffer)byteView.invoke(output(name));
        byte[] values = new byte[source.remaining()]; source.get(values); return values;
    }
    public synchronized void reset() throws Exception {
        inputs.clear(); inputs.putAll(initial);
        closeResource(previousResult); previousResult = null;
    }
    public String endProfiling() throws Exception { return session.getClass().getMethod("endProfiling").invoke(session).toString(); }
    private static void closeResource(Object object) throws Exception { if (object instanceof AutoCloseable) ((AutoCloseable)object).close(); }
    private void closeQnn() throws Exception {
        try {
            if(qnnRegistered)environment.getClass().getMethod("unregisterExecutionProviderLibrary",String.class).invoke(environment,"QNNExecutionProvider");
        } finally {
            qnnRegistered=false;
            if(qnnEnvironmentSet) {
                if(previousAdsp==null)android.system.Os.unsetenv("ADSP_LIBRARY_PATH");else android.system.Os.setenv("ADSP_LIBRARY_PATH",previousAdsp,true);
                qnnEnvironmentSet=false;
            }
        }
    }
    @Override public synchronized void close() throws Exception {
        if (closed) return;
        closed = true;
        List<Object> resources=new ArrayList<>(initial.values());resources.add(previousResult);resources.add(session);resources.add(options);
        previousResult=null;Exception failure=null;
        for(Object resource:resources)try {closeResource(resource);}catch(Exception error) {
            if(failure==null)failure=error;else failure.addSuppressed(error);
        }
        try {closeQnn();}catch(Exception error){if(failure==null)failure=error;else failure.addSuppressed(error);}
        if(failure!=null)throw failure;
    }
}
