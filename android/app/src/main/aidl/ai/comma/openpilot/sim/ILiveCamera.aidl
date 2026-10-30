package ai.comma.openpilot.sim;
import android.view.Surface;
import android.graphics.Bitmap;
interface ILiveCamera {
    void start(String session, String mode, in Surface roadPreview, in Surface cabinPreview, int rotation);
    String status();
    Bitmap thumbnail(int stream);
    void stop();
    void resetCounters();
}
