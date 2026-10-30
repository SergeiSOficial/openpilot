package ai.comma.openpilot.sim;

import java.nio.*;
import java.lang.reflect.*;
import java.util.*;

/** Reference-only bridge; ORT is an Android CPU runtime, never executed by host tests. */
public final class DriverReference {
    private static Object cachedSession;
    private static String cachedPath;
    private DriverReference() {}
    public static void close() {
        try {if(cachedSession instanceof AutoCloseable)((AutoCloseable)cachedSession).close();}
        catch(Exception error){android.util.Log.e("OpenpilotDriver","ORT session cleanup",error);}
        finally {cachedSession=null;cachedPath=null;}
    }
    public static float[] zeroInput(String path) throws Exception {
        // Warm the same persistent session used by live diagnostic frames.
        return runBuffer(path,ByteBuffer.allocateDirect(1440*960).order(ByteOrder.nativeOrder()),new float[3]);
    }

    /** Export ORT's mandatory CPU lowering, including its FP16 precision casts.
     * The original file is never modified. NO_OPT matches runBuffer's reference.
     * Used only by numerical diagnostics, outside performance measurements.
     */
    public static synchronized String loweredModel(String path,String target) throws Exception {
        if(new java.io.File(path).getCanonicalPath().equals(new java.io.File(target).getCanonicalPath()))
            throw new IllegalArgumentException("Lowering must preserve the original model");
        Class<?> environmentClass=Class.forName("ai.onnxruntime.OrtEnvironment");
        Class<?> optionsClass=Class.forName("ai.onnxruntime.OrtSession$SessionOptions");
        Class<?> levelClass=Class.forName("ai.onnxruntime.OrtSession$SessionOptions$OptLevel");
        Object environment=environmentClass.getMethod("getEnvironment").invoke(null);
        Object options=optionsClass.getConstructor().newInstance();
        try {
            optionsClass.getMethod("addCPU",boolean.class).invoke(options,true);
            optionsClass.getMethod("setIntraOpNumThreads",int.class).invoke(options,1);
            optionsClass.getMethod("setOptimizationLevel",levelClass).invoke(options,levelClass.getField("NO_OPT").get(null));
            optionsClass.getMethod("setOptimizedModelFilePath",String.class).invoke(options,target);
            Object session=environmentClass.getMethod("createSession",String.class,optionsClass).invoke(environment,path,options);
            ((AutoCloseable)session).close();
            if(!new java.io.File(target).isFile())throw new IllegalStateException("ORT did not export CPU lowering");
            return target;
        }finally{((AutoCloseable)options).close();}
    }

    public static synchronized float[] runBuffer(String path,ByteBuffer pixels,float[] calibration) throws Exception {
        float[] output=runOutputs(path,pixels,calibration,new String[]{"outputs"}).get("outputs");
        if(output.length!=553)throw new IllegalStateException("Unexpected driver model output");
        return output;
    }

    public static synchronized Map<String,float[]> zeroIntermediates(String path,String[] names) throws Exception {
        if(names.length>256)throw new IllegalArgumentException("Diagnostic output limit");
        return runOutputs(path,ByteBuffer.allocateDirect(1440*960).order(ByteOrder.nativeOrder()),new float[3],names);
    }

    private static Map<String,float[]> runOutputs(String path,ByteBuffer pixels,float[] calibration,String[] names) throws Exception {
        if(!pixels.isDirect()||pixels.remaining()!=1440*960||calibration.length!=3)
            throw new IllegalArgumentException("Driver input must be a direct 1440x960 luma buffer and 3 calibration values");
        Class<?> environmentClass=Class.forName("ai.onnxruntime.OrtEnvironment");
        Class<?> optionsClass=Class.forName("ai.onnxruntime.OrtSession$SessionOptions");
        Class<?> tensorClass=Class.forName("ai.onnxruntime.OnnxTensor");
        Class<?> typeClass=Class.forName("ai.onnxruntime.OnnxJavaType");
        Object environment=environmentClass.getMethod("getEnvironment").invoke(null);
        if(cachedSession==null||!path.equals(cachedPath)) {
            if(cachedSession instanceof AutoCloseable)((AutoCloseable)cachedSession).close();
            Object options=optionsClass.getConstructor().newInstance();
            try {
                optionsClass.getMethod("addCPU",boolean.class).invoke(options,true);
                optionsClass.getMethod("setIntraOpNumThreads",int.class).invoke(options,1);
                Class<?> levelClass=Class.forName("ai.onnxruntime.OrtSession$SessionOptions$OptLevel");
                optionsClass.getMethod("setOptimizationLevel",levelClass).invoke(options,levelClass.getField("NO_OPT").get(null));
                cachedSession=environmentClass.getMethod("createSession",String.class,optionsClass).invoke(environment,path,options);cachedPath=path;
            }finally{((AutoCloseable)options).close();}
        }
        Object image=null,calib=null,result=null;
        try {
            image=tensorClass.getMethod("createTensor",environmentClass,ByteBuffer.class,long[].class,typeClass)
                .invoke(null,environment,pixels,new long[]{1,1440*960},typeClass.getField("UINT8").get(null));
            FloatBuffer values=ByteBuffer.allocateDirect(12).order(ByteOrder.nativeOrder()).asFloatBuffer();values.put(calibration).rewind();
            calib=tensorClass.getMethod("createTensor",environmentClass,FloatBuffer.class,long[].class)
                .invoke(null,environment,values,new long[]{1,3});
            Map<String,Object> inputs=new HashMap<>();inputs.put("input_img",image);inputs.put("calib",calib);
            result=cachedSession.getClass().getMethod("run",Map.class).invoke(cachedSession,inputs);
            Map<String,float[]> outputs=new LinkedHashMap<>();long total=0;
            for(String name:names) {
                Object output=((Optional<?>)result.getClass().getMethod("get",String.class).invoke(result,name)).orElseThrow();
                FloatBuffer buffer=(FloatBuffer)tensorClass.getMethod("getFloatBuffer").invoke(output);
                if(buffer==null)throw new IllegalStateException("Diagnostic requires floating point output: "+name);
                total+=buffer.remaining()*4L;
                if(total>128*1024*1024)throw new IllegalStateException("Diagnostic output byte limit");
                float[] floats=new float[buffer.remaining()];buffer.get(floats);outputs.put(name,floats);
            }
            return outputs;
        }finally{for(Object value:new Object[]{result,calib,image})if(value instanceof AutoCloseable)((AutoCloseable)value).close();}
    }
}
