package jarvis;
import android.content.*;
import org.json.*;
import java.util.*;
import java.lang.reflect.*;
import javax.crypto.*;
public class KeyVaultHarness {
    static void require(boolean ok,String message) { if(!ok)throw new AssertionError(message); }
    static class Preferences implements SharedPreferences {
        final Map<String,String> values=new HashMap<>(); boolean fail;
        public String getString(String key,String fallback) { return values.getOrDefault(key,fallback); }
        public Editor edit() { return new Editor() {
            final Map<String,String> pending=new HashMap<>();
            public Editor putString(String key,String value) { pending.put(key,value);return this; }
            public boolean commit() { if(fail)return false;values.putAll(pending);return true; }
            public void apply() { commit(); }
        }; }
    }
    public static void main(String[] args) throws Exception {
        KeyGenerator generator=KeyGenerator.getInstance("AES");generator.init(256);
        SecretKey key=generator.generateKey();
        Field cached=KeyVault.class.getDeclaredField("cached");cached.setAccessible(true);cached.set(null,key);
        String secret="test-api-credential";
        String sealed=KeyVault.seal(secret,"hamdi",key);
        require(!sealed.contains(secret) && KeyVault.open(sealed,"hamdi",key).equals(secret),"round trip");
        require(!sealed.equals(KeyVault.seal(secret,"hamdi",key)),"IV reused");
        try { KeyVault.open(sealed,"other",key); throw new AssertionError("owner swap accepted"); }
        catch(java.security.GeneralSecurityException expected) {}
        try { KeyVault.open(sealed.substring(0,sealed.length()-4)+"AAAA","hamdi",key);throw new AssertionError("tampering accepted"); }
        catch(java.security.GeneralSecurityException expected) {}
        Preferences prefs=new Preferences();
        Context context=new Context() { public SharedPreferences getSharedPreferences(String name,int mode) { return prefs; } };
        User user=new User();user.name="hamdi";user.key=secret;
        prefs.values.put("users",new JSONArray().put(user.toJson()).toString());
        Store store=new Store(context);
        require(store.users().get(0).key.equals(secret),"legacy key unreadable");
        String encryptedRecord=new JSONArray(prefs.values.get("users")).getJSONObject(0).optString("k");
        require(encryptedRecord.startsWith(KeyVault.PREFIX) && !encryptedRecord.contains(secret),"legacy migration plaintext");
        require(new Store(context).users().get(0).key.equals(secret),"reload failed");
        JSONObject bad=user.toJson().put("k",KeyVault.PREFIX+"invalid");
        prefs.values.put("users",new JSONArray().put(bad).toString());
        User unreadable=store.users().get(0);require(unreadable.key.isEmpty(),"unreadable key used");
        unreadable.voice="new";store.update(unreadable);
        require(new JSONArray(prefs.values.get("users")).getJSONObject(0).optString("k").equals(KeyVault.PREFIX+"invalid"),"unreadable ciphertext discarded");
        String previous=prefs.values.get("users");cached.set(null,null);
        try { store.upsert(user);throw new AssertionError("no Keystore silently accepted"); }
        catch(IllegalStateException expected) {}
        require(prefs.values.get("users").equals(previous),"failed protection changed storage");
        cached.set(null,key);prefs.fail=true;
        try {store.upsert(user);throw new AssertionError("failed commit accepted");}
        catch(IllegalStateException expected) {}
        require(prefs.values.get("users").equals(previous),"failed commit changed storage");
        System.out.println("KeyVault migration, owner isolation, tamper, unreadable preservation and fail closed passed (JCE; Android Keystore substituted).");
    }
}
