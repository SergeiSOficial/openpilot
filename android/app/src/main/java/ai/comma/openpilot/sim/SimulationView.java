package ai.comma.openpilot.sim;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ImageFormat;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.YuvImage;
import android.view.View;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.nio.file.Files;
import org.json.JSONArray;
import org.json.JSONObject;

final class SimulationView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private Bitmap camera;
    private JSONObject path;
    SimulationView(Context context) { super(context); setMinimumHeight(280); }

    static Bitmap loadFrame(File files, int frame) throws Exception {
        File root = new File(files, "fixture");
        JSONObject info = new JSONObject(new String(Files.readAllBytes(new File(root, "fixture.json").toPath()), java.nio.charset.StandardCharsets.UTF_8))
            .getJSONObject("cameras").getJSONObject("narrowRoadCameraState");
        int width = info.getInt("width"), height = info.getInt("height"), stride = info.getInt("stride");
        byte[] padded = Files.readAllBytes(new File(root, String.format(java.util.Locale.ROOT,
            "narrowRoadCameraState/%04d.nv12", frame)).toPath());
        byte[] nv21 = new byte[width * height * 3 / 2];
        for (int row = 0; row < height; row++) System.arraycopy(padded, row*stride, nv21, row*width, width);
        int uv = stride * info.getInt("y_height");
        for (int row = 0; row < height/2; row++) {
            for (int col = 0; col < width; col += 2) {
                int dest = width*height + row*width + col, source = uv + row*stride + col;
                nv21[dest] = padded[source+1]; nv21[dest+1] = padded[source];
            }
        }
        ByteArrayOutputStream jpeg = new ByteArrayOutputStream();
        new YuvImage(nv21, ImageFormat.NV21, width, height, null)
            .compressToJpeg(new Rect(0, 0, width, height), 80, jpeg);
        byte[] bytes = jpeg.toByteArray();
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
    }

    void update(Bitmap image, JSONObject modelPath) {
        Bitmap previous = camera;
        camera = image; path = modelPath; invalidate();
        if (previous != null && previous != image) previous.recycle();
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawColor(Color.rgb(20, 26, 32));
        if (camera == null) {
            paint.setColor(Color.LTGRAY); paint.setTextSize(24);
            canvas.drawText("Recorded road camera · awaiting model output", 24, getHeight()/2f, paint);
            return;
        }
        float aspect = camera.getWidth()/(float)camera.getHeight();
        float width = Math.min(getWidth(), getHeight()*aspect), height = width/aspect;
        RectF target = new RectF((getWidth()-width)/2, (getHeight()-height)/2, (getWidth()+width)/2, (getHeight()+height)/2);
        canvas.drawBitmap(camera, null, target, paint);
        if (path != null) {
            JSONArray x = path.optJSONArray("x"), y = path.optJSONArray("y"), z = path.optJSONArray("z");
            if (x != null && y != null && z != null) {
                Path line = new Path(); boolean first = true;
                for (int i = 0; i < Math.min(x.length(), y.length()); i++) {
                    float distance = (float)x.optDouble(i);
                    if (distance < 2) continue;
                    // Perspective preview using a nominal camera height.
                    float px = target.centerX() - (float)y.optDouble(i)/distance*width*0.7f;
                    float py = target.centerY() + (1.2f+(float)z.optDouble(i))/distance*height*0.9f;
                    if (first) { line.moveTo(px, py); first = false; } else line.lineTo(px, py);
                }
                paint.setColor(Color.rgb(80, 255, 150)); paint.setStrokeWidth(7); paint.setStyle(Paint.Style.STROKE);
                canvas.drawPath(line, paint); paint.setStyle(Paint.Style.FILL);
            }
        }
    }
}
