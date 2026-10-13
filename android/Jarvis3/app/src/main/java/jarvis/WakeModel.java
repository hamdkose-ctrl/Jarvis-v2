package jarvis;

import android.content.Context;

import org.json.JSONObject;
import org.vosk.LibVosk;
import org.vosk.LogLevel;
import org.vosk.Model;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * İnternetsiz uyandırma için Vosk'un küçük Türkçe modeli (~35 MB): ilk kullanımda bir kez indirilir.
 * Ayrıca duyulanla uyandırma kelimesini karşılaştıran esnek eşleştirme ("cervis", "carvis" de Jarvis sayılır).
 */
public final class WakeModel {
    private WakeModel() {}

    /** Aynı model iki yerde: önce resmi sunucu, ulaşılamazsa Hugging Face kopyası. */
    public static final String[] URLS = {
            "https://alphacephei.com/vosk/models/vosk-model-small-tr-0.3.zip",
            "https://huggingface.co/rhasspy/vosk-models/resolve/main/tr/vosk-model-small-tr-0.3.zip",
    };
    private static Model model;
    private static final Locale TR = new Locale("tr", "TR");

    public interface Progress {
        void on(int percent);
    }

    private static File root(Context c) {
        return new File(c.getFilesDir(), "vosk-tr");
    }

    /** Modelin asıl klasörü; yoksa null. Zip'te dosyalar doğrudan ya da bir-iki alt klasörde olabilir. */
    private static File folder(Context c) {
        return find(root(c), 0);
    }

    /** Yeni düzen: am/ + conf/ klasörleri. Eski düzen (Türkçe küçük model 0.3 böyle): final.mdl doğrudan klasörde. */
    private static boolean isModel(File f) {
        boolean v2 = new File(f, "am").isDirectory() && new File(f, "conf").isDirectory();
        boolean v1 = new File(f, "final.mdl").isFile() && new File(f, "mfcc.conf").isFile();
        return v2 || v1;
    }

    private static File find(File dir, int depth) {
        if (dir == null || !dir.isDirectory()) return null;
        if (isModel(dir)) return dir;
        if (depth >= 2) return null;
        File[] subs = dir.listFiles(File::isDirectory);
        if (subs == null) return null;
        for (File f : subs) {
            File m = find(f, depth + 1);
            if (m != null) return m;
        }
        return null;
    }

    public static boolean ready(Context c) {
        return folder(c) != null;
    }

    /** Modeli indirip açar (arka plan iş parçacığında çağır). Kaynaklar sırayla denenir. */
    public static void download(Context c, Progress p) throws IOException {
        StringBuilder errs = new StringBuilder();
        for (int i = 0; i < URLS.length; i++) {
            try {
                downloadFrom(c, URLS[i], p);
                return;
            } catch (IOException e) {
                String host = URLS[i].replaceAll("https://([^/]+)/.*", "$1");
                errs.append("\n• ").append(host).append(": ").append(explain(e));
            }
        }
        throw new IOException("Hiçbir kaynaktan indirilemedi:" + errs);
    }

    private static String explain(IOException e) {
        if (e instanceof java.net.UnknownHostException) return "sunucu adı çözülemedi (DNS / internet yok)";
        if (e instanceof java.net.SocketTimeoutException) return "zaman aşımı (bağlantı çok yavaş)";
        if (e instanceof javax.net.ssl.SSLException) return "güvenli bağlantı kurulamadı (" + e.getMessage() + ")";
        if (e instanceof java.net.ConnectException) return "bağlantı reddedildi / engelli";
        return String.valueOf(e.getMessage() != null ? e.getMessage() : e);
    }

