package ai.comma.openpilot.sim;

import android.content.Context;
import android.os.Build;
import android.os.PerformanceHintManager;
import android.os.Process;

/** Optional per-process Android scheduler hints; never changes system policy. */
public final class LivePerformance {
    private static PerformanceHintManager manager;
    private static PerformanceHintManager.Session session;
    public static void initialize(Context context) {
        if(Build.VERSION.SDK_INT>=31)manager=context.getSystemService(PerformanceHintManager.class);
    }
    public static synchronized void report(long durationNs) {
        if(manager==null||durationNs<=0)return;
        try {
            if(session==null)session=manager.createHintSession(new int[]{Process.myTid()},50_000_000L);
            if(session!=null)session.reportActualWorkDuration(durationNs);
        } catch(RuntimeException failure) {close();manager=null;}
    }
    public static synchronized void close() {if(session!=null){session.close();session=null;}}
}
