package jarvis;

import android.os.Handler;
import android.os.Looper;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** Gemini'ye doğrudan (kullanıcının kendi anahtarıyla) bağlanır; bilgisayar gerekmez. */
public final class Gemini {
    private Gemini() {}

    public interface Callback {
        void ok(String text);

        void err(String message);
    }

    private static final GeminiWorkers EX = new GeminiWorkers();
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final String BASE = "https://generativelanguage.googleapis.com/v1beta/models/";

    /** Fotoğraflı soruda modele giden talimat. */
    public static String photoPrompt(boolean stepByStep, String userText) {
        String q = userText == null ? "" : userText.trim();
        String base = stepByStep
                ? "Fotoğraftaki soruyu çöz. Önce soruyu bir cümleyle özetle, sonra çözümü numaralı adımlarla, "
                + "bir öğrenciye anlatır gibi açıkla. En sonda ayrı satırda 'Cevap: ...' yaz; çoktan seçmeliyse doğru şıkkı belirt. "
                + "Fotoğraf okunmuyorsa ya da soru eksikse bunu söyle ve tahmin yürütme."
                : "Fotoğraftaki sorunun yalnızca doğru cevabını ver: çoktan seçmeliyse şıkkı ve tek cümlelik gerekçeyi yaz. "
                + "Fotoğraf okunmuyorsa bunu söyle.";
        if (!q.isEmpty()) base += " Kullanıcının notu: " + q;
        return base;
    }

    /** Kullanıcıya ve hedeflerine göre Jarvis'in kişiliği. */
    public static String persona(User u) {
        String now = new SimpleDateFormat("d MMMM yyyy EEEE, HH:mm", new Locale("tr", "TR")).format(new Date());
        StringBuilder s = new StringBuilder();
        s.append("Sen ").append(u.assistant).append(", ").append(u.name)
                .append(" adlı kullanıcının telefonundaki kişisel yapay zeka asistanısın. Türkçe konuş, samimi ama saygılı ol. ")
                .append("Kullanıcı hızlı yazar ve yazım hataları yapabilir: ne demek istediğini anlamaya çalış, hatalarını düzeltip yüzüne vurma; ")
                .append("anlam gerçekten belirsizse kısaca sor. ")
                .append("Cevapların kısa ve net olsun (genelde 2-4 cümle); kullanıcı ayrıntı isterse uzat. ")
                .append("Cevapların sesli de okunabileceği için markdown işaretleri (*, #, tablo) kullanma; liste gerekirse 1) 2) diye sade yaz. ")
                .append("Matematik ifadelerini LaTeX kullanmadan düz yaz (ör. 3/4, x², √2, 2·5). ")
                .append("Telefonda arama yapmak, alarm kurmak, uygulama açmak gibi işleri henüz yapamazsın; istenirse bunu dürüstçe söyle. ")
                .append("Şu an: ").append(now).append(". ");
        if (!u.goals.isEmpty()) {
            s.append("Kullanıcının hedefleri: ").append(String.join("; ", u.goals)).append(". ")
                    .append("Bu hedeflerle ilgili konularda öğretici ol, adım adım anlat ve uygun yerde hedefine nasıl katkı sağladığını belirt. ");
        }
        return s.toString();
    }

    /**
     * Soru gönderir. history: önceki mesajlar (yeni soru hariç). jpeg: isteğe bağlı fotoğraf (3. adım).
     * Sonuç ana iş parçacığında döner.
     */
    public static void ask(User u, List<ChatStore.Msg> history, String text, byte[] jpeg, Callback cb) {
        ask(u, "", history, text, jpeg, cb);
    }

    /** extra: kişiliğe eklenecek o anki bilgi (ör. hedeflerin bugünkü durumu). */
    public static void ask(User u, String extra, List<ChatStore.Msg> history, String text, byte[] jpeg, Callback cb) {
        if (!EX.submit(() -> {
            String result = null, error = null;
            try {
                JSONObject body = buildBody(u, extra, history, text, jpeg);
                error = "Gemini'ye ulaşılamadı.";
                for (String model : u.modelsOrDefault()) {
                    Reply r = post(model, u.key, body.toString());
                    if (r.text != null) {
                        result = r.text;
                        error = null;
                        break;
                    }
                    error = r.error;
                    if (!r.tryNext) break;     // anahtar hatası gibi durumlarda diğer modelleri deneme
                }
            } catch (JSONException e) {
                error = "İstek hazırlanamadı: " + e.getMessage();
            }
            final String fr = result, fe = error;
            MAIN.post(() -> {
                if (fr != null) cb.ok(fr);
                else cb.err(fe);
            });
        })) MAIN.post(() -> cb.err("Bekleyen istekler dolu. Birazdan yeniden dene."));
    }