    private static void downloadFrom(Context c, String url, Progress p) throws IOException {
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        con.setConnectTimeout(20000);
        con.setReadTimeout(60000);
        con.setInstanceFollowRedirects(true);
        con.setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android) JarvisApp/3.0");
        int code = con.getResponseCode();
        if (code != 200) {
            con.disconnect();
            throw new IOException("sunucu " + code + " döndürdü");
        }
        long total = con.getContentLengthLong();
        try (InputStream raw = con.getInputStream()) {
            unpack(c, raw, total, p);
        } finally {
            con.disconnect();
        }
    }

    /** Telefonun tarayıcısıyla indirilmiş zip dosyasından yükler (internet sorunu olursa). */
    public static void importZip(Context c, android.net.Uri uri, Progress p) throws IOException {
        long total = -1;
        try (android.content.res.AssetFileDescriptor fd = c.getContentResolver().openAssetFileDescriptor(uri, "r")) {
            if (fd != null) total = fd.getLength();
        } catch (Exception ignored) {
        }
        try (InputStream raw = c.getContentResolver().openInputStream(uri)) {
            if (raw == null) throw new IOException("Dosya açılamadı.");
            unpack(c, raw, total, p);
        }
    }

    private static void unpack(Context c, InputStream raw, long total, Progress p) throws IOException {
        File tmp = new File(c.getFilesDir(), "vosk-tr.tmp");
        deleteTree(tmp);
        final long[] read = {0};
        int[] last = {-1};
        try (InputStream counting = new InputStream() {
                 @Override
                 public int read() throws IOException {
                     int b = raw.read();
                     if (b >= 0) tick(1);
                     return b;
                 }

                 @Override
                 public int read(byte[] b, int off, int len) throws IOException {
                     int n = raw.read(b, off, len);
                     if (n > 0) tick(n);
                     return n;
                 }

                 private void tick(int n) {
                     read[0] += n;
                     if (total > 0) {
                         int pc = (int) (read[0] * 100 / total);
                         if (pc != last[0]) {
                             last[0] = pc;
                             p.on(pc);
                         }
                     }
                 }
             };
             ZipInputStream zin = new ZipInputStream(counting)) {
            ZipEntry e;
            byte[] buf = new byte[65536];
            String base = tmp.getCanonicalPath() + File.separator;
            while ((e = zin.getNextEntry()) != null) {
                File out = new File(tmp, e.getName());
                if (!out.getCanonicalPath().startsWith(base)) continue;     // zip içinden dışarı yazma girişimi
                if (e.isDirectory()) {
                    //noinspection ResultOfMethodCallIgnored
                    out.mkdirs();
                    continue;
                }
                File parent = out.getParentFile();
                //noinspection ResultOfMethodCallIgnored
                if (parent != null) parent.mkdirs();
                try (OutputStream o = new FileOutputStream(out)) {
                    int n;
                    while ((n = zin.read(buf)) > 0) o.write(buf, 0, n);
                }
            }
        }
        File r = root(c);
        deleteTree(r);
        if (!tmp.renameTo(r)) throw new IOException("Model klasörü kaydedilemedi.");
        if (!ready(c)) throw new IOException("Dosyanın içinde ses modeli bulunamadı (doğru zip mi? vosk-model-small-tr-0.3.zip olmalı).");
    }

    private static void deleteTree(File f) {
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) deleteTree(k);
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }

    /** Modeli bir kez yükler (1-2 sn; arka planda çağır). Ekran ve servis aynı modeli paylaşır. */
    public static synchronized Model get(Context c) throws IOException {
        if (model != null) return model;
        File f = folder(c);
        if (f == null) throw new IOException("Uyandırma modeli henüz indirilmedi.");
        LibVosk.setLogLevel(LogLevel.WARNINGS);
        model = new Model(f.getAbsolutePath());
        return model;
    }

    // ------------------------------------------------------------------ eşleştirme
    /** Vosk'un JSON çıktısından metin ("partial" ya da "text"). */
    public static String text(String json) {
        try {
            JSONObject o = new JSONObject(json);
            return o.has("partial") ? o.optString("partial", "") : o.optString("text", "");
        } catch (Exception e) {
            return "";
        }
    }

    /** Türkçe harfleri ve benzer sesleri sadeleştirir: "Jarvis" ve "carvis" aynı biçime gelir. */
    public static String fold(String s) {
        String t = s.toLowerCase(TR)
                .replace('ç', 'c').replace('ğ', 'g').replace('ı', 'i').replace('ö', 'o')
                .replace('ş', 's').replace('ü', 'u').replace('â', 'a').replace('î', 'i').replace('û', 'u')
                .replace('j', 'c').replace('w', 'v').replace('q', 'k').replace("x", "ks");
        return t.replaceAll("[^a-z ]", " ").replaceAll("\\s+", " ").trim();
    }

    private static double sim(String a, String b) {
        int n = a.length(), m = b.length();
        if (n == 0 || m == 0) return 0;
        int[] prev = new int[m + 1], cur = new int[m + 1];
        for (int j = 0; j <= m; j++) prev[j] = j;
        for (int i = 1; i <= n; i++) {
            cur[0] = i;
            for (int j = 1; j <= m; j++) {
                int cost = a.charAt(i - 1) == b.charAt(j - 1) ? 0 : 1;
                cur[j] = Math.min(Math.min(cur[j - 1] + 1, prev[j] + 1), prev[j - 1] + cost);
            }
            int[] t = prev;
            prev = cur;
            cur = t;
        }
        return 1.0 - prev[m] / (double) Math.max(n, m);
    }

    /** Duyulan cümlede uyandırma kelimesi (ya da öğrenilmiş bir benzeri) var mı? */
    public static boolean matches(String heard, User u) {
        String h = fold(heard);
        if (h.isEmpty()) return false;
        String[] tok = h.split(" ");
        List<String> targets = new ArrayList<>();
        targets.add(fold(u.wakeWord()).replace(" ", ""));
        for (String a : u.wakeAlts) targets.add(fold(a).replace(" ", ""));
        double thr = u.wakeSens == 0 ? 0.84 : u.wakeSens == 2 ? 0.62 : 0.72;
        for (String target : targets) {
            if (target.isEmpty()) continue;
            double t = target.length() <= 4 ? Math.max(thr, 0.8) : thr;
            for (int i = 0; i < tok.length; i++) {
                StringBuilder w = new StringBuilder();
                for (int k = i; k < Math.min(tok.length, i + 3); k++) {
                    w.append(tok[k]);
                    if (sim(w.toString(), target) >= t) return true;
                }
            }
        }
        return false;
    }
}
