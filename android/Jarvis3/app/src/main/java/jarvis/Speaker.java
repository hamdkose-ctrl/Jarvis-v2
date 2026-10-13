package jarvis;

import android.content.Context;
import android.os.Bundle;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/** Cevapları telefonun Türkçe sesiyle okur. Ses ve hız kullanıcı başına seçilir. */
public class Speaker {
    public interface Listener {
        void onStart();

        void onDone();
    }

    private static final Locale TR = new Locale("tr", "TR");
    private TextToSpeech tts;
    private boolean ready, hasTurkish;
    private Listener listener;
    private String pendingText;
    private User pendingUser;

    public Speaker(Context c) {
        tts = new TextToSpeech(c.getApplicationContext(), status -> {
            if (status != TextToSpeech.SUCCESS) return;
            int r = tts.setLanguage(TR);
            hasTurkish = r != TextToSpeech.LANG_MISSING_DATA && r != TextToSpeech.LANG_NOT_SUPPORTED;
            ready = true;
            if (pendingText != null) {
                speak(pendingUser, pendingText);
                pendingText = null;
            }
        });
        tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
            @Override
            public void onStart(String id) {
                if (listener != null) Ui.MAIN.post(() -> listener.onStart());
            }

            @Override
            public void onDone(String id) {
                if (listener != null) Ui.MAIN.post(() -> listener.onDone());
            }

            @Override
            @SuppressWarnings("deprecation")
            public void onError(String id) {
                if (listener != null) Ui.MAIN.post(() -> listener.onDone());
            }

            @Override
            public void onStop(String id, boolean interrupted) {
                if (listener != null) Ui.MAIN.post(() -> listener.onDone());
            }
        });
    }

    public void setListener(Listener l) {
        listener = l;
    }

    public boolean isReady() {
        return ready;
    }

    public boolean hasTurkish() {
        return hasTurkish;
    }

    /** Telefondaki Türkçe sesler (ada göre sıralı). İnternet isteyenler sona. */
    public List<Voice> turkishVoices() {
        List<Voice> out = new ArrayList<>();
        if (!ready) return out;
        try {
            for (Voice v : tts.getVoices()) {
                Locale l = v.getLocale();
                if (l != null && "tr".equals(l.getLanguage())) out.add(v);
            }
        } catch (Exception ignored) {   // bazı ses motorları burada hata fırlatabiliyor
        }
        Collections.sort(out, (a, b) -> {
            if (a.isNetworkConnectionRequired() != b.isNetworkConnectionRequired())
                return a.isNetworkConnectionRequired() ? 1 : -1;
            return a.getName().compareTo(b.getName());
        });
        return out;
    }

    public void speak(User u, String text) {
        if (text == null || text.trim().isEmpty()) return;
        if (!ready) {
            pendingText = text;
            pendingUser = u;
            return;
        }
        if (u != null && !u.voice.isEmpty()) {
            for (Voice v : turkishVoices()) {
                if (v.getName().equals(u.voice)) {
                    tts.setVoice(v);
                    break;
                }
            }
        } else {
            tts.setLanguage(TR);
        }
        tts.setSpeechRate(u != null ? u.rate : 0.95f);
        tts.setPitch(u != null ? u.pitch : 1f);
        String clean = forSpeech(text);
        // uzun cevapları cümle gruplarına böl (motorların karakter sınırı var)
        int max = Math.min(3500, TextToSpeech.getMaxSpeechInputLength() - 10);
        List<String> parts = split(clean, max);
        for (int i = 0; i < parts.size(); i++) {
            Bundle p = new Bundle();
            tts.speak(parts.get(i), i == 0 ? TextToSpeech.QUEUE_FLUSH : TextToSpeech.QUEUE_ADD, p,
                    i == parts.size() - 1 ? "son" : "p" + i);
        }
    }

    public void stop() {
        pendingText = null;
        if (ready) tts.stop();
    }

    public boolean isSpeaking() {
        return ready && tts.isSpeaking();
    }

    public void shutdown() {
        tts.shutdown();
    }

    /** Ekrandaki metni okunacak hale getirir: işaretler, emojiler, bağlantılar atılır. */
    static String forSpeech(String s) {
        String t = Ui.clean(s);
        t = t.replaceAll("https?://\\S+", "bağlantı");
        t = t.replaceAll("[\\p{So}\\p{Cn}\\x{1F000}-\\x{1FFFF}\\x{2600}-\\x{27BF}]", "");
        t = t.replace("•", "").replace("◆", "");
        return t.trim();
    }

    private static List<String> split(String s, int max) {
        List<String> out = new ArrayList<>();
        StringBuilder cur = new StringBuilder();
        for (String sent : s.split("(?<=[.!?…\\n])\\s+")) {
            if (cur.length() + sent.length() + 1 > max && cur.length() > 0) {
                out.add(cur.toString());
                cur.setLength(0);
            }
            if (sent.length() > max) {
                for (int i = 0; i < sent.length(); i += max) out.add(sent.substring(i, Math.min(sent.length(), i + max)));
                continue;
            }
            if (cur.length() > 0) cur.append(' ');
            cur.append(sent);
        }
        if (cur.length() > 0) out.add(cur.toString());
        return out;
    }
}
