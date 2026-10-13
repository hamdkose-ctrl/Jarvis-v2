package jarvis;

import android.content.Context;
import android.util.AtomicFile;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.lang.ref.WeakReference;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Kullanıcının ölçülebilir hedefleri (en fazla 3) ve günlük kayıtları: goals_<ad>.json.
 * Kayıt üç yoldan gelir: kamerayla çözülen sorular (otomatik), hedef ekranından elle,
 * ya da sohbette "bugün 25 soru çözdüm" denince Jarvis'in cevabına eklediği [[KAYIT:...]] işaretinden.
 */
public class Goals {
    // Screens and late chat callbacks must share the current progress, rather
    // than save independent, stale snapshots over the same private app file.
    private static final Map<String, WeakReference<Goals>> OPEN = new LinkedHashMap<>();
    public static final int MAX = 3;
    public static final String[] UNITS = {"soru", "dakika", "kelime", "sayfa", "kez"};
    private static final Locale TR = new Locale("tr", "TR");
    private static final Pattern MARK = Pattern.compile("\\[\\[KAYIT:([a-z0-9]+):(-?[0-9]+(?:[.,][0-9]+)?)\\]\\]");

    public static class Goal {
        public String id = "";
        public String name = "";
        public String unit = "soru";
        public double daily = 10;        // günlük hedef
        public boolean photo = false;    // kamerayla çözülen her soru +1 sayılsın
    }

    public final List<Goal> goals = new ArrayList<>();
    /** tarih (yyyy-MM-dd) -> hedef id -> miktar */
    public final Map<String, Map<String, Double>> log = new LinkedHashMap<>();
    private final File file;

    private Goals(File f) {
        file = f;
    }

    public static Goals load(Context c, User u) {
        return loadFile(new File(c.getFilesDir(), "goals_" + u.slug() + ".json"));
    }

    static synchronized Goals loadFile(File file) {
        OPEN.entrySet().removeIf(e -> e.getValue().get() == null);
        String path = file.getAbsolutePath();
        WeakReference<Goals> ref = OPEN.get(path);
        Goals current = ref == null ? null : ref.get();
        if (current != null) return current;
        Goals g = readFile(file);
        OPEN.put(path, new WeakReference<>(g));
        return g;
    }

    private static Goals readFile(File file) {
        Goals g = new Goals(file);
        try (FileInputStream in = new AtomicFile(g.file).openRead()) {
            byte[] b = new byte[(int) g.file.length()];
            int off = 0;
            while (off < b.length) {
                int n = in.read(b, off, b.length - off);
                if (n < 0) break;
                off += n;
            }
            JSONObject o = new JSONObject(new String(b, 0, off, StandardCharsets.UTF_8));
            JSONArray a = o.optJSONArray("goals");
            if (a != null) for (int i = 0; i < a.length(); i++) {
                JSONObject j = a.getJSONObject(i);
                Goal x = new Goal();
                x.id = j.optString("id");
                x.name = j.optString("name");
                x.unit = j.optString("unit", "soru");
                x.daily = j.optDouble("daily", 10);
                x.photo = j.optBoolean("photo", false);
                if (!x.id.isEmpty()) g.goals.add(x);
            }
            JSONObject l = o.optJSONObject("log");
            if (l != null) {
                JSONArray days = l.names();
                if (days != null) for (int i = 0; i < days.length(); i++) {
                    String d = days.getString(i);
                    JSONObject e = l.getJSONObject(d);
                    Map<String, Double> m = new LinkedHashMap<>();
                    JSONArray ids = e.names();
                    if (ids != null) for (int k = 0; k < ids.length(); k++) m.put(ids.getString(k), e.getDouble(ids.getString(k)));
                    g.log.put(d, m);
                }
            }
        } catch (IOException | JSONException ignored) {
        }
        return g;
    }

