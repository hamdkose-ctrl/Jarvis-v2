package jarvis;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** Telefondaki bir kullanıcı: PC'den QR ile gelir (ya da elle eklenir). */
public class User {
    public static final String[] DEFAULT_MODELS = {"gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-2.5-flash"};

    public String name = "";
    public String key = "";
    // Preserve an unreadable encrypted record when unrelated preferences change.
    String storedKey = "";
    public String assistant = "Jarvis";
    public final List<String> models = new ArrayList<>();
    public final List<String> goals = new ArrayList<>();   // PC'deki hedefler (5. adımda ölçülebilir hale gelecek)

    // ses tercihleri (yalnızca telefonda; QR yeniden okutulunca korunur)
    public String voice = "";          // boş = telefonun varsayılan Türkçe sesi
    public float rate = 0.95f;         // konuşma hızı
    public float pitch = 1.0f;         // ses tonu (düşük = daha kalın)
    public boolean speakAlways = false; // yazarak sorulunca da sesli cevap ver
    public String wake = "";           // uyandırma kelimesi (boşsa asistanın adı)
    public final List<String> wakeAlts = new ArrayList<>();   // test ekranında "bunu da kabul et" denenler
    public int wakeSens = 1;           // 0 = sıkı, 1 = normal, 2 = gevşek
    public int remindMin = 20 * 60;    // hedef hatırlatma saati (gün içindeki dakika), -1 = kapalı

    public String wakeWord() {
        return wake.trim().isEmpty() ? assistant : wake.trim();
    }

    /** QR ile güncellenirken telefonda seçilmiş ses ayarlarını korur. */
    public void keepPrefsFrom(User old) {
        if (old == null) return;
        voice = old.voice;
        rate = old.rate;
        pitch = old.pitch;
        speakAlways = old.speakAlways;
        wake = old.wake;
        wakeAlts.clear();
        wakeAlts.addAll(old.wakeAlts);
        wakeSens = old.wakeSens;
        remindMin = old.remindMin;
    }

    public String slug() {
        String s = name.toLowerCase(new java.util.Locale("tr", "TR"))
                .replace('ç', 'c').replace('ğ', 'g').replace('ı', 'i').replace('ö', 'o')
                .replace('ş', 's').replace('ü', 'u');
        s = s.replaceAll("[^a-z0-9]", "");
        return s.isEmpty() ? "kullanici" : s;
    }

    public List<String> modelsOrDefault() {
        List<String> out = new ArrayList<>(models);
        if (out.isEmpty()) for (String m : DEFAULT_MODELS) out.add(m);
        // son çare olarak her zaman bilinen kararlı bir model dene
        if (!out.contains("gemini-2.5-flash")) out.add("gemini-2.5-flash");
        return out;
    }

    public JSONObject toJson() throws JSONException {
        JSONObject o = new JSONObject();
        o.put("n", name);
        o.put("k", key);
        o.put("a", assistant);
        o.put("m", new JSONArray(models));
        o.put("g", new JSONArray(goals));
        o.put("vo", voice);
        o.put("ra", (double) rate);
        o.put("pi", (double) pitch);
        o.put("sa", speakAlways);
        o.put("w", wake);
        o.put("wa", new JSONArray(wakeAlts));
        o.put("ws", wakeSens);
        o.put("rm", remindMin);
        return o;
    }

    public static User fromJson(JSONObject o) {
        User u = new User();
        u.name = o.optString("n", "").trim();
        u.key = o.optString("k", "").trim();
        String a = o.optString("a", "").trim();
        if (!a.isEmpty()) u.assistant = a;
        JSONArray m = o.optJSONArray("m");
        if (m != null) for (int i = 0; i < m.length(); i++) {
            String s = m.optString(i, "").trim();
            if (!s.isEmpty()) u.models.add(s);
        }
        JSONArray g = o.optJSONArray("g");
        if (g != null) for (int i = 0; i < g.length(); i++) {
            String s = g.optString(i, "").trim();
            if (!s.isEmpty()) u.goals.add(s);
        }
        u.voice = o.optString("vo", "");
        u.rate = (float) o.optDouble("ra", 0.95);
        u.pitch = (float) o.optDouble("pi", 1.0);
        u.speakAlways = o.optBoolean("sa", false);
        u.wake = o.optString("w", "");
        JSONArray wa = o.optJSONArray("wa");
        if (wa != null) for (int i = 0; i < wa.length(); i++) {
            String s = wa.optString(i, "").trim();
            if (!s.isEmpty()) u.wakeAlts.add(s);
        }
        u.wakeSens = o.optInt("ws", 1);
        u.remindMin = o.optInt("rm", 20 * 60);
        return u;
    }

    /** PC'deki "Android Jarvis uygulaması · kurulum" QR'ının içeriğini çözer. Hatalıysa açıklama fırlatır. */
    public static User fromQr(String raw) throws IllegalArgumentException {
        if (raw == null || raw.trim().isEmpty()) throw new IllegalArgumentException("QR boş okundu.");
        JSONObject o;
        try {
            o = new JSONObject(raw.trim());
        } catch (JSONException e) {
            throw new IllegalArgumentException("Bu bir Jarvis kurulum QR'ı değil. Bilgisayarda Telefon sayfasındaki “Kurulum QR’ını göster” kodunu okut.");
        }
        if (!"jarvis-android".equals(o.optString("j"))) {
            throw new IllegalArgumentException("Bu bir Jarvis kurulum QR'ı değil. Bilgisayarda Telefon sayfasındaki “Kurulum QR’ını göster” kodunu okut.");
        }
        User u = fromJson(o);
        if (u.name.isEmpty()) throw new IllegalArgumentException("QR'da kullanıcı adı yok.");
        if (u.key.isEmpty()) throw new IllegalArgumentException("QR'da Gemini anahtarı yok. Bilgisayarda bu kullanıcıya anahtar ekleyip yeniden dene.");
        return u;
    }
}
