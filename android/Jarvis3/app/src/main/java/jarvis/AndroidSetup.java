package jarvis;
import android.os.Handler;
import android.os.Looper;
import org.json.JSONObject;
import org.json.JSONException;
import java.net.URL;
import java.net.URI;
import javax.net.ssl.HttpsURLConnection;
import java.nio.charset.StandardCharsets;
import java.io.*;

/** Redeem a key-free QR via normal certificate-checked Tailscale HTTPS. */
final class AndroidSetup {
    interface Callback { void ok(User user); void err(String message); }
    private static final GeminiWorkers WORKERS = new GeminiWorkers();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    static boolean isSetupQr(String raw) {
        try { return raw != null && new JSONObject(raw).optInt("v",0)==2; }
        catch(JSONException e) { return false; }
    }
    static URL endpoint(JSONObject qr) throws Exception {
        if(!"jarvis-android".equals(qr.optString("j")) || qr.optInt("v",0)!=2)
            throw new IllegalArgumentException("Geçersiz kurulum QR'ı.");
        URI uri = new URI(qr.optString("u"));
        String host = uri.getHost();
        if(!"https".equals(uri.getScheme()) || host==null || !host.toLowerCase(java.util.Locale.ROOT).endsWith(".ts.net")
                || uri.getUserInfo()!=null || (uri.getPort()!=-1 && uri.getPort()!=443)
                || !"/api/android-setup".equals(uri.getPath()) || uri.getQuery()!=null || uri.getFragment()!=null)
            throw new IllegalArgumentException("Kurulum güvenli Tailscale HTTPS adresi gerektirir.");
        if(!qr.optString("c").matches("[A-Za-z0-9_-]{40,100}"))
            throw new IllegalArgumentException("Geçersiz kurulum kodu.");
        return uri.toURL();
    }
    static void fetch(String raw, Callback cb) {
        if(raw==null || raw.length()>4096) { cb.err("Geçersiz QR boyutu.");return; }
        if(!WORKERS.submit(()-> {
            HttpsURLConnection connection = null;
            try {
                JSONObject qr = new JSONObject(raw);
                connection = (HttpsURLConnection)endpoint(qr).openConnection();
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(10000);connection.setReadTimeout(15000);
                connection.setRequestMethod("POST");connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type","application/json");
                byte[] body = new JSONObject().put("code",qr.optString("c")).toString().getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(body.length);
                try(OutputStream out=connection.getOutputStream()) { out.write(body); }
                if(connection.getResponseCode()!=200) throw new IOException("Kurulum kodu kullanılmış, süresi dolmuş veya bağlantı reddedilmiş.");
                ByteArrayOutputStream bytes=new ByteArrayOutputStream();
                try(InputStream in=connection.getInputStream()) {
                    byte[] chunk=new byte[1024];int n;
                    while((n=in.read(chunk))!=-1) {
                        if(bytes.size()+n>16384)throw new IOException("Kurulum yanıtı çok büyük.");
                        bytes.write(chunk,0,n);
                    }
                }
                User user=User.fromQr(bytes.toString(StandardCharsets.UTF_8.name()));
                MAIN.post(()->cb.ok(user));
            } catch(Exception e) {
                MAIN.post(()->cb.err("Güvenli kurulum tamamlanamadı. Telefonun Tailscale bağlantısını kontrol et ve bilgisayarda yeni QR oluştur."));
            } finally { if(connection!=null)connection.disconnect(); }
        })) cb.err("Kurulum işlemi meşgul. Birazdan tekrar dene.");
    }
}
