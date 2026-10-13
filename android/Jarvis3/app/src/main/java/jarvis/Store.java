package jarvis;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** Kullanıcı listesi ve aktif kullanıcı (uygulamanın özel ayar dosyasında). */
public class Store {
    private static final Object LOCK = new Object();
    private final SharedPreferences sp;

    public Store(Context c) {
        sp = c.getSharedPreferences("jarvis", Context.MODE_PRIVATE);
    }

    public List<User> users() {
        synchronized (LOCK) { return readUsers(); }
    }

    private List<User> readUsers() {
        List<User> out = new ArrayList<>();
        boolean migrate = false;
        try {
            JSONArray a = new JSONArray(sp.getString("users", "[]"));
            for (int i = 0; i < a.length(); i++) {
                User u = User.fromJson(a.getJSONObject(i));
                u.storedKey = u.key;
                if (u.key.startsWith(KeyVault.PREFIX)) {
                    try { u.key = KeyVault.unprotect(u.key, u.slug()); }
                    catch (java.security.GeneralSecurityException e) { u.key = ""; }
                } else if (!u.key.isEmpty()) migrate = true;
                if (!u.name.isEmpty()) out.add(u);
            }
        } catch (JSONException ignored) {
            migrate = false; // Never replace a partially parsed user list.
        }
        // Preserve the original preferences if encryption/storage fails.
        if (migrate) {
            try { save(out); } catch (IllegalStateException ignored) {}
        }
        return out;
    }

    private void save(List<User> list) {
        JSONArray a = new JSONArray();
        try {
            for (User u : list) {
                JSONObject value = u.toJson();
                String sealed = u.key.isEmpty() && u.storedKey.startsWith(KeyVault.PREFIX)
                        ? u.storedKey : u.key.isEmpty() ? "" : KeyVault.protect(u.key, u.slug());
                value.put("k", sealed);
                a.put(value);
            }
        } catch (JSONException | java.security.GeneralSecurityException e) {
            throw new IllegalStateException("Anahtar güvenli kaydedilemedi; mevcut kayıt korundu.", e);
        }
        if (!sp.edit().putString("users", a.toString()).commit())
            throw new IllegalStateException("Kullanıcı kaydı yazılamadı.");
    }

    public User active() {
        List<User> list = users();
        if (list.isEmpty()) return null;
        String s = sp.getString("active", "");
        for (User u : list) if (u.slug().equals(s)) return u;
        return list.get(0);
    }

    public void setActive(User u) {
        sp.edit().putString("active", u.slug()).apply();
    }

    /** Aynı adlı kullanıcı varsa günceller. true = yeni eklendi. */
    public boolean upsert(User u) {
        synchronized (LOCK) { return upsertLocked(u); }
    }

    private boolean upsertLocked(User u) {
        List<User> list = users();
        for (int i = 0; i < list.size(); i++) {
            if (list.get(i).slug().equals(u.slug())) {
                list.set(i, u);
                save(list);
                return false;
            }
        }
        list.add(u);
        save(list);
        return true;
    }

    /** Ses ayarı gibi küçük değişiklikleri kaydeder. */
    public void update(User u) {
        synchronized (LOCK) { updateLocked(u); }
    }

    private void updateLocked(User u) {
        List<User> list = users();
        for (int i = 0; i < list.size(); i++) {
            if (list.get(i).slug().equals(u.slug())) {
                list.set(i, u);
                save(list);
                return;
            }
        }
    }

    public User find(String slug) {
        for (User u : users()) if (u.slug().equals(slug)) return u;
        return null;
    }

    public void remove(User u) {
        synchronized (LOCK) { removeLocked(u); }
    }

    private void removeLocked(User u) {
        List<User> list = users();
        List<User> keep = new ArrayList<>();
        for (User x : list) if (!x.slug().equals(u.slug())) keep.add(x);
        save(keep);
    }
}
