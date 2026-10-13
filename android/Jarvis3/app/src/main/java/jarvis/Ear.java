package jarvis;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;

import java.util.ArrayList;

/** Mikrofonla tek bir soru dinler (Google'ın Türkçe ses tanıması). Bas-konuş değil: bir kez dokun, konuş, susunca biter. */
public class Ear {
    public interface Listener {
        void onReady();

        void onLevel(float rms);

        void onPartial(String text);

        void onResult(String text);

        void onError(String message);
    }

    private final Context ctx;
    private SpeechRecognizer sr;
    private boolean active;

    public Ear(Context c) {
        ctx = c;
    }

    public static boolean available(Context c) {
        return SpeechRecognizer.isRecognitionAvailable(c);
    }

    public boolean isActive() {
        return active;
    }

    public void start(Listener l) {
        stop();
        sr = SpeechRecognizer.createSpeechRecognizer(ctx);
        active = true;
        sr.setRecognitionListener(new RecognitionListener() {
            @Override
            public void onReadyForSpeech(Bundle b) {
                l.onReady();
            }

            @Override
            public void onBeginningOfSpeech() {}

            @Override
            public void onRmsChanged(float rms) {
                l.onLevel(rms);
            }

            @Override
            public void onBufferReceived(byte[] buffer) {}

            @Override
            public void onEndOfSpeech() {}

            @Override
            public void onError(int error) {
                if (!active) return;
                active = false;
                l.onError(describe(error));
            }

            @Override
            public void onResults(Bundle b) {
                if (!active) return;
                active = false;
                ArrayList<String> r = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                String t = r == null || r.isEmpty() ? "" : r.get(0).trim();
                if (t.isEmpty()) l.onError("Seni anlayamadım, tekrar söyler misin?");
                else l.onResult(t);
            }

            @Override
            public void onPartialResults(Bundle b) {
                ArrayList<String> r = b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                if (r != null && !r.isEmpty()) l.onPartial(r.get(0));
            }

            @Override
            public void onEvent(int type, Bundle b) {}
        });
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "tr-TR");
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, "tr-TR");
        i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
        i.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        // konuşma bitince hemen kesmesin; düşünerek konuşana biraz pay bırak
        i.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1800L);
        i.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 1500L);
        sr.startListening(i);
    }

    /** Dinlemeyi bitirir; o ana kadar söyleneni sonuç olarak verir. */
    public void finish() {
        if (sr != null && active) sr.stopListening();
    }

    public void stop() {
        active = false;
        if (sr != null) {
            try {
                sr.cancel();
                sr.destroy();
            } catch (Exception ignored) {
            }
            sr = null;
        }
    }

    private static String describe(int e) {
        switch (e) {
            case SpeechRecognizer.ERROR_NO_MATCH:
            case SpeechRecognizer.ERROR_SPEECH_TIMEOUT:
                return "Seni duyamadım ya da anlayamadım. Tekrar dener misin?";
            case SpeechRecognizer.ERROR_NETWORK:
            case SpeechRecognizer.ERROR_NETWORK_TIMEOUT:
            case SpeechRecognizer.ERROR_SERVER:
                return "Ses tanıma için internet gerekiyor; bağlantı yok gibi.";
            case SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS:
                return "Mikrofon izni verilmemiş.";
            case SpeechRecognizer.ERROR_RECOGNIZER_BUSY:
                return "Ses tanıma meşgul, bir saniye sonra tekrar dene.";
            case SpeechRecognizer.ERROR_AUDIO:
                return "Mikrofon açılamadı. Başka bir uygulama kullanıyor olabilir.";
            default:
                return "Ses tanıma hatası (" + e + "). Tekrar dene.";
        }
    }
}
