package jarvis;

import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.Base64;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Encrypt persisted API credentials; never fall back to plaintext on failure. */
final class KeyVault {
    static final String PREFIX = "keystore:v1:";
    private static final String ALIAS = "jarvis-api-credentials-v1";
    private static SecretKey cached;

    private static synchronized SecretKey key() throws GeneralSecurityException {
        if (cached != null) return cached;
        try {
            KeyStore store = KeyStore.getInstance("AndroidKeyStore");
            store.load(null);
            if (store.containsAlias(ALIAS)) cached = (SecretKey)store.getKey(ALIAS, null);
            else {
                KeyGenerator generator = KeyGenerator.getInstance("AES", "AndroidKeyStore");
                generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                        KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
                cached = generator.generateKey();
            }
            if (cached == null) throw new GeneralSecurityException("Keystore key unavailable");
            return cached;
        } catch (java.io.IOException e) { throw new GeneralSecurityException(e); }
    }

    static String protect(String text, String owner) throws GeneralSecurityException {
        return seal(text, owner, key());
    }
    static String unprotect(String text, String owner) throws GeneralSecurityException {
        return open(text, owner, key());
    }
    static String seal(String text, String owner, SecretKey key) throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key);
        cipher.updateAAD(owner.getBytes(StandardCharsets.UTF_8));
        byte[] encrypted = cipher.doFinal(text.getBytes(StandardCharsets.UTF_8));
        return PREFIX + Base64.getEncoder().encodeToString(cipher.getIV()) + ":"
                + Base64.getEncoder().encodeToString(encrypted);
    }
    static String open(String text, String owner, SecretKey key) throws GeneralSecurityException {
        try {
            if (!text.startsWith(PREFIX)) throw new GeneralSecurityException("Unknown credential format");
            String[] parts = text.substring(PREFIX.length()).split(":", -1);
            if (parts.length != 2) throw new GeneralSecurityException("Invalid credential format");
            byte[] iv = Base64.getDecoder().decode(parts[0]);
            if (iv.length != 12) throw new GeneralSecurityException("Invalid credential IV");
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, iv));
            cipher.updateAAD(owner.getBytes(StandardCharsets.UTF_8));
            return new String(cipher.doFinal(Base64.getDecoder().decode(parts[1])), StandardCharsets.UTF_8);
        } catch (IllegalArgumentException e) { throw new GeneralSecurityException("Invalid credential encoding", e); }
    }
}
