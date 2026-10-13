package jarvis;

import android.app.Notification;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.AudioManager;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

import com.hamdi.jarvis.R;

import org.vosk.Model;
import org.vosk.Recognizer;
import org.vosk.android.RecognitionListener;
import org.vosk.android.SpeechService;

import java.util.List;

/**
 * Süreli uyandırma dinlemesi (ön plan servisi, ekran kilitliyken de çalışır):
 * Vosk ile internetsiz olarak uyandırma kelimesini bekler → bip → soruyu Google ses tanımayla dinler →
 * Gemini'ye sorar → cevabı sesli okur → tekrar beklemeye döner. Süre bitince kendiliğinden kapanır.
 */
public class WakeService extends Service {
    public static final String A_START = "jarvis.UYANDIRMA_BASLA", A_STOP = "jarvis.UYANDIRMA_DUR",
            A_MORE = "jarvis.UYANDIRMA_UZAT", A_ASK = "jarvis.UYANDIRMA_SOR";
    public static final String EXTRA_MIN = "dakika";
    private static final int NOTE_ID = 1;

    /** Uygulama içinden erişim (aynı süreç). */
    static volatile WakeService instance;
    /** Servis sohbete mesaj ekleyince ekranı yenilemek için (ekran açıksa). */
    static volatile Runnable onChat;
    /** Durum değişince ekrandaki göstergeyi yenilemek için. */
    static volatile Runnable onState;
    /** Dinleme bir hata yüzünden kapandıysa açıklaması (ekran gösterip temizler). */
    static volatile String lastError;

    private final Handler h = new Handler(Looper.getMainLooper());
    private User user;
    private Model model;
    private SpeechService ss;
    private Ear ear;
    private Speaker speaker;
    private PowerManager.WakeLock wl;
    private volatile long endAt;
    private boolean handling;     // soru-cevap sürüyor
    private String lastHeard = "";   // bildirimde gösterilir: arka planda gerçekten duyuyor mu
    private int startFails;

    public static boolean running() {
        return instance != null;
    }

    public static long remainingMs() {
        WakeService service = instance;
        return service == null ? 0 : Math.max(0, service.endAt - System.currentTimeMillis());
    }

    public static void start(Context c, int minutes) {
        Intent i = new Intent(c, WakeService.class).setAction(A_START).putExtra(EXTRA_MIN, minutes);
        c.startForegroundService(i);
    }

    public static void stop(Context c) {
        WakeService service = instance;
        if (service != null) service.h.post(() -> {
            if (instance == service) service.shutdown();
        });
    }

    /** Dinlemeyi kim duraklattı ("tts", "mic", "test"). Adla tutulur: aynı şey iki kez duraklatıp bir kez bıraksa da takılmaz. */
    private static final WakeHolds HOLDS = new WakeHolds();

    /** Ekran mikrofonu/sesi kullanacakken dinlemeyi duraklat (kendi sesini duyup uyanmasın). */
    public static void pauseMic(String who) {
        HOLDS.add(who);
        WakeService service = instance;
        if (service != null) service.h.post(() -> {
            if (instance == service && paused()) service.stopVosk();
        });
    }

    public static void resumeMic(String who) {
        if (!HOLDS.remove(who)) return;
        WakeService service = instance;
        if (service != null) service.h.postDelayed(() -> {
            if (instance == service && !paused()) service.startVosk();
        }, 400);
    }