    private static JSONObject buildBody(User u, String extra, List<ChatStore.Msg> history, String text, byte[] jpeg) throws JSONException {
        JSONArray contents = new JSONArray();
        for (ChatStore.Msg m : history) {
            if (m.text == null || m.text.isEmpty()) continue;
            // eski fotoğraflar yeniden gönderilmez (hızlı ve ucuz kalsın); sadece fotoğraf gönderildiği bilinsin
            String t = m.img.isEmpty() ? m.text : "[Fotoğraf gönderdim] " + m.text;
            contents.put(new JSONObject()
                    .put("role", m.mine() ? "user" : "model")
                    .put("parts", new JSONArray().put(new JSONObject().put("text", t))));
        }
        JSONArray parts = new JSONArray();
        if (jpeg != null) {
            parts.put(new JSONObject().put("inline_data", new JSONObject()
                    .put("mime_type", "image/jpeg")
                    .put("data", Base64.encodeToString(jpeg, Base64.NO_WRAP))));
        }
        parts.put(new JSONObject().put("text", text));
        contents.put(new JSONObject().put("role", "user").put("parts", parts));
        return new JSONObject()
                .put("system_instruction", new JSONObject().put("parts",
                        new JSONArray().put(new JSONObject().put("text", persona(u) + (extra == null ? "" : extra)))))
                .put("contents", contents)
                .put("generationConfig", new JSONObject().put("temperature", 0.7));
    }

    private static final class Reply {
        String text, error;
        boolean tryNext;
    }

    private static Reply post(String model, String key, String json) {
        Reply r = new Reply();
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(BASE + model + ":generateContent").openConnection();
            c.setConnectTimeout(15000);
            c.setReadTimeout(60000);
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            c.setRequestProperty("x-goog-api-key", key);
            try (OutputStream o = c.getOutputStream()) {
                o.write(json.getBytes(StandardCharsets.UTF_8));
            }
            int code = c.getResponseCode();
            String resp = read(code >= 400 ? c.getErrorStream() : c.getInputStream());
            if (code == 200) {
                parse(resp, r);
                return r;
            }
            String msg = "";
            try {
                msg = new JSONObject(resp).getJSONObject("error").optString("message", "");
            } catch (JSONException ignored) {
            }
            String low = msg.toLowerCase(Locale.ROOT);
            if (code == 400 && (low.contains("api key") || low.contains("api_key"))) {
                r.error = "Gemini anahtarı geçersiz. Bilgisayarda bu kullanıcının anahtarını kontrol edip QR'ı yeniden okut.";
            } else if (code == 403) {
                r.error = "Gemini bu anahtara izin vermiyor (403). Anahtar kapatılmış ya da kısıtlanmış olabilir.";
            } else if (code == 429) {
                r.error = "Gemini kotası doldu (ücretsiz kullanım sınırı). Biraz bekleyip tekrar dene.";
                r.tryNext = true;
            } else if (code == 404) {
                r.error = "Model bulunamadı: " + model;
                r.tryNext = true;
            } else if (code >= 500) {
                r.error = "Gemini şu an yoğun ya da arızalı (" + code + "). Birazdan tekrar dene.";
                r.tryNext = true;
            } else {
                r.error = "Gemini hata verdi (" + code + ")" + (msg.isEmpty() ? "." : ": " + msg);
            }
        } catch (UnknownHostException e) {
            r.error = "İnternet bağlantısı yok gibi görünüyor.";
        } catch (SocketTimeoutException e) {
            r.error = "Gemini zamanında cevap vermedi. Tekrar dene.";
            r.tryNext = true;
        } catch (IOException e) {
            r.error = "Bağlantı hatası: " + e.getMessage();
        } finally {
            if (c != null) c.disconnect();
        }
        return r;
    }

    private static void parse(String resp, Reply r) {
        try {
            JSONObject o = new JSONObject(resp);
            JSONArray cands = o.optJSONArray("candidates");
            if (cands == null || cands.length() == 0) {
                JSONObject pf = o.optJSONObject("promptFeedback");
                r.error = (pf != null && pf.has("blockReason"))
                        ? "Bu soruya güvenlik filtresi yüzünden cevap veremiyorum."
                        : "Gemini boş cevap döndürdü.";
                return;
            }
            JSONObject cand = cands.getJSONObject(0);
            StringBuilder sb = new StringBuilder();
            JSONObject content = cand.optJSONObject("content");
            JSONArray parts = content == null ? null : content.optJSONArray("parts");
            if (parts != null) for (int i = 0; i < parts.length(); i++) {
                JSONObject p = parts.getJSONObject(i);
                if (p.optBoolean("thought", false)) continue;
                sb.append(p.optString("text", ""));
            }
            String t = sb.toString().trim();
            if (t.isEmpty()) {
                r.error = "SAFETY".equals(cand.optString("finishReason"))
                        ? "Bu soruya güvenlik filtresi yüzünden cevap veremiyorum."
                        : "Gemini boş cevap döndürdü.";
                return;
            }
            r.text = t;
        } catch (JSONException e) {
            r.error = "Gemini'nin cevabı okunamadı.";
        }
    }

    private static String read(InputStream in) throws IOException {
        if (in == null) return "";
        try (InputStream s = in) {
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = s.read(buf)) > 0) b.write(buf, 0, n);
            return b.toString("UTF-8");
        }
    }
}