    public synchronized void save() {
        AtomicFile target = new AtomicFile(file);
        FileOutputStream stream = null;
        try {
            JSONObject o = new JSONObject();
            JSONArray a = new JSONArray();
            for (Goal x : goals) {
                a.put(new JSONObject().put("id", x.id).put("name", x.name).put("unit", x.unit)
                        .put("daily", x.daily).put("photo", x.photo));
            }
            o.put("goals", a);
            JSONObject l = new JSONObject();
            String cutoff = day(-120);      // dört aydan eski kayıtları tutma
            for (Map.Entry<String, Map<String, Double>> e : log.entrySet()) {
                if (e.getKey().compareTo(cutoff) < 0) continue;
                l.put(e.getKey(), new JSONObject(e.getValue()));
            }
            o.put("log", l);
            stream = target.startWrite();
            stream.write(o.toString().getBytes(StandardCharsets.UTF_8));
            target.finishWrite(stream);
        } catch (IOException | JSONException ignored) {
            if (stream != null) target.failWrite(stream);
        }
    }

    public synchronized void deleteFile() {
        goals.clear();
        log.clear();
        new AtomicFile(file).delete();
    }

    // ------------------------------------------------------------------ tarih
    /** Bugünden offset gün sonrası/öncesi, yyyy-MM-dd. */
    public static String day(int offset) {
        Calendar c = Calendar.getInstance();
        c.add(Calendar.DAY_OF_YEAR, offset);
        return new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).format(c.getTime());
    }

    public static String dayLabel(int offset) {
        Calendar c = Calendar.getInstance();
        c.add(Calendar.DAY_OF_YEAR, offset);
        return new SimpleDateFormat("EEE", TR).format(c.getTime());
    }

    // ------------------------------------------------------------------ hedefler
    public synchronized Goal find(String id) {
        for (Goal g : goals) if (g.id.equals(id)) return g;
        return null;
    }

    public synchronized Goal add(String name, String unit, double daily, boolean photo) {
        Goal g = new Goal();
        g.id = "h" + java.util.UUID.randomUUID().toString().replace("-", "");
        g.name = name;
        g.unit = unit;
        g.daily = daily;
        g.photo = photo;
        goals.add(g);
        save();
        return g;
    }

    public synchronized void remove(Goal g) {
        goals.remove(g);
        for (Map<String, Double> m : log.values()) m.remove(g.id);
        save();
    }

    public synchronized double amount(String id, String day) {
        Map<String, Double> m = log.get(day);
        if (m == null) return 0;
        Double v = m.get(id);
        return v == null ? 0 : v;
    }

    public synchronized void addAmount(String id, double v) {
        if (find(id) == null || !Double.isFinite(v)) return;
        String d = day(0);
        Map<String, Double> m = log.get(d);
        if (m == null) {
            m = new LinkedHashMap<>();
            log.put(d, m);
        }
        double nv = Math.max(0, amount(id, d) + v);
        m.put(id, nv);
        save();
    }

    /** Bugünden geriye kaç gün üst üste hedefe ulaşılmış (bugün henüz tamamlanmadıysa dünden sayar). */
    public int streak(Goal g) {
        int n = 0;
        int start = amount(g.id, day(0)) >= g.daily ? 0 : -1;
        for (int i = start; i > -365; i--) {
            if (amount(g.id, day(i)) >= g.daily) n++;
            else break;
        }
        return n;
    }

    /** Son 7 günde hedefe ulaşılan gün sayısı. */
    public int hitDays(Goal g, int fromOffset) {
        int n = 0;
        for (int i = fromOffset; i > fromOffset - 7; i--) if (amount(g.id, day(i)) >= g.daily) n++;
        return n;
    }

    public static String fmt(double v) {
        return v == Math.floor(v) ? String.valueOf((long) v) : String.format(TR, "%.1f", v);
    }

    /** Kamerayla soru çözülünce: "fotoğraf sayılsın" işaretli hedeflere +1. Değişiklik olduysa true. */
    public synchronized boolean countPhoto() {
        boolean any = false;
        for (Goal g : goals) if (g.photo) {
            addAmount(g.id, 1);
            any = true;
        }
        return any;
    }

    // ------------------------------------------------------------------ Jarvis ile bağlantı
    /** Kişiliğe eklenecek: hedefler, bugünkü durum ve sohbetten kayıt alma kuralı. */
    public String contextForModel() {
        if (goals.isEmpty()) return "";
        StringBuilder s = new StringBuilder(" Kullanıcının ölçülebilir hedefleri ve bugünkü durumu: ");
        for (Goal g : goals) {
            s.append("[id=").append(g.id).append("] ").append(g.name).append(": günde ").append(fmt(g.daily)).append(' ')
                    .append(g.unit).append(", bugün ").append(fmt(amount(g.id, day(0)))).append(", son 7 günde ")
                    .append(hitDays(g, 0)).append("/7 gün tamam, seri ").append(streak(g)).append(" gün. ");
        }
        s.append("Kullanıcı bu hedeflerle ilgili bugün yaptığı bir miktarı söylerse (ör. 'bugün 25 soru çözdüm', '20 dakika İngilizce çalıştım'), ")
                .append("cevabının EN SONUNA ayrı satırda [[KAYIT:hedef_id:miktar]] yaz (miktar bugüne EKLENECEK sayı; ")
                .append("yanlış girildiyse düzeltmek için eksi sayı yazabilirsin). Emin değilsen sor, işaret koyma. ")
                .append("Bu işaret kullanıcıya gösterilmez; cevabında 'kaydettim' diyebilirsin. ")
                .append("Uygun anlarda hedeflerini hatırlat ve gerçekçi, dürüst geri bildirim ver; boş övgü yapma. ");
        return s.toString();
    }

    /** Cevaptaki [[KAYIT:...]] işaretlerini uygular ve metinden siler. */
    public synchronized String applyMarks(String reply) {
        if (reply == null) return "";
        Matcher m = MARK.matcher(reply);
        boolean any = false;
        while (m.find()) {
            Goal g = find(m.group(1));
            if (g == null) continue;
            try {
                double v = Double.parseDouble(m.group(2).replace(',', '.'));
                if (Math.abs(v) <= 100000) {
                    addAmount(g.id, v);
                    any = true;
                }
            } catch (NumberFormatException ignored) {
            }
        }
        if (any) save();
        return MARK.matcher(reply).replaceAll("").trim();
    }

    /** Haftalık analiz için modele gidecek istek: son 14 günün tablosu. */
    public String analysisPrompt(User u) {
        StringBuilder s = new StringBuilder("Haftalık hedef analizimi yap. Veriler (gün: miktar / günlük hedef):\n");
        for (Goal g : goals) {
            s.append("\nHedef: ").append(g.name).append(" (günde ").append(fmt(g.daily)).append(' ').append(g.unit).append(")\n");
            for (int i = -13; i <= 0; i++) {
                s.append(day(i)).append(' ').append(dayLabel(i)).append(": ").append(fmt(amount(g.id, day(i)))).append('\n');
            }
            s.append("Bu hafta ").append(hitDays(g, 0)).append("/7 gün, geçen hafta ").append(hitDays(g, -7))
                    .append("/7 gün hedefe ulaştı; seri ").append(streak(g)).append(" gün.\n");
        }
        s.append("\nŞunları yap: 1) Bu haftayı geçen haftayla kıyasla. 2) Neyin iyi gittiğini kısaca söyle. ")
                .append("3) Aksayan yerleri açık sözlü eleştir (hangi günler boş, düşüş var mı); yumuşatma ama kırıcı da olma. ")
                .append("4) Gelecek hafta için 2-3 somut, uygulanabilir öneri ver; hedef çok zor ya da çok kolaysa yeni günlük hedef öner. ")
                .append("En fazla 8-10 cümle, sade Türkçe.");
        return s.toString();
    }

    /** Hedefin bugün henüz tamamlanmadığı kısa özet (hatırlatma bildirimi için); hepsi tamamsa boş. */
    public String remaining() {
        StringBuilder s = new StringBuilder();
        for (Goal g : goals) {
            double left = g.daily - amount(g.id, day(0));
            if (left > 0) {
                if (s.length() > 0) s.append(" · ");
                s.append(g.name).append(": ").append(fmt(left)).append(' ').append(g.unit).append(" kaldı");
            }
        }
        return s.toString();
    }
}
