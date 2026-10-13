package jarvis;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** Her kullanıcının sohbet geçmişi: uygulamanın kendi klasöründe chat_<ad>.json. */
public class ChatStore {
    public static final int MAX = 400;

    public static class Msg {
        public final String role;   // "user" | "model"
        public final String text;
        public final long ts;
        public final String img;    // fotoğraflı soruda telefondaki fotoğraf dosyası, yoksa ""

        public Msg(String role, String text, long ts) {
            this(role, text, ts, "");
        }

        public Msg(String role, String text, long ts, String img) {
            this.role = role;
            this.text = text;
            this.ts = ts;
            this.img = img == null ? "" : img;
        }

        public boolean mine() {
            return "user".equals(role);
        }
    }

    private final File file;
    private final List<Msg> list = new ArrayList<>();
    private static final java.util.Map<String, ChatStore> OPEN = new java.util.HashMap<>();

    /** Ekran ve arka plan servisi aynı geçmişi paylaşsın diye kullanıcı başına tek örnek. */
    public static synchronized ChatStore of(Context c, User u) {
        ChatStore s = OPEN.get(u.slug());
        if (s == null) {
            s = new ChatStore(c.getApplicationContext(), u);
            OPEN.put(u.slug(), s);
        }
        return s;
    }

    public static synchronized void forget(User u) {
        OPEN.remove(u.slug());
    }

    private ChatStore(Context c, User u) {
        file = new File(c.getFilesDir(), "chat_" + u.slug() + ".json");
        load();
    }

    private void load() {
        list.clear();
        if (!file.exists()) return;
        try (FileInputStream in = new FileInputStream(file)) {
            byte[] b = new byte[(int) file.length()];
            int off = 0;
            while (off < b.length) {
                int n = in.read(b, off, b.length - off);
                if (n < 0) break;
                off += n;
            }
            JSONArray a = new JSONArray(new String(b, 0, off, StandardCharsets.UTF_8));
            for (int i = 0; i < a.length(); i++) {
                JSONObject o = a.getJSONObject(i);
                list.add(new Msg(o.optString("r"), o.optString("t"), o.optLong("ts"), o.optString("i", "")));
            }
        } catch (IOException | JSONException ignored) {
            // bozuk dosya: boş geçmişle devam
        }
    }

    public synchronized List<Msg> all() {
        return new ArrayList<>(list);
    }

    /** Gemini'ye bağlam olarak gidecek son mesajlar. */
    public synchronized List<Msg> last(int n) {
        int from = Math.max(0, list.size() - n);
        return new ArrayList<>(list.subList(from, list.size()));
    }

    public synchronized void add(Msg m) {
        list.add(m);
        while (list.size() > MAX) dropImage(list.remove(0));
        save();
    }

    private static void dropImage(Msg m) {
        //noinspection ResultOfMethodCallIgnored
        if (!m.img.isEmpty()) new File(m.img).delete();
    }

    public synchronized void clear() {
        for (Msg m : list) dropImage(m);
        list.clear();
        save();
    }

    private void save() {
        JSONArray a = new JSONArray();
        try {
            for (Msg m : list) {
                JSONObject o = new JSONObject();
                o.put("r", m.role);
                o.put("t", m.text);
                o.put("ts", m.ts);
                if (!m.img.isEmpty()) o.put("i", m.img);
                a.put(o);
            }
        } catch (JSONException ignored) {
        }
        File tmp = new File(file.getPath() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(tmp)) {
            out.write(a.toString().getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            return;
        }
        if (!tmp.renameTo(file)) {
            //noinspection ResultOfMethodCallIgnored
            file.delete();
            //noinspection ResultOfMethodCallIgnored
            tmp.renameTo(file);
        }
    }

    public void deleteFile() {
        synchronized (this) {
            for (Msg m : list) dropImage(m);
        }
        //noinspection ResultOfMethodCallIgnored
        file.delete();
    }
}
