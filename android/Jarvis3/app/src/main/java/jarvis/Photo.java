package jarvis;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.media.ExifInterface;
import android.net.Uri;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;

/** Fotoğrafı Gemini'ye uygun hale getirir: döndürür, küçültür (yazı okunur kalacak kadar), JPEG yapar. */
public final class Photo {
    private Photo() {}

    public static final int MAX_SIDE = 1600;   // soru metni okunur kalsın, yükleme hızlı olsun

    /** Uri'den (kamera ya da galeri) okunmuş, döndürülmüş, küçültülmüş JPEG. */
    public static byte[] prepare(Context c, Uri uri) throws IOException {
        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        try (InputStream in = c.getContentResolver().openInputStream(uri)) {
            if (in == null) throw new IOException("Fotoğraf açılamadı.");
            BitmapFactory.decodeStream(in, null, bounds);
        }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) throw new IOException("Bu dosya bir fotoğraf değil gibi.");
        int sample = 1;
        while (Math.max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_SIDE) sample *= 2;
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inSampleSize = sample;
        Bitmap bmp;
        try (InputStream in = c.getContentResolver().openInputStream(uri)) {
            bmp = BitmapFactory.decodeStream(in, null, o);
        }
        if (bmp == null) throw new IOException("Fotoğraf okunamadı.");

        int rot = 0;
        try (InputStream in = c.getContentResolver().openInputStream(uri)) {
            if (in != null) {
                int ori = new ExifInterface(in).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL);
                rot = ori == ExifInterface.ORIENTATION_ROTATE_90 ? 90 : ori == ExifInterface.ORIENTATION_ROTATE_180 ? 180
                        : ori == ExifInterface.ORIENTATION_ROTATE_270 ? 270 : 0;
            }
        } catch (IOException | RuntimeException ignored) {
        }
        float scale = Math.min(1f, MAX_SIDE / (float) Math.max(bmp.getWidth(), bmp.getHeight()));
        if (rot != 0 || scale < 1f) {
            Matrix m = new Matrix();
            m.postScale(scale, scale);
            m.postRotate(rot);
            Bitmap b2 = Bitmap.createBitmap(bmp, 0, 0, bmp.getWidth(), bmp.getHeight(), m, true);
            if (b2 != bmp) bmp.recycle();
            bmp = b2;
        }
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        bmp.compress(Bitmap.CompressFormat.JPEG, 85, out);
        bmp.recycle();
        return out.toByteArray();
    }

    /** Sohbet geçmişinde göstermek için fotoğrafı uygulama klasörüne kaydeder; dosya yolunu döndürür. */
    public static String save(Context c, byte[] jpeg) {
        File dir = new File(c.getFilesDir(), "foto");
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        File f = new File(dir, System.currentTimeMillis() + ".jpg");
        try (FileOutputStream o = new FileOutputStream(f)) {
            o.write(jpeg);
            return f.getAbsolutePath();
        } catch (IOException e) {
            return "";
        }
    }

    /** Dosyadan küçük önizleme (en uzun kenar yaklaşık maxPx). */
    public static Bitmap thumb(String path, int maxPx) {
        if (path == null || path.isEmpty() || !new File(path).exists()) return null;
        BitmapFactory.Options b = new BitmapFactory.Options();
        b.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(path, b);
        int s = 1;
        while (Math.max(b.outWidth, b.outHeight) / (s * 2) >= maxPx) s *= 2;
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inSampleSize = s;
        return BitmapFactory.decodeFile(path, o);
    }

    public static Bitmap thumb(byte[] jpeg, int maxPx) {
        BitmapFactory.Options b = new BitmapFactory.Options();
        b.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, b);
        int s = 1;
        while (Math.max(b.outWidth, b.outHeight) / (s * 2) >= maxPx) s *= 2;
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inSampleSize = s;
        return BitmapFactory.decodeByteArray(jpeg, 0, jpeg.length, o);
    }
}