    public static boolean paused() {
        return HOLDS.paused();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent in, int flags, int startId) {
        String a = in == null ? A_START : in.getAction();
        if (A_STOP.equals(a)) {
            shutdown();
            return START_NOT_STICKY;
        }
        if (A_MORE.equals(a) && instance != null) {
            endAt += 30 * 60_000L;
            updateNote();
            return START_NOT_STICKY;
        }
        if (A_ASK.equals(a) && instance != null) {
            if (!handling) onWake();
            return START_NOT_STICKY;
        }
        // başlat
        int min = in == null ? 30 : in.getIntExtra(EXTRA_MIN, 30);
        endAt = System.currentTimeMillis() + min * 60_000L;
        user = new Store(this).active();
        Reminders.channels(this);
        Notification n = note();
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTE_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        else startForeground(NOTE_ID, n);
        if (user == null) {
            shutdown();
            return START_NOT_STICKY;
        }
        if (instance == null) {
            instance = this;
            speaker = new Speaker(this);
            speaker.setListener(new Speaker.Listener() {
                @Override
                public void onStart() {}

                @Override
                public void onDone() {
                    if (handling && !speaker.isSpeaking()) finishTurn();
                }
            });
            ear = new Ear(this);
            PowerManager pm = getSystemService(PowerManager.class);
            if (pm != null) {
                wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "jarvis:uyandirma");
                wl.acquire(min * 60_000L + 60_000L);
            }
            new Thread(() -> {
                try {
                    Model m = WakeModel.get(this);
                    h.post(() -> {
                        model = m;
                        startVosk();
                    });
                } catch (Throwable e) {     // yerel kütüphane yüklenemezse Error gelir, onu da yakala
                    lastError = "Uyandırma modeli yüklenemedi: " + e;
                    h.post(this::shutdown);
                }
            }).start();
            h.postDelayed(tick, 30_000);
        } else {
            if (wl != null) {
                if (wl.isHeld()) wl.release();
                wl.acquire(min * 60_000L + 60_000L);
            }
            updateNote();
        }
        if (onState != null) onState.run();
        return START_NOT_STICKY;
    }

    private final Runnable tick = new Runnable() {
        @Override
        public void run() {
            if (instance == null) return;
            if (System.currentTimeMillis() >= endAt) {
                shutdown();
                return;
            }
            updateNote();
            if (onState != null) onState.run();
            h.postDelayed(this, 30_000);
        }
    };

    // ------------------------------------------------------------------ uyandırma kelimesi
    private void startVosk() {
        if (instance != this || model == null || ss != null || handling || paused()) return;
        User fresh = new Store(this).find(user.slug());    // testte öğretilen benzer söylenişler hemen geçerli olsun
        if (fresh != null) user = fresh;
        try {
            Recognizer rec = new Recognizer(model, 16000f);
            ss = new SpeechService(rec, 16000f);
            startFails = 0;
            ss.startListening(new RecognitionListener() {
                @Override
                public void onPartialResult(String hyp) {
                    check(hyp);
                }

                @Override
                public void onResult(String hyp) {
                    check(hyp);
                    String t = WakeModel.text(hyp);
                    if (!t.isEmpty() && !handling) {
                        lastHeard = t.length() > 40 ? t.substring(0, 40) + "…" : t;
                        updateNote();
                    }
                }

                @Override
                public void onFinalResult(String hyp) {}

                @Override
                public void onError(Exception e) {
                    stopVosk();
                    h.postDelayed(WakeService.this::startVosk, 2000);
                }

                @Override
                public void onTimeout() {}
            });
        } catch (Throwable e) {
            ss = null;
            if (++startFails >= 3) {
                lastError = "Mikrofon dinlemesi başlatılamadı: " + e;
                shutdown();
                return;
            }
            h.postDelayed(this::startVosk, 3000);
        }
    }

    private void check(String json) {
        if (handling || user == null) return;
        if (WakeModel.matches(WakeModel.text(json), user)) onWake();
    }

    private void stopVosk() {
        if (ss != null) {
            try {
                ss.stop();
                ss.shutdown();
            } catch (Exception ignored) {
            }
            ss = null;
        }
    }

    // ------------------------------------------------------------------ soru-cevap
    private void onWake() {
        handling = true;
        stopVosk();
        speaker.stop();
        try {
            ToneGenerator tg = new ToneGenerator(AudioManager.STREAM_MUSIC, 80);
            tg.startTone(ToneGenerator.TONE_PROP_BEEP, 150);
            h.postDelayed(tg::release, 400);
        } catch (RuntimeException ignored) {
        }
        h.postDelayed(this::listenQuestion, 300);
        // güvenlik: bir şey takılırsa (ses motoru yok, ağ asılı kaldı) 90 sn sonra yeniden dinlemeye dön
        h.postDelayed(() -> {
            if (handling && (speaker == null || !speaker.isSpeaking())) finishTurn();
        }, 90_000);
    }

    private void listenQuestion() {
        if (instance == null) return;
        ear.start(new Ear.Listener() {
            @Override
            public void onReady() {}

            @Override
            public void onLevel(float rms) {}

            @Override
            public void onPartial(String text) {}

            @Override
            public void onResult(String text) {
                ask(text);
            }

            @Override
            public void onError(String message) {
                speaker.speak(user, "Anlayamadım. Tekrar sormak için beni yeniden çağır.");
            }
        });
    }

    private void ask(String text) {
        ChatStore chat = ChatStore.of(this, user);
        List<ChatStore.Msg> history = chat.last(20);
        chat.add(new ChatStore.Msg("user", "🎙 " + text, System.currentTimeMillis()));
        if (onChat != null) onChat.run();
        Goals goals = Goals.load(this, user);
        Gemini.ask(user, goals.contextForModel(), history, text, null, new Gemini.Callback() {
            @Override
            public void ok(String reply) {
                String clean = Goals.load(WakeService.this, user).applyMarks(reply);
                chat.add(new ChatStore.Msg("model", clean, System.currentTimeMillis()));
                if (onChat != null) onChat.run();
                speaker.speak(user, clean);
            }

            @Override
            public void err(String message) {
                speaker.speak(user, message);
            }
        });
    }

    private void finishTurn() {
        handling = false;
        h.postDelayed(this::startVosk, 300);
    }

    // ------------------------------------------------------------------ bildirim
    private Notification note() {
        PendingIntent open = PendingIntent.getActivity(this, 1, new Intent(this, MainActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        long left = Math.max(0, endAt - System.currentTimeMillis());
        String word = user == null ? "Jarvis" : user.wakeWord();
        return new Notification.Builder(this, Reminders.CH_WAKE)
                .setSmallIcon(R.drawable.ic_stat_jarvis)
                .setContentTitle("Dinliyorum · “" + word + "” de")
                .setContentText("Kalan süre: " + fmtLeft(left)
                        + (paused() ? " · duraklatıldı" : ""))
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setOngoing(true)
                .setColor(Ui.CYAN)
                .setContentIntent(open)
                .addAction(new Notification.Action.Builder(null, "Sor", action(A_ASK, 2)).build())
                .addAction(new Notification.Action.Builder(null, "+30 dk", action(A_MORE, 3)).build())
                .addAction(new Notification.Action.Builder(null, "Durdur", action(A_STOP, 4)).build())
                .build();
    }

    private PendingIntent action(String a, int code) {
        return PendingIntent.getService(this, code, new Intent(this, WakeService.class).setAction(a),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    public static String fmtLeft(long ms) {
        long m = (ms + 59_999) / 60_000;
        return m >= 60 ? (m / 60) + " sa " + (m % 60) + " dk" : m + " dk";
    }

    private void updateNote() {
        NotificationManager nm = getSystemService(NotificationManager.class);
        try {
            if (nm != null) nm.notify(NOTE_ID, note());
        } catch (SecurityException ignored) {
        }
    }

    private void shutdown() {
        h.removeCallbacksAndMessages(null);
        stopVosk();
        if (ear != null) ear.stop();
        if (speaker != null) speaker.shutdown();
        if (wl != null && wl.isHeld()) wl.release();
        instance = null;
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
        if (onState != null) onState.run();
    }

    @Override
    public void onDestroy() {
        if (instance == this) shutdown();
        super.onDestroy();
    }
}
