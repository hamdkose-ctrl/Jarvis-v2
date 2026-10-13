package jarvis;

import android.Manifest;
import android.app.Activity;
import android.app.DownloadManager;
import android.app.TimePickerDialog;
import android.content.ClipData;
import android.app.Dialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.provider.MediaStore;
import android.content.pm.PackageManager;
import android.speech.tts.Voice;
import android.graphics.Insets;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowInsets;
import android.view.inputmethod.EditorInfo;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;
import com.google.mlkit.vision.barcode.BarcodeScanner;
import com.google.mlkit.vision.barcode.BarcodeScannerOptions;
import com.google.mlkit.vision.barcode.BarcodeScanning;
import com.google.mlkit.vision.common.InputImage;

import org.vosk.Recognizer;
import org.vosk.android.RecognitionListener;
import org.vosk.android.SpeechService;
import com.hamdi.jarvis.R;

import androidx.core.content.FileProvider;

import java.io.File;
import java.util.ArrayList;

import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** Ana ekran: üstte JARVIS çemberi, ortada sohbet, altta yazı kutusu; soldan açılan menüde kullanıcılar. */
public class MainActivity extends Activity {
    private static final int SHOW_LAST = 150;      // ekranda gösterilen en fazla mesaj
    private static final int CONTEXT_MSGS = 20;    // Gemini'ye bağlam olarak giden son mesaj sayısı
    private static final Locale TR = new Locale("tr", "TR");

    private final Handler h = new Handler(Looper.getMainLooper());
    private Store store;
    private User user;
    private ChatStore chat;

    private FrameLayout root;
    private LinearLayout main, list, drawer, setup;
    private FrameLayout scrim;
    private ScrollView scroll;
    private ReactorView reactor;
    private TextView status, userChip, userAvatar;
    private EditText input;
    private ImageView sendBtn, micBtn;
    private View typing;
    private boolean busy;
    private long lastDay = -1;
    private Speaker speaker;
    private Ear ear;
    private static final int REQ_MIC = 7, REQ_NOTIF = 8, REQ_CAM = 11, REQ_GAL = 12, REQ_SEND = 13, REQ_MODEL = 14;
    private static final String MODEL_PAGE = "https://huggingface.co/rhasspy/vosk-models/resolve/main/tr/vosk-model-small-tr-0.3.zip";
    private Runnable afterModel;         // model dosyadan yüklenince yapılacak iş
    private static final String TAILSCALE = "com.tailscale.ipn";

    private Runnable afterMic;           // mikrofon izni verilince yapılacak iş
    private boolean micHeld, ttsHeld;    // uyandırma servisini kendi sesimiz/mikrofonumuz için duraklattık mı
    private ScrollView goalsView;
    private TextView goalLine;
    private SpeechService testSs;

    // fotoğraflı soru (3. adım)
    private byte[] pendingImg;
    private boolean stepMode = true;
    private LinearLayout attachBar;
    private ImageView attachThumb;
    private TextView chipStep, chipAns;
    private Uri camUri;
    private boolean qrPhoto;     // kamera, QR fotoğrafı için mi açıldı

    // ------------------------------------------------------------------ yaşam döngüsü
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        store = new Store(this);
        if (b != null && b.getString("camUri") != null) camUri = Uri.parse(b.getString("camUri"));
        if (Build.VERSION.SDK_INT >= 30) getWindow().setDecorFitsSystemWindows(false);
        speaker = new Speaker(this);
        ear = new Ear(this);
        buildUi();
        setContentView(root);
        speaker.setListener(new Speaker.Listener() {
            @Override
            public void onStart() {
                if (!ttsHeld) {
                    ttsHeld = true;
                    WakeService.pauseMic("tts");     // kendi sesimizi duyup uyanmasın
                }
                if (ear.isActive()) return;
                reactor.setState(ReactorView.SPEAK);
                status.setTextColor(Ui.CYAN);
                status.setText("KONUŞUYOR · SUSTURMAK İÇİN ÇEMBERE DOKUN");
            }

            @Override
            public void onDone() {
                // bazı telefonlarda "konuşuyor" bilgisi bir an geç düşer: kısa bekleyip öyle bak
                h.postDelayed(() -> {
                    if (speaker.isSpeaking()) return;
                    if (ttsHeld) {
                        ttsHeld = false;
                        WakeService.resumeMic("tts");
                    }
                    if (!busy && !ear.isActive()) setIdle();
                }, 350);
            }
        });
        Reminders.channels(this);
        Reminders.scheduleAll(this);
        WakeService.onChat = () -> runOnUiThread(() -> {
            if (chat != null && !busy) renderChat();
            refreshGoalLine();
        });
        WakeService.onState = () -> runOnUiThread(() -> {
            if (!busy && !ear.isActive() && !speaker.isSpeaking()) setIdle();
            String err = WakeService.lastError;
            if (err != null) {
                WakeService.lastError = null;
                JDialog.info(this, "Uyandırma durdu", err);
            }
        });
        refreshUser();
        handleIntent(getIntent());
    }

    @Override
    protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        setIntent(i);
        handleIntent(i);
    }

    /** Bildirimden açılınca: doğru kullanıcıya geç, pazar bildirimiyse haftalık analizi başlat. */
    private void handleIntent(Intent i) {
        if (i == null) return;
        String slug = i.getStringExtra(Reminders.EXTRA_USER);
        boolean analyze = i.getBooleanExtra(Reminders.EXTRA_ANALYZE, false);
        i.removeExtra(Reminders.EXTRA_USER);
        i.removeExtra(Reminders.EXTRA_ANALYZE);
        if (slug != null) {
            User u = store.find(slug);
            if (u != null && (user == null || !u.slug().equals(user.slug()))) switchTo(u);
        }
        if (analyze) h.postDelayed(this::runAnalysis, 700);
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (camUri != null) out.putString("camUri", camUri.toString());   // kamera açıkken uygulama kapanırsa
    }

    @Override
    protected void onPause() {
        super.onPause();
        if (ear.isActive()) {
            ear.stop();
            micOff();
            if (!busy) setIdle();
        }
    }

    @Override
    protected void onDestroy() {
        WakeService.onChat = null;
        WakeService.onState = null;
        stopTest();
        WakeService.resumeMic("mic");
        WakeService.resumeMic("tts");
        WakeService.resumeMic("test");
        ear.stop();
        speaker.shutdown();
        super.onDestroy();
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (scrim.getVisibility() == View.VISIBLE) closeDrawer();
        else if (goalsView != null) closeGoals();
        else super.onBackPressed();
    }

    // ------------------------------------------------------------------ ekran
    private int dp(float v) {
        return Ui.dp(this, v);
    }

    private void buildUi() {
        root = new FrameLayout(this);
        root.setBackground(Ui.background());

        main = new LinearLayout(this);
        main.setOrientation(LinearLayout.VERTICAL);
        root.addView(main, new FrameLayout.LayoutParams(-1, -1));

        // PC ile aynı kullanıcı kartı ve kompakt sayfa geçişleri.
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(14), dp(10), dp(14), dp(8));
        userAvatar = Ui.text(this, "?", 18, Ui.WHITE);
        userAvatar.setGravity(Gravity.CENTER);
        userAvatar.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        userAvatar.setBackground(Ui.box(this, Ui.CYAN, 0, 24));
        userAvatar.setContentDescription("Kullanıcı Seç");
        userAvatar.setOnClickListener(v -> openDrawer());
        bar.addView(userAvatar, new LinearLayout.LayoutParams(dp(44), dp(44)));
        userChip = Ui.text(this, "Kullanıcı", 20, Ui.TEXT);
        userChip.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        userChip.setSingleLine(true);
        userChip.setEllipsize(android.text.TextUtils.TruncateAt.END);
        userChip.setPadding(dp(10), dp(10), dp(10), dp(10));
        userChip.setContentDescription("Kullanıcı Seç");
        userChip.setOnClickListener(v -> openDrawer());
        bar.addView(userChip, new LinearLayout.LayoutParams(0, dp(48), 1));
        status = Ui.text(this, "Hazır", 11, Ui.DIM);
        status.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        status.setMaxLines(2);
        status.setEllipsize(android.text.TextUtils.TruncateAt.END);
        status.setGravity(Gravity.CENTER_VERTICAL);
        status.setPadding(dp(4), dp(4), dp(8), dp(4));
        status.setMinHeight(dp(44));
        status.setContentDescription("Ses Durumu: Dinlemek veya Susturmak İçin Dokun");
        bar.addView(status, new LinearLayout.LayoutParams(0, -2, 1));
        ImageView menu = iconBtn(R.drawable.ic_menu, false);
        menu.setContentDescription("Ayarlar ve Araçlar");
        menu.setOnClickListener(v -> openDrawer());
        bar.addView(menu);
        main.addView(bar);
        LinearLayout nav = new LinearLayout(this);
        nav.setPadding(dp(14), 0, dp(14), dp(10));
        addNav(nav, "Sohbet", true, () -> { closeGoals(); closeDrawer(); scrollDown(); });
        addNav(nav, "Hedefler", false, this::showGoals);
        addNav(nav, "Dosyalar", false, () -> JDialog.menu(this, "Dosyalar",
                new String[]{"PC'ye Dosya Gönder", "PC'den Gelen Dosyalar"},
                k -> { if (k == 0) sendToPc(); else openDownloads(); }));
        addNav(nav, "Ayarlar", false, this::openDrawer);
        main.addView(nav);

        // Durum kullanıcı adının yanında; ayrı satır sohbete bırakıldı.
        reactor = new ReactorView(this);
        status.setOnClickListener(v -> {
            if (speaker.isSpeaking()) { speaker.stop(); setIdle(); }
            else toggleListen();
        });
        status.setOnLongClickListener(v -> { wakeMenu(); return true; });
        goalLine = Ui.text(this, "", 12, Ui.CYAN);
        goalLine.setTypeface(Ui.MONO);
        goalLine.setPadding(dp(12), 0, dp(12), dp(8));
        goalLine.setGravity(Gravity.CENTER);
        goalLine.setVisibility(View.GONE);
        goalLine.setOnClickListener(v -> showGoals());
        main.addView(goalLine);

        View line = new View(this);
        line.setBackgroundColor(Ui.LINE);
        main.addView(line, new LinearLayout.LayoutParams(-1, 1));

        // sohbet
        scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setVerticalScrollBarEnabled(false);
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        list.setPadding(dp(12), dp(10), dp(12), dp(10));
        scroll.addView(list, new ScrollView.LayoutParams(-1, -2));
        main.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));

        main.addView(buildInputBar());

        // soldan açılan menü
        scrim = new FrameLayout(this);
        scrim.setBackgroundColor(0x99000000);
        scrim.setVisibility(View.GONE);
        scrim.setOnClickListener(v -> closeDrawer());
        ScrollView ds = new ScrollView(this);
        ds.setBackground(Ui.box(this, Ui.PANEL, Ui.LINE, 0));
        ds.setClickable(true);
        drawer = new LinearLayout(this);
        drawer.setOrientation(LinearLayout.VERTICAL);
        ds.addView(drawer, new ScrollView.LayoutParams(-1, -2));
        scrim.addView(ds, new FrameLayout.LayoutParams(dp(296), -1, Gravity.START));
        root.addView(scrim, new FrameLayout.LayoutParams(-1, -1));

        // ilk kurulum ekranı
        setup = buildSetup();
        root.addView(setup, new FrameLayout.LayoutParams(-1, -1));

        root.setOnApplyWindowInsetsListener((v, ins) -> {
            int t = 0, btm = 0, l = 0, r = 0;
            if (Build.VERSION.SDK_INT >= 30) {
                Insets s = ins.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                Insets ime = ins.getInsets(WindowInsets.Type.ime());
                t = s.top;
                l = s.left;
                r = s.right;
                btm = Math.max(s.bottom, ime.bottom);
            }
            main.setPadding(l, t, r, btm);
            drawer.setPadding(dp(16) + l, dp(18) + t, dp(16), dp(18) + btm);
            setup.setPadding(dp(28) + l, t, dp(28) + r, btm);
            if (btm > 0) scrollDown();
            return ins;
        });
    }

    private void addNav(LinearLayout nav, String label, boolean active, Runnable action) {
        TextView button = Ui.text(this, label, 12.5f, active ? 0xFF96610D : Ui.DIM);
        button.setGravity(Gravity.CENTER);
        button.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);
        button.setMinHeight(dp(44));
        button.setPadding(dp(3), dp(8), dp(3), dp(8));
        button.setBackground(Ui.press(this, Ui.box(this, active ? 0xFFFFF5DB : Ui.PANEL,
                active ? Ui.GOLD : Ui.LINE, 12)));
        button.setContentDescription(label);
        button.setOnClickListener(v -> action.run());
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, -2, 1);
        lp.rightMargin = dp(4);
        nav.addView(button, lp);
    }

    private ImageView iconBtn(int res, boolean filled) {
        ImageView i = new ImageView(this);
        i.setImageResource(res);
        i.setColorFilter(filled ? Ui.WHITE : Ui.CYAN);
        i.setPadding(dp(11), dp(11), dp(11), dp(11));
        i.setBackground(Ui.press(this, Ui.box(this, filled ? Ui.CYAN : 0x1422D3EE, filled ? 0 : Ui.LINE, 24)));
        i.setLayoutParams(new LinearLayout.LayoutParams(dp(46), dp(46)));
        return i;
    }

    private View buildInputBar() {
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.BOTTOM);
        bar.setPadding(dp(10), dp(8), dp(10), dp(10));
        bar.setBackgroundColor(Ui.PANEL);

        ImageView cam = iconBtn(R.drawable.ic_cam, false);
        cam.setOnClickListener(v -> {
            if (user == null) return;
            JDialog.menu(this, "Fotoğrafla soru", new String[]{"📷   Fotoğraf çek", "🖼   Galeriden seç"},
                    k -> {
                        if (k == 0) takePhoto();
                        else pickPhoto();
                    });
        });
        bar.addView(cam);

        input = new EditText(this);
        input.setHint("Yaz…");
        input.setTextColor(Ui.TEXT);
        input.setHintTextColor(Ui.MUTED);
        input.setTextSize(16);
        input.setMaxLines(5);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE
                | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        input.setImeOptions(EditorInfo.IME_ACTION_SEND);
        input.setPadding(dp(14), dp(11), dp(14), dp(11));
        input.setBackground(Ui.box(this, Ui.BG, Ui.LINE, 22));
        LinearLayout.LayoutParams il = new LinearLayout.LayoutParams(0, -2, 1);
        il.leftMargin = dp(8);
        il.rightMargin = dp(8);
        bar.addView(input, il);
        input.setOnEditorActionListener((v, id, ev) -> {
            boolean enter = ev != null && ev.getKeyCode() == KeyEvent.KEYCODE_ENTER && ev.getAction() == KeyEvent.ACTION_DOWN;
            if (id == EditorInfo.IME_ACTION_SEND || enter) {
                send(false);
                return true;
            }
            return false;
        });

        sendBtn = iconBtn(R.drawable.ic_send, true);
        sendBtn.setOnClickListener(v -> send(false));
        micBtn = iconBtn(R.drawable.ic_mic, false);
        micBtn.setOnClickListener(v -> toggleListen());
        bar.addView(micBtn);
        bar.addView(sendBtn);
        sendBtn.setVisibility(View.GONE);
        input.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int a, int b, int c) {}

            @Override
            public void onTextChanged(CharSequence s, int a, int b, int c) {}

            @Override
            public void afterTextChanged(Editable s) {
                updateSendMic();
            }
        });

        // fotoğraf eklenince yazı kutusunun üstünde çıkan şerit
        attachBar = new LinearLayout(this);
        attachBar.setGravity(Gravity.CENTER_VERTICAL);
        attachBar.setPadding(dp(12), dp(8), dp(12), 0);
        attachBar.setBackgroundColor(Ui.PANEL);
        attachBar.setVisibility(View.GONE);
        attachThumb = new ImageView(this);
        attachThumb.setScaleType(ImageView.ScaleType.CENTER_CROP);
        attachThumb.setBackground(Ui.box(this, Ui.BG, Ui.LINE, 8));
        attachThumb.setClipToOutline(true);
        attachBar.addView(attachThumb, new LinearLayout.LayoutParams(dp(56), dp(56)));
        chipStep = chip("Adım adım anlat");
        chipAns = chip("Sadece cevap");
        chipStep.setOnClickListener(v -> {
            stepMode = true;
            paintChips();
        });
        chipAns.setOnClickListener(v -> {
            stepMode = false;
            paintChips();
        });
        LinearLayout.LayoutParams cl = new LinearLayout.LayoutParams(-2, -2);
        cl.leftMargin = dp(10);
        attachBar.addView(chipStep, cl);
        LinearLayout.LayoutParams cl2 = new LinearLayout.LayoutParams(-2, -2);
        cl2.leftMargin = dp(6);
        attachBar.addView(chipAns, cl2);
        View sp = new View(this);
        attachBar.addView(sp, new LinearLayout.LayoutParams(0, 1, 1));
        TextView x = Ui.text(this, "✕", 18, Ui.DIM);
        x.setPadding(dp(10), dp(6), dp(4), dp(6));
        x.setOnClickListener(v -> clearAttach());
        attachBar.addView(x);

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.addView(attachBar, new LinearLayout.LayoutParams(-1, -2));
        box.addView(bar, new LinearLayout.LayoutParams(-1, -2));
        return box;
    }

    private TextView chip(String s) {
        TextView t = Ui.text(this, s, 13, Ui.CYAN);
        t.setPadding(dp(10), dp(7), dp(10), dp(7));
        return t;
    }

    private void paintChips() {
        chipStep.setTextColor(stepMode ? Ui.BG : Ui.CYAN);
        chipStep.setBackground(Ui.press(this, Ui.box(this, stepMode ? Ui.CYAN : 0x1422D3EE, stepMode ? 0 : Ui.LINE, 16)));
        chipAns.setTextColor(!stepMode ? Ui.BG : Ui.CYAN);
        chipAns.setBackground(Ui.press(this, Ui.box(this, !stepMode ? Ui.CYAN : 0x1422D3EE, !stepMode ? 0 : Ui.LINE, 16)));
    }

    private void updateSendMic() {
        boolean has = (input.getText().toString().trim().length() > 0 || pendingImg != null) && !ear.isActive();
        sendBtn.setVisibility(has ? View.VISIBLE : View.GONE);
        micBtn.setVisibility(has ? View.GONE : View.VISIBLE);
    }

    private LinearLayout buildSetup() {
        LinearLayout s = new LinearLayout(this);
        s.setOrientation(LinearLayout.VERTICAL);
        s.setGravity(Gravity.CENTER);
        s.setBackgroundColor(Ui.BG);
        s.setClickable(true);
        ReactorView rv = new ReactorView(this);
        s.addView(rv, new LinearLayout.LayoutParams(dp(170), dp(170)));
        TextView t = Ui.text(this, "Jarvis", 24, Ui.CYAN);
        t.setTypeface(Ui.MONO_B);
        t.setLetterSpacing(0.3f);
        t.setPadding(0, dp(18), 0, dp(6));
        s.addView(t);
        TextView sub = Ui.text(this, "Kişisel asistanın · telefon", 13, Ui.DIM);
        sub.setTypeface(Ui.MONO);
        s.addView(sub);
        s.addView(Ui.gap(this, 26));
        TextView how = Ui.text(this,
                "Kurulum için bilgisayardaki Jarvis'te Telefon sayfasını aç, kullanıcını seçip "
                        + "“Kurulum QR’ını göster”e bas. Sonra aşağıdaki düğmeyle QR’ı okut.", 15, Ui.TEXT);
        how.setGravity(Gravity.CENTER);
        how.setLineSpacing(0, 1.2f);
        s.addView(how);
        s.addView(Ui.gap(this, 24));
        TextView qr = Ui.button(this, "QR ile kur", true);
        qr.setOnClickListener(v -> scanQr());
        s.addView(qr, new LinearLayout.LayoutParams(dp(240), -2));
        s.addView(Ui.gap(this, 12));
        TextView manual = Ui.text(this, "Anahtarım var, elle ekleyeceğim", 14, Ui.DIM);
        manual.setPadding(dp(12), dp(10), dp(12), dp(10));
        manual.setOnClickListener(v -> addManual());
        s.addView(manual);
        return s;
    }

    // ------------------------------------------------------------------ kullanıcı
    private void refreshUser() {
        user = store.active();
        if (user == null) {
            setup.setVisibility(View.VISIBLE);
            chat = null;
            return;
        }
        setup.setVisibility(View.GONE);
        chat = ChatStore.of(this, user);
        userChip.setText(user.name);
        userAvatar.setText(user.name.isEmpty() ? "?" : user.name.substring(0, 1).toUpperCase(TR));
        input.setHint(user.assistant + "'e yaz…");
        setIdle();
        renderChat();
        refreshGoalLine();
    }

    private void switchTo(User u) {
        if (WakeService.running()) {
            WakeService.stop(this);     // dinleme önceki kullanıcının kelimesi ve hesabıyla çalışıyordu
            toast("Uyandırma kapatıldı; " + u.name + " için yeniden başlatabilirsin.");
        }
        clearAttach();
        speaker.stop();
        ear.stop();
        micOff();
        store.setActive(u);
        busy = false;
        refreshUser();
    }

    private void scanQr() {
        GmsBarcodeScannerOptions o = new GmsBarcodeScannerOptions.Builder()
                .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
                .build();
        GmsBarcodeScanning.getClient(this, o).startScan()
                .addOnSuccessListener(code -> importQr(code.getRawValue()))
                .addOnFailureListener(e -> JDialog.confirm(this, "QR okuyucu açılamadı",
                        "Google'ın hazır QR okuyucusu bu telefonda açılmadı (" + e.getMessage() + ").\n\n"
                                + "Onun yerine QR'ın fotoğrafını çekelim, uygulama kendisi okusun. "
                                + "Fotoğrafta QR net ve ekranı dolduracak kadar büyük olsun.",
                        "Fotoğrafını çek", false, this::scanQrByPhoto));
    }

    /** Yedek yol: kamerayla QR'ın fotoğrafını çek, uygulamanın içindeki okuyucuyla çöz. */
    private void scanQrByPhoto() {
        qrPhoto = true;
        takePhoto();
    }

    private void decodeQrPhoto(Uri u) {
        try {
            InputImage img = InputImage.fromFilePath(this, u);
            BarcodeScanner sc = BarcodeScanning.getClient(new BarcodeScannerOptions.Builder()
                    .setBarcodeFormats(Barcode.FORMAT_QR_CODE).build());
            sc.process(img)
                    .addOnSuccessListener(list -> {
                        String raw = null;
                        for (Barcode b : list) if (b.getRawValue() != null) raw = b.getRawValue();
                        if (raw == null) JDialog.confirm(this, "QR bulunamadı",
                                "Fotoğrafta QR kod okunamadı. QR'a daha yakından, titretmeden çekip tekrar dene.",
                                "Tekrar çek", false, this::scanQrByPhoto);
                        else importQr(raw);
                    })
                    .addOnFailureListener(e -> JDialog.info(this, "QR okunamadı", String.valueOf(e.getMessage())));
        } catch (Exception e) {
            JDialog.info(this, "QR okunamadı", String.valueOf(e.getMessage()));
        }
    }

    private Boolean saveUser(User value) {
        try { return store.upsert(value); }
        catch (IllegalStateException e) {
            JDialog.info(this, "Kayıt yapılamadı", e.getMessage());
            return null;
        }
    }

    private boolean saveUserPrefs() {
        try { store.update(user); return true; }
        catch (IllegalStateException e) {
            refreshUser();
            JDialog.info(this, "Kayıt yapılamadı", e.getMessage());
            return false;
        }
    }

    private void importQr(String raw) {
        if (AndroidSetup.isSetupQr(raw)) {
            toast("Güvenli kurulum alınıyor…");
            AndroidSetup.fetch(raw, new AndroidSetup.Callback() {
                public void ok(User value) { importUser(value); }
                public void err(String message) { JDialog.info(MainActivity.this, "Kurulum tamamlanamadı", message); }
            });
            return;
        }
        try {
            importUser(User.fromQr(raw));
        } catch (IllegalArgumentException e) {
            JDialog.info(this, "QR okunamadı", e.getMessage());
        }
    }

    private void importUser(User u) {
            u.keepPrefsFrom(store.find(u.slug()));
            Boolean isNew = saveUser(u);
            if (isNew == null) return;
            store.setActive(u);
            refreshUser();
            toast(isNew ? u.name + " eklendi ✓" : u.name + " güncellendi ✓");
    }

    private void addManual() {
        JDialog.two(this, "Elle kullanıcı ekle",
                "Gemini anahtarını aistudio.google.com/apikey adresinden alabilirsin. QR ile kurmak daha kolaydır.",
                "Ad (örn. Ebru)", "Gemini API anahtarı (AIza…)", (n, k) -> {
                    if (n.isEmpty() || k.isEmpty()) {
                        JDialog.info(this, "Eksik bilgi", "Ad ve anahtarın ikisi de gerekli.");
                        return;
                    }
                    User u = new User();
                    u.name = n;
                    u.key = k;
                    if (saveUser(u) == null) return;
                    store.setActive(u);
                    refreshUser();
                });
    }

    private void deleteUser(User u) {
        JDialog.confirm(this, u.name + " silinsin mi?",
                "Kullanıcı ve sohbet geçmişi bu telefondan silinir. Bilgisayardaki profil etkilenmez.",
                "Sil", true, () -> {
                    try { store.remove(u); } catch (IllegalStateException e) {
                        JDialog.info(this, "Kayıt yapılamadı", e.getMessage());
                        return;
                    }
                    ChatStore.of(this, u).deleteFile();
                    ChatStore.forget(u);
                    Goals.load(this, u).deleteFile();
                    Reminders.cancel(this, u);
                    closeDrawer();
                    refreshUser();
                });
    }

    // ------------------------------------------------------------------ menü
    private void openDrawer() {
        fillDrawer();
        scrim.setVisibility(View.VISIBLE);
        View panel = scrim.getChildAt(0);
        panel.setTranslationX(-dp(300));
        panel.animate().translationX(0).setDuration(200).start();
        scrim.setAlpha(0f);
        scrim.animate().alpha(1f).setDuration(200).start();
    }

    private void closeDrawer() {
        View panel = scrim.getChildAt(0);
        panel.animate().translationX(-dp(300)).setDuration(180).start();
        scrim.animate().alpha(0f).setDuration(180).withEndAction(() -> scrim.setVisibility(View.GONE)).start();
    }

    private void section(String s) {
        TextView t = Ui.text(this, s, 11, Ui.MUTED);
        t.setTypeface(Ui.MONO);
        t.setLetterSpacing(0.2f);
        t.setPadding(dp(4), dp(18), 0, dp(6));
        drawer.addView(t);
    }

    private TextView row(String s, int color) {
        TextView t = Ui.text(this, s, 15, color);
        t.setPadding(dp(12), dp(12), dp(12), dp(12));
        t.setBackground(Ui.press(this, Ui.box(this, 0, 0, 10)));
        drawer.addView(t, new LinearLayout.LayoutParams(-1, -2));
        return t;
    }

    private void fillDrawer() {
        drawer.removeAllViews();
        TextView t = Ui.text(this, "Jarvis", 18, Ui.CYAN);
        t.setTypeface(Ui.MONO_B);
        t.setLetterSpacing(0.25f);
        drawer.addView(t);
        TextView sub = Ui.text(this, "Komut Merkezi · telefon", 12, Ui.DIM);
        sub.setTypeface(Ui.MONO);
        drawer.addView(sub);

        section("KULLANICILAR");
        for (User u : store.users()) {
            boolean on = user != null && u.slug().equals(user.slug());
            TextView r = row((on ? "●  " : "○  ") + u.name, on ? Ui.CYAN : Ui.TEXT);
            if (on) r.setBackground(Ui.press(this, Ui.box(this, 0x1422D3EE, Ui.LINE, 10)));
            r.setOnClickListener(v -> {
                closeDrawer();
                if (!on) switchTo(u);
            });
            r.setOnLongClickListener(v -> {
                deleteUser(u);
                return true;
            });
        }
        row("＋  QR ile kullanıcı ekle", Ui.CYAN).setOnClickListener(v -> {
            closeDrawer();
            scanQr();
        });
        row("＋  Elle ekle", Ui.DIM).setOnClickListener(v -> {
            closeDrawer();
            addManual();
        });
        TextView hint = Ui.text(this, "Silmek için kullanıcının üstüne basılı tut.", 11, Ui.MUTED);
        hint.setPadding(dp(12), dp(2), 0, 0);
        drawer.addView(hint);

        if (user != null) {
            section("SOHBET");
            row("Sohbeti temizle", Ui.TEXT).setOnClickListener(v -> JDialog.confirm(this, "Sohbet temizlensin mi?",
                    user.name + " kullanıcısının bu telefondaki tüm sohbet geçmişi silinir.", "Temizle", true, () -> {
                        chat.clear();
                        closeDrawer();
                        renderChat();
                    }));
            section("HEDEFLER");
            row("◆  Hedefler ve ilerleme", Ui.CYAN).setOnClickListener(v -> {
                closeDrawer();
                showGoals();
            });
            row("📊  Haftalık analiz yap", Ui.TEXT).setOnClickListener(v -> {
                closeDrawer();
                runAnalysis();
            });
        }

        if (user != null) fillWakeSection();
        if (user != null) fillVoiceSection();

        section("DOSYALAR");
        row("⇪  PC'ye dosya gönder", Ui.TEXT).setOnClickListener(v -> {
            closeDrawer();
            sendToPc();
        });
        row("⇩  PC'den gelen dosyalar", Ui.TEXT).setOnClickListener(v -> {
            closeDrawer();
            openDownloads();
        });

        TextView v = Ui.text(this, "Jarvis · Mobil Arayüz" + (user != null ? " · " + user.modelsOrDefault().get(0) : ""), 11, Ui.MUTED);
        v.setTypeface(Ui.MONO);
        v.setPadding(dp(4), dp(24), 0, 0);
        drawer.addView(v);
    }

    // ------------------------------------------------------------------ durum
    private void setIdle() {
        reactor.setState(ReactorView.IDLE);
        if (WakeService.running() && user != null) {
            status.setTextColor(Ui.GOOD);
            status.setText("“" + user.wakeWord().toUpperCase(TR) + "” DE · " + WakeService.fmtLeft(WakeService.remainingMs()).toUpperCase(TR));
        } else {
            status.setTextColor(Ui.DIM);
            status.setText("ÇEVRİMİÇİ · " + (user != null ? user.assistant.toUpperCase(TR) : "JARVIS"));
        }
    }

    private void setThinking() {
        reactor.setState(ReactorView.THINK);
        status.setTextColor(Ui.CYAN);
        status.setText("DÜŞÜNÜYOR…");
    }

    // ------------------------------------------------------------------ sohbet
    private void renderChat() {
        list.removeAllViews();
        lastDay = -1;
        typing = null;
        List<ChatStore.Msg> all = chat.all();
        if (all.isEmpty()) {
            addWelcome();
            return;
        }
        int from = Math.max(0, all.size() - SHOW_LAST);
        if (from > 0) addCenterNote("Daha eski " + from + " mesaj saklı");
        for (int i = from; i < all.size(); i++) addBubble(all.get(i));
        scrollDown();
    }

    private void addWelcome() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(16), dp(16), dp(16), dp(16));
        card.setBackground(Ui.box(this, Ui.PANEL, Ui.LINE, 14));
        TextView t = Ui.text(this, "Merhaba " + user.name + " 👋", 18, Ui.CYAN);
        t.setTypeface(Ui.MONO_B);
        card.addView(t);
        String g = user.goals.isEmpty() ? "" : "\n\nHedeflerini biliyorum: " + String.join(", ", user.goals) + ".";
        TextView b = Ui.text(this, "Ben " + user.assistant + ". Bana istediğini yazabilirsin; yazım hatalarını dert etme, anlarım."
                + g + "\n\nÖrnek: “yarın yağmur yağacak mı”, “bana 5 ingilizce kelime sor”, “kesirleri anlat”.", 15, Ui.TEXT);
        b.setLineSpacing(0, 1.2f);
        b.setPadding(0, dp(8), 0, 0);
        card.addView(b);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(12);
        list.addView(card, lp);
    }

    private void addCenterNote(String s) {
        TextView t = Ui.text(this, s, 11, Ui.MUTED);
        t.setTypeface(Ui.MONO);
        t.setGravity(Gravity.CENTER);
        t.setPadding(0, dp(10), 0, dp(4));
        list.addView(t, new LinearLayout.LayoutParams(-1, -2));
    }

    private static long dayOf(long ts) {
        Calendar c = Calendar.getInstance();
        c.setTimeInMillis(ts);
        return c.get(Calendar.YEAR) * 1000L + c.get(Calendar.DAY_OF_YEAR);
    }

    private void maybeDay(long ts) {
        long d = dayOf(ts);
        if (d == lastDay) return;
        lastDay = d;
        long today = dayOf(System.currentTimeMillis());
        long yest = dayOf(System.currentTimeMillis() - 86_400_000L);
        String label = d == today ? "BUGÜN" : d == yest ? "DÜN"
                : new SimpleDateFormat("d MMMM yyyy", TR).format(new Date(ts)).toUpperCase(TR);
        addCenterNote("— " + label + " —");
    }

    private void addBubble(ChatStore.Msg m) {
        maybeDay(m.ts);
        boolean mine = m.mine();
        LinearLayout wrap = new LinearLayout(this);
        wrap.setOrientation(LinearLayout.VERTICAL);
        wrap.setGravity(mine ? Gravity.END : Gravity.START);

        if (!m.img.isEmpty()) {
            Bitmap bm = Photo.thumb(m.img, 700);
            if (bm != null) {
                ImageView iv = new ImageView(this);
                iv.setImageBitmap(bm);
                iv.setAdjustViewBounds(true);
                iv.setMaxWidth((int) (getResources().getDisplayMetrics().widthPixels * 0.66f));
                iv.setMaxHeight(dp(260));
                iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
                iv.setBackground(Ui.box(this, Ui.BG, Ui.LINE, 12));
                iv.setClipToOutline(true);
                iv.setOnClickListener(v -> showFull(m.img));
                LinearLayout.LayoutParams il = new LinearLayout.LayoutParams(-2, -2);
                il.bottomMargin = dp(4);
                wrap.addView(iv, il);
            }
        }

        TextView b = Ui.text(this, mine ? m.text : Ui.clean(m.text), 15.5f, mine ? Ui.WHITE : Ui.TEXT);
        b.setTextIsSelectable(true);
        b.setLineSpacing(0, 1.15f);
        b.setMaxWidth((int) (getResources().getDisplayMetrics().widthPixels * 0.80f));
        b.setPadding(dp(10), dp(6), dp(10), dp(6));
        b.setIncludeFontPadding(false);
        b.setBackground(mine ? Ui.box(this, Ui.CYAN, 0, 16) : Ui.box(this, Ui.PANEL, Ui.LINE, 16));
        wrap.addView(b, new LinearLayout.LayoutParams(-2, -2));

        TextView time = Ui.text(this, (mine ? "" : user.assistant + " · ")
                + new SimpleDateFormat("HH:mm", TR).format(new Date(m.ts)), 10, Ui.MUTED);
        time.setTypeface(Ui.MONO);
        time.setPadding(dp(4), dp(3), dp(4), 0);
        wrap.addView(time);

        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(6);
        list.addView(wrap, lp);
    }

    private void addError(String msg, Runnable retry) {
        LinearLayout wrap = new LinearLayout(this);
        wrap.setOrientation(LinearLayout.VERTICAL);
        wrap.setPadding(dp(13), dp(10), dp(13), dp(10));
        wrap.setBackground(Ui.box(this, 0x1AFF5D73, Ui.BAD, 14));
        TextView t = Ui.text(this, "⚠ " + msg, 14.5f, Ui.BAD);
        t.setLineSpacing(0, 1.15f);
        wrap.addView(t);
        TextView again = Ui.text(this, "TEKRAR DENE", 12, Ui.CYAN);
        again.setTypeface(Ui.MONO_B);
        again.setPadding(0, dp(8), dp(8), 0);
        wrap.addView(again);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(6);
        list.addView(wrap, lp);
        again.setOnClickListener(v -> {
            if (busy) return;
            list.removeView(wrap);
            retry.run();
        });
    }

    private void showTyping() {
        TextView t = Ui.text(this, "●", 16, Ui.CYAN);
        t.setPadding(dp(14), dp(8), dp(14), dp(8));
        t.setBackground(Ui.box(this, Ui.PANEL, 0x2222D3EE, 14));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.topMargin = dp(8);
        list.addView(t, lp);
        typing = t;
        tickTyping(t, 0);
    }

    private void tickTyping(TextView t, int n) {
        if (typing != t) return;
        t.setText(n % 3 == 0 ? "●" : n % 3 == 1 ? "● ●" : "● ● ●");
        h.postDelayed(() -> tickTyping(t, n + 1), 380);
    }

    private void hideTyping() {
        if (typing != null) list.removeView(typing);
        typing = null;
    }

    private void scrollDown() {
        scroll.post(() -> scroll.smoothScrollTo(0, list.getHeight()));
    }

    private boolean voiceTurn;   // son soru sesle mi soruldu (öyleyse cevap mutlaka sesli)

    private void send(boolean byVoice) {
        if (user == null || busy) return;
        voiceTurn = byVoice;
        speaker.stop();
        String text = input.getText().toString().trim();
        byte[] img = pendingImg;
        if (text.isEmpty() && img == null) return;
        input.setText("");
        List<ChatStore.Msg> history = chat.last(CONTEXT_MSGS);
        String display = text, toModel = text, path = "";
        if (img != null) {
            path = Photo.save(this, img);
            display = (stepMode ? "📷 Adım adım çöz" : "📷 Sadece cevap") + (text.isEmpty() ? "" : " — " + text);
            toModel = Gemini.photoPrompt(stepMode, text);
            clearAttach();
        }
        ChatStore.Msg m = new ChatStore.Msg("user", display, System.currentTimeMillis(), path);
        chat.add(m);
        if (history.isEmpty()) renderChat();    // karşılama kartını kaldır
        else addBubble(m);
        ask(history, toModel, img);
    }

    private void ask(List<ChatStore.Msg> history, String text, byte[] img) {
        busy = true;
        setThinking();
        showTyping();
        scrollDown();
        final ChatStore target = chat;
        final User who = user;
        Gemini.ask(who, Goals.load(this, who).contextForModel(), history, text, img, new Gemini.Callback() {
            @Override
            public void ok(String raw) {
                Goals g = Goals.load(MainActivity.this, who);
                String reply = g.applyMarks(raw);
                if (img != null) g.countPhoto();     // kamerayla çözülen soru hedefe sayılsın
                ChatStore.Msg r = new ChatStore.Msg("model", reply, System.currentTimeMillis());
                target.add(r);
                if (target != chat) return;     // bu arada kullanıcı değiştiyse ekrana basma
                busy = false;
                hideTyping();
                addBubble(r);
                scrollDown();
                refreshGoalLine();
                if (voiceTurn || who.speakAlways) {
                    speaker.speak(who, reply);
                } else {
                    reactor.setState(ReactorView.SPEAK);
                    status.setText("CEVAP VERDİ");
                    h.postDelayed(() -> {
                        if (!busy && !speaker.isSpeaking()) setIdle();
                    }, 1800);
                }
            }

            @Override
            public void err(String message) {
                if (target != chat) return;
                busy = false;
                hideTyping();
                addError(message, () -> ask(history, text, img));
                if (voiceTurn) speaker.speak(who, message);
                scrollDown();
                reactor.setState(ReactorView.ERROR);
                status.setTextColor(Ui.BAD);
                status.setText("BAĞLANTI SORUNU");
                h.postDelayed(() -> {
                    if (!busy) setIdle();
                }, 2500);
            }
        });
    }

    // ------------------------------------------------------------------ fotoğraf
    private void takePhoto() {
        try {
            File dir = new File(getCacheDir(), "cam");
            //noinspection ResultOfMethodCallIgnored
            dir.mkdirs();
            File f = new File(dir, "cekim.jpg");
            camUri = FileProvider.getUriForFile(this, getPackageName() + ".files", f);
            Intent i = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            i.putExtra(MediaStore.EXTRA_OUTPUT, camUri);
            i.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivityForResult(i, REQ_CAM);
        } catch (ActivityNotFoundException e) {
            JDialog.info(this, "Kamera açılamadı", "Telefonda kamera uygulaması bulunamadı. Galeriden seçmeyi deneyebilirsin.");
        } catch (RuntimeException e) {
            JDialog.info(this, "Kamera açılamadı", String.valueOf(e.getMessage()));
        }
    }

    private void pickPhoto() {
        Intent i = new Intent(Intent.ACTION_GET_CONTENT);
        i.setType("image/*");
        i.addCategory(Intent.CATEGORY_OPENABLE);
        try {
            startActivityForResult(i, REQ_GAL);
        } catch (ActivityNotFoundException e) {
            JDialog.info(this, "Galeri açılamadı", "Fotoğraf seçecek bir uygulama bulunamadı.");
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req == REQ_MODEL) {
            Runnable then = afterModel;
            afterModel = null;
            if (res == RESULT_OK && data != null && data.getData() != null) runModelJob(then, data.getData());
            return;
        }
        if (res == RESULT_OK && req == REQ_SEND) {
            shareToTailscale(data);
            return;
        }
        if (req == REQ_CAM && qrPhoto) {
            qrPhoto = false;
            if (res == RESULT_OK && camUri != null) decodeQrPhoto(camUri);
            return;
        }
        if (res != RESULT_OK || (req != REQ_CAM && req != REQ_GAL)) return;
        Uri u = req == REQ_CAM ? camUri : (data != null ? data.getData() : null);
        if (u == null) return;
        status.setTextColor(Ui.CYAN);
        status.setText("FOTOĞRAF HAZIRLANIYOR…");
        new Thread(() -> {
            try {
                byte[] jpeg = Photo.prepare(this, u);
                Ui.MAIN.post(() -> {
                    setAttach(jpeg);
                    if (!busy) setIdle();
                });
            } catch (Exception e) {
                Ui.MAIN.post(() -> {
                    if (!busy) setIdle();
                    JDialog.info(this, "Fotoğraf okunamadı", String.valueOf(e.getMessage()));
                });
            }
        }).start();
    }

    private void setAttach(byte[] jpeg) {
        pendingImg = jpeg;
        attachThumb.setImageBitmap(Photo.thumb(jpeg, 200));
        attachThumb.setOnClickListener(v -> showBitmap(Photo.thumb(jpeg, 2000)));
        paintChips();
        attachBar.setVisibility(View.VISIBLE);
        input.setHint("İstersen not ekle (ör. “5. soru”)…");
        updateSendMic();
        toast("Fotoğraf hazır. Gönder'e bas ya da not ekle.");
    }

    private void clearAttach() {
        pendingImg = null;
        attachThumb.setImageDrawable(null);
        attachBar.setVisibility(View.GONE);
        if (user != null) input.setHint(user.assistant + "'e yaz…");
        updateSendMic();
    }

    private void showFull(String path) {
        showBitmap(Photo.thumb(path, 2000));
    }

    private void showBitmap(Bitmap bm) {
        if (bm == null) return;
        Dialog d = new Dialog(this, android.R.style.Theme_Black_NoTitleBar_Fullscreen);
        ImageView iv = new ImageView(this);
        iv.setImageBitmap(bm);
        iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
        iv.setBackgroundColor(0xFF000000);
        iv.setOnClickListener(v -> d.dismiss());
        d.setContentView(iv);
        d.show();
    }

    // ------------------------------------------------------------------ mikrofon
    private void toggleListen() {
        if (user == null) return;
        if (ear.isActive()) {
            ear.finish();          // o ana kadar söyleneni gönder
            return;
        }
        if (busy) {
            toast("Önceki soruya cevap bekleniyor…");
            return;
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
            return;
        }
        startListen();
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
        if (code != REQ_MIC) return;
        boolean ok = res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED;
        Runnable next = afterMic;
        afterMic = null;
        if (ok && next != null) next.run();
        else if (ok) startListen();
        else JDialog.info(this, "Mikrofon izni gerekli",
                "Sesli soru sorabilmek için mikrofon izni lazım. Telefon Ayarlar → Uygulamalar → Jarvis → İzinler → Mikrofon'dan açabilirsin.");
    }

    private void startListen() {
        if (!Ear.available(this)) {
            JDialog.info(this, "Ses tanıma yok",
                    "Bu telefonda Google ses tanıma bulunamadı. Play Store'dan “Google” uygulamasını güncelleyip tekrar dene.");
            return;
        }
        speaker.stop();
        input.setText("");
        micOn();
        reactor.setState(ReactorView.LISTEN);
        status.setTextColor(Ui.GOOD);
        status.setText("HAZIRLANIYOR…");
        ear.start(new Ear.Listener() {
            @Override
            public void onReady() {
                status.setText("DİNLİYORUM · BİTİNCE SUS YA DA DOKUN");
            }

            @Override
            public void onLevel(float rms) {
                reactor.setLevel(rms);
            }

            @Override
            public void onPartial(String text) {
                input.setText(text);
                input.setSelection(input.getText().length());
            }

            @Override
            public void onResult(String text) {
                micOff();
                reactor.setLevel(0);
                input.setText(text);
                send(true);
            }

            @Override
            public void onError(String message) {
                micOff();
                reactor.setLevel(0);
                input.setText("");
                reactor.setState(ReactorView.ERROR);
                status.setTextColor(Ui.BAD);
                status.setText(message.toUpperCase(TR));
                h.postDelayed(() -> {
                    if (!busy && !ear.isActive() && !speaker.isSpeaking()) setIdle();
                }, 2500);
            }
        });
    }

    private void micOn() {
        if (!micHeld) {
            micHeld = true;
            WakeService.pauseMic("mic");
        }
        micBtn.setVisibility(View.VISIBLE);
        sendBtn.setVisibility(View.GONE);
        micBtn.setColorFilter(Ui.BG);
        micBtn.setBackground(Ui.press(this, Ui.box(this, Ui.GOOD, 0, 24)));
    }

    private void micOff() {
        if (micHeld) {
            micHeld = false;
            WakeService.resumeMic("mic");
        }
        micBtn.setColorFilter(Ui.CYAN);
        micBtn.setBackground(Ui.press(this, Ui.box(this, 0x1422D3EE, Ui.LINE, 24)));
    }

    // ------------------------------------------------------------------ ses ayarları (menüde)
    private static final float[] RATES = {0.8f, 0.95f, 1.1f, 1.25f};
    private static final String[] RATE_N = {"Yavaş", "Normal", "Hızlı", "Çok hızlı"};
    private static final float[] PITCHES = {0.8f, 0.9f, 1.0f, 1.15f};
    private static final String[] PITCH_N = {"Çok kalın", "Kalın", "Normal", "İnce"};

    private static int nearest(float[] arr, float v) {
        int best = 0;
        for (int i = 1; i < arr.length; i++) if (Math.abs(arr[i] - v) < Math.abs(arr[best] - v)) best = i;
        return best;
    }

    private void sample() {
        speaker.speak(user, "Merhaba " + user.name + ", ben " + user.assistant + ". Sesim böyle.");
    }

    private void fillVoiceSection() {
        section("SES");
        row("Yazınca da sesli cevap:  " + (user.speakAlways ? "Açık" : "Kapalı"), Ui.TEXT).setOnClickListener(v -> {
            user.speakAlways = !user.speakAlways;
            if (!saveUserPrefs()) return;
            if (!user.speakAlways) speaker.stop();
            fillDrawer();
        });
        List<Voice> voices = speaker.turkishVoices();
        int vi = -1;
        for (int i = 0; i < voices.size(); i++) if (voices.get(i).getName().equals(user.voice)) vi = i;
        row("Ses:  " + (vi < 0 ? "Varsayılan" : "Ses " + (vi + 1)), Ui.TEXT).setOnClickListener(v -> pickVoice());
        int ri = nearest(RATES, user.rate);
        row("Hız:  " + RATE_N[ri], Ui.TEXT).setOnClickListener(v -> {
            user.rate = RATES[(ri + 1) % RATES.length];
            if (!saveUserPrefs()) return;
            sample();
            fillDrawer();
        });
        int pi = nearest(PITCHES, user.pitch);
        row("Ton:  " + PITCH_N[pi], Ui.TEXT).setOnClickListener(v -> {
            user.pitch = PITCHES[(pi + 1) % PITCHES.length];
            if (!saveUserPrefs()) return;
            sample();
            fillDrawer();
        });
        if (speaker.isReady() && !speaker.hasTurkish()) {
            TextView w = row("⚠  Telefonda Türkçe ses paketi yok — kurmak için dokun", Ui.BAD);
            w.setTextSize(13);
            w.setOnClickListener(v -> openTtsSettings());
        }
    }

    private void pickVoice() {
        List<Voice> voices = speaker.turkishVoices();
        if (voices.isEmpty()) {
            JDialog.confirm(this, "Türkçe ses bulunamadı",
                    "Telefonun metin okuma ayarlarından Türkçe ses verisini indirmen gerekiyor (Google Metin Okuma → Türkçe).",
                    "Ayarları aç", false, this::openTtsSettings);
            return;
        }
        String[] items = new String[voices.size() + 1];
        String[] subs = new String[voices.size() + 1];
        items[0] = "Varsayılan";
        subs[0] = "Telefonun seçtiği Türkçe ses";
        int checked = 0;
        for (int i = 0; i < voices.size(); i++) {
            Voice v = voices.get(i);
            items[i + 1] = "Ses " + (i + 1);
            subs[i + 1] = (v.isNetworkConnectionRequired() ? "internet gerekir · " : "telefonda · ") + v.getName();
            if (v.getName().equals(user.voice)) checked = i + 1;
        }
        JDialog.choose(this, "Ses seç (dokununca dinlersin)", items, subs, checked, k -> {
            String keep = user.voice;          // sadece dinlet; "Tamam" denmeden kaydetme
            user.voice = k == 0 ? "" : voices.get(k - 1).getName();
            sample();
            user.voice = keep;
        }, k -> {
            user.voice = k == 0 ? "" : voices.get(k - 1).getName();
            if (!saveUserPrefs()) return;
            fillDrawer();
        });
    }

    private void openTtsSettings() {
        try {
            startActivity(new Intent("com.android.settings.TTS_SETTINGS"));
        } catch (Exception e) {
            startActivity(new Intent(android.provider.Settings.ACTION_SETTINGS));
        }
    }

    // ------------------------------------------------------------------ izinler
    /** Mikrofon izni varsa işi hemen yapar, yoksa ister ve izin gelince yapar. */
    private void withMic(Runnable r) {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            r.run();
            return;
        }
        afterMic = r;
        requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
    }

    /** Android 13+ bildirim izni (hatırlatmalar ve uyandırma bildirimi için); yoksa sorar, cevabı beklemez. */
    private void askNotifPermission() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTIF);
        }
    }

    // ------------------------------------------------------------------ uyandırma (4. adım)
    private static final int[] WAKE_MIN = {15, 30, 60, 120};
    private static final String[] WAKE_N = {"15 dakika", "30 dakika", "1 saat", "2 saat"};
    private static final String[] SENS_N = {"Sıkı (az yanlış uyanır)", "Normal", "Gevşek (zor duyuyorsa)"};

    private void fillWakeSection() {
        section("UYANDIRMA");
        boolean on = WakeService.running();
        TextView st = row(on ? "●  Dinliyor · " + WakeService.fmtLeft(WakeService.remainingMs()) + " kaldı"
                : "○  Dinleme kapalı · başlatmak için dokun", on ? Ui.GOOD : Ui.TEXT);
        st.setOnClickListener(v -> {
            closeDrawer();
            wakeMenu();
        });
        row("Kelime:  “" + user.wakeWord() + "”", Ui.TEXT).setOnClickListener(v -> {
            closeDrawer();
            setWakeWord();
        });
        row("Dene:  kelimeyi söyle, duyuyor mu bak", Ui.TEXT).setOnClickListener(v -> {
            closeDrawer();
            testWake();
        });
        row("Hassasiyet:  " + SENS_N[Math.max(0, Math.min(2, user.wakeSens))], Ui.TEXT).setOnClickListener(v -> {
            user.wakeSens = (user.wakeSens + 1) % 3;
            if (!saveUserPrefs()) return;
            fillDrawer();
        });
        TextView hint = Ui.text(this, "Kısayol: çembere basılı tut.", 11, Ui.MUTED);
        hint.setPadding(dp(12), dp(2), 0, 0);
        drawer.addView(hint);
    }

    private void wakeMenu() {
        if (user == null) return;
        boolean on = WakeService.running();
        String[] items = new String[WAKE_MIN.length + (on ? 1 : 0)];
        for (int i = 0; i < WAKE_MIN.length; i++) items[i] = (on ? "Süreyi " : "") + WAKE_N[i] + (on ? " yap" : " dinle");
        if (on) items[WAKE_MIN.length] = "■  Dinlemeyi durdur";
        JDialog.menu(this, on ? "Uyandırma açık" : "“" + user.wakeWord() + "” deyince uyan", items, k -> {
            if (k == WAKE_MIN.length) {
                WakeService.stop(this);
                setIdle();
                toast("Uyandırma kapatıldı.");
            } else {
                startWake(WAKE_MIN[k]);
            }
        });
    }

    private void startWake(int minutes) {
        withMic(() -> ensureModel(() -> {
            askNotifPermission();
            try {
                WakeService.start(this, minutes);
            } catch (Throwable e) {
                JDialog.info(this, "Uyandırma başlatılamadı", String.valueOf(e));
                return;
            }
            toast("Dinliyorum: “" + user.wakeWord() + "” de. Ekranı kilitleyebilirsin.");
            h.postDelayed(() -> {
                if (!busy && !speaker.isSpeaking() && !ear.isActive()) setIdle();
            }, 500);
        }));
    }

    /** Uyandırma modeli yoksa (bir kereliğine) indirir, sonra işe devam eder. */
    private void ensureModel(Runnable then) {
        if (WakeModel.ready(this)) {
            then.run();
            return;
        }
        JDialog.menu(this, "Türkçe ses modeli gerekli (~37 MB, bir kez)", new String[]{
                "⇩  Uygulama indirsin",
                "🌐  Tarayıcıyla indir (uygulama indiremiyorsa)",
                "📁  İndirdiğim dosyadan yükle"}, k -> {
            if (k == 0) runModelJob(then, null);
            else if (k == 1) {
                JDialog.info(this, "Tarayıcıyla indir",
                        "Şimdi tarayıcı açılacak ve “vosk-model-small-tr-0.3.zip” dosyası İndirilenler'e inecek. "
                                + "İndirme bitince Jarvis'e dön ve aynı menüden “İndirdiğim dosyadan yükle”yi seç.");
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(MODEL_PAGE)));
                } catch (ActivityNotFoundException e) {
                    toast("Tarayıcı açılamadı.");
                }
            } else {
                afterModel = then;
                Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                i.addCategory(Intent.CATEGORY_OPENABLE);
                i.setType("*/*");
                i.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/zip", "application/x-zip-compressed", "application/octet-stream"});
                try {
                    startActivityForResult(i, REQ_MODEL);
                } catch (ActivityNotFoundException e) {
                    JDialog.info(this, "Dosya seçilemedi", "Dosya seçecek bir uygulama bulunamadı.");
                }
            }
        });
    }

    /** Modeli indirir (zip == null) ya da seçilen zip'ten yükler; ilerlemeyi gösterir. */
    private void runModelJob(Runnable then, Uri zip) {
        TextView p = Ui.text(this, zip == null ? "Bağlanıyor…" : "Dosya açılıyor…", 15, Ui.TEXT);
        Dialog d = JDialog.base(this, zip == null ? "Model indiriliyor" : "Model yükleniyor", p, null, false, null, null);
        d.setCancelable(false);
        d.show();
        new Thread(() -> {
            try {
                WakeModel.Progress pr = pc -> runOnUiThread(() -> p.setText((zip == null ? "İndiriliyor… %" : "Açılıyor… %") + pc));
                if (zip == null) WakeModel.download(this, pr);
                else WakeModel.importZip(this, zip, pr);
                runOnUiThread(() -> {
                    d.dismiss();
                    toast("Ses modeli hazır ✓");
                    if (then != null) then.run();
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    d.dismiss();
                    JDialog.info(this, zip == null ? "İndirilemedi" : "Yüklenemedi", e.getMessage()
                            + (zip == null ? "\n\nAynı menüden “Tarayıcıyla indir”i dene." : ""));
                });
            }
        }).start();
    }

    private void setWakeWord() {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        TextView note = Ui.text(this, "İki-üç heceli, günlük konuşmada az geçen bir kelime en iyisi (ör. Jarvis, Hey Asistan, Karaca). "
                + "Kaydettikten sonra “Dene” ile telefonun seni duyup duymadığına bak.", 13, Ui.DIM);
        col.addView(note);
        col.addView(Ui.gap(this, 10));
        EditText e = JDialog.field(this, "Uyandırma kelimesi", false);
        e.setText(user.wakeWord());
        col.addView(e);
        JDialog.base(this, "Uyandırma kelimesi", col, "Kaydet", false, () -> {
            String w = e.getText().toString().trim();
            if (w.isEmpty()) return;
            if (w.replace(" ", "").length() < 4) {
                JDialog.info(this, "Çok kısa", "Bu kadar kısa bir kelime sohbet arasında yanlışlıkla uyandırır. En az 4 harfli bir kelime seç.");
                return;
            }
            if (!w.equalsIgnoreCase(user.wakeWord())) user.wakeAlts.clear();
            user.wake = w;
            if (!saveUserPrefs()) return;
            setIdle();
            JDialog.confirm(this, "Kaydedildi", "Şimdi bir kere deneyelim mi? “" + w + "” deyince ekranda göreceksin.",
                    "Dene", false, this::testWake);
        }, "Vazgeç").show();
    }

    /** Test: kelimeyi söyle → Vosk ne duydu, eşleşti mi? Duyulanı "bunu da kabul et" ile öğretebilirsin. */
    private void testWake() {
        if (user == null) return;
        withMic(() -> ensureModel(() -> {
            LinearLayout col = new LinearLayout(this);
            col.setOrientation(LinearLayout.VERTICAL);
            TextView say = Ui.text(this, "Normal sesle “" + user.wakeWord() + "” de. Birkaç kez, farklı mesafelerden dene.", 15, Ui.TEXT);
            col.addView(say);
            col.addView(Ui.gap(this, 12));
            TextView heard = Ui.text(this, "Duyulan: …", 14, Ui.DIM);
            heard.setTypeface(Ui.MONO);
            col.addView(heard);
            col.addView(Ui.gap(this, 8));
            TextView result = Ui.text(this, "Hazırlanıyor…", 17, Ui.CYAN);
            result.setTypeface(Ui.MONO_B);
            col.addView(result);
            col.addView(Ui.gap(this, 10));
            TextView accept = Ui.button(this, "Duyduğunu da kabul et", false);
            accept.setVisibility(View.GONE);
            col.addView(accept);
            Dialog d = JDialog.base(this, "Uyandırma testi", col, null, false, null, "Kapat");
            d.setOnDismissListener(x -> {
                stopTest();
                WakeService.resumeMic("test");
            });
            WakeService.pauseMic("test");
            d.show();
            final String[] last = {""};
            accept.setOnClickListener(v -> {
                String w = last[0].trim();
                if (w.isEmpty()) return;
                if (!user.wakeAlts.contains(w)) user.wakeAlts.add(w);
                while (user.wakeAlts.size() > 6) user.wakeAlts.remove(0);
                if (!saveUserPrefs()) return;
                accept.setVisibility(View.GONE);
                result.setTextColor(Ui.GOOD);
                result.setText("✔ “" + w + "” de artık uyandırır");
            });
            new Thread(() -> {
                try {
                    org.vosk.Model m = WakeModel.get(this);
                    runOnUiThread(() -> {
                        if (!d.isShowing()) return;
                        try {
                            testSs = new SpeechService(new Recognizer(m, 16000f), 16000f);
                            result.setText("Dinliyorum…");
                            testSs.startListening(new RecognitionListener() {
                                private void show(String json, boolean fin) {
                                    String t = WakeModel.text(json);
                                    if (t.isEmpty()) return;
                                    heard.setText("Duyulan: " + t);
                                    if (WakeModel.matches(t, user)) {
                                        result.setTextColor(Ui.GOOD);
                                        result.setText("✔ Algılandı");
                                        accept.setVisibility(View.GONE);
                                    } else if (fin) {
                                        last[0] = t.length() > 24 ? t.substring(0, 24) : t;
                                        result.setTextColor(Ui.BAD);
                                        result.setText("✖ Algılanmadı");
                                        accept.setText("“" + last[0] + "” da uyandırsın");
                                        accept.setVisibility(View.VISIBLE);
                                    }
                                }

                                @Override
                                public void onPartialResult(String hyp) {
                                    show(hyp, false);
                                }

                                @Override
                                public void onResult(String hyp) {
                                    show(hyp, true);
                                }

                                @Override
                                public void onFinalResult(String hyp) {}

                                @Override
                                public void onError(Exception e) {
                                    result.setTextColor(Ui.BAD);
                                    result.setText("Mikrofon hatası: " + e.getMessage());
                                }

                                @Override
                                public void onTimeout() {}
                            });
                        } catch (Throwable e) {
                            result.setTextColor(Ui.BAD);
                            result.setText("Başlatılamadı: " + e);
                        }
                    });
                } catch (Throwable e) {
                    runOnUiThread(() -> {
                        result.setTextColor(Ui.BAD);
                        result.setText("Model yüklenemedi: " + e);
                    });
                }
            }).start();
        }));
    }

    private void stopTest() {
        if (testSs != null) {
            try {
                testSs.stop();
                testSs.shutdown();
            } catch (Exception ignored) {
            }
            testSs = null;
        }
    }

    // ------------------------------------------------------------------ hedefler (5. adım)
    private void refreshGoalLine() {
        if (user == null || goalLine == null) return;
        Goals g = Goals.load(this, user);
        if (g.goals.isEmpty()) {
            goalLine.setVisibility(View.GONE);
            return;
        }
        StringBuilder s = new StringBuilder();
        for (Goals.Goal x : g.goals) {
            if (s.length() > 0) s.append("   ");
            double t = g.amount(x.id, Goals.day(0));
            s.append(t >= x.daily ? "✔ " : "◆ ").append(x.name).append(' ')
                    .append(Goals.fmt(t)).append('/').append(Goals.fmt(x.daily));
        }
        goalLine.setText(s.toString());
        goalLine.setVisibility(View.VISIBLE);
    }

    private void closeGoals() {
        if (goalsView != null) root.removeView(goalsView);
        goalsView = null;
        refreshGoalLine();
    }

    private void showGoals() {
        if (user == null) return;
        int keepY = goalsView != null ? goalsView.getScrollY() : 0;
        if (goalsView != null) root.removeView(goalsView);
        Goals g = Goals.load(this, user);

        ScrollView sv = new ScrollView(this);
        sv.setBackgroundColor(Ui.BG);
        sv.setClickable(true);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(dp(16) + main.getPaddingLeft(), dp(12) + main.getPaddingTop(),
                dp(16) + main.getPaddingRight(), dp(28) + main.getPaddingBottom());
        sv.addView(col, new ScrollView.LayoutParams(-1, -2));

        LinearLayout head = new LinearLayout(this);
        head.setGravity(Gravity.CENTER_VERTICAL);
        TextView t = Ui.text(this, "HEDEFLER · " + user.name.toUpperCase(TR), 16, Ui.CYAN);
        t.setTypeface(Ui.MONO_B);
        t.setLetterSpacing(0.15f);
        head.addView(t, new LinearLayout.LayoutParams(0, -2, 1));
        TextView x = Ui.text(this, "✕", 22, Ui.DIM);
        x.setPadding(dp(12), dp(6), dp(4), dp(6));
        x.setOnClickListener(v -> closeGoals());
        head.addView(x);
        col.addView(head);

        if (g.goals.isEmpty()) {
            TextView e = Ui.text(this, "Henüz hedef yok. En fazla 3 ölçülebilir hedef ekleyebilirsin — ör. “LGS matematik: günde 20 soru”, "
                    + "“İngilizce: günde 15 dakika”. Jarvis her gün ilerlemeni takip eder, hatırlatır ve hafta sonu açık sözlü bir değerlendirme yapar.",
                    14, Ui.DIM);
            e.setLineSpacing(0, 1.2f);
            e.setPadding(0, dp(12), 0, 0);
            col.addView(e);
        }
        for (Goals.Goal goal : g.goals) col.addView(goalCard(g, goal), cardLp());

        if (g.goals.size() < Goals.MAX) {
            TextView add = Ui.button(this, "+ Hedef ekle", true);
            add.setOnClickListener(v -> editGoal(g, null, ""));
            col.addView(add, cardLp());
            // PC'deki hedeflerden öneri
            for (String pg : user.goals) {
                boolean exists = false;
                for (Goals.Goal z : g.goals) if (z.name.equalsIgnoreCase(pg)) exists = true;
                if (exists) continue;
                TextView sug = Ui.text(this, "PC'deki hedefin: “" + pg + "” → ölçülebilir hedef yap", 13, Ui.CYAN);
                sug.setPadding(dp(12), dp(10), dp(12), dp(10));
                sug.setBackground(Ui.press(this, Ui.box(this, 0x1422D3EE, Ui.LINE, 10)));
                sug.setOnClickListener(v -> editGoal(g, null, pg));
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
                lp.topMargin = dp(8);
                col.addView(sug, lp);
            }
        }

        if (!g.goals.isEmpty()) {
            TextView an = Ui.button(this, "📊  Haftalık analiz yap", false);
            an.setOnClickListener(v -> runAnalysis());
            col.addView(an, cardLp());

            String rt = user.remindMin < 0 ? "Kapalı"
                    : String.format(TR, "%02d:%02d", user.remindMin / 60, user.remindMin % 60);
            TextView rem = Ui.text(this, "⏰  Hatırlatma: " + rt + "\nHer gün bu saatte, eksik hedef varsa bildirim; pazar günleri haftalık analiz daveti.",
                    14, Ui.TEXT);
            rem.setLineSpacing(0, 1.2f);
            rem.setPadding(dp(14), dp(12), dp(14), dp(12));
            rem.setBackground(Ui.press(this, Ui.box(this, Ui.PANEL, Ui.LINE, 12)));
            rem.setOnClickListener(v -> JDialog.menu(this, "Hatırlatma", new String[]{"Saati değiştir", "Kapat"}, k -> {
                if (k == 1) {
                    user.remindMin = -1;
                    if (!saveUserPrefs()) return;
                    Reminders.schedule(this, user);
                    showGoals();
                    return;
                }
                int cur = user.remindMin < 0 ? 20 * 60 : user.remindMin;
                new TimePickerDialog(this, android.R.style.Theme_Material_Dialog_Alert, (tp, hh, mm) -> {
                    user.remindMin = hh * 60 + mm;
                    if (!saveUserPrefs()) return;
                    Reminders.schedule(this, user);
                    askNotifPermission();
                    showGoals();
                }, cur / 60, cur % 60, true).show();
            }));
            col.addView(rem, cardLp());
        }

        root.addView(sv, new FrameLayout.LayoutParams(-1, -1));
        goalsView = sv;
        if (keepY > 0) sv.post(() -> sv.scrollTo(0, keepY));
    }

    private LinearLayout.LayoutParams cardLp() {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.topMargin = dp(14);
        return lp;
    }

    private View goalCard(Goals g, Goals.Goal goal) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(14), dp(12), dp(14), dp(12));
        card.setBackground(Ui.box(this, Ui.PANEL, Ui.LINE, 14));

        LinearLayout top = new LinearLayout(this);
        top.setGravity(Gravity.CENTER_VERTICAL);
        TextView n = Ui.text(this, goal.name, 16, Ui.CYAN);
        n.setTypeface(Ui.MONO_B);
        top.addView(n, new LinearLayout.LayoutParams(0, -2, 1));
        TextView more = Ui.text(this, "⋯", 22, Ui.DIM);
        more.setPadding(dp(10), 0, dp(4), 0);
        more.setOnClickListener(v -> JDialog.menu(this, goal.name, new String[]{"Düzenle", "Sil"}, k -> {
            if (k == 0) editGoal(g, goal, "");
            else JDialog.confirm(this, "Hedef silinsin mi?", "“" + goal.name + "” ve kayıtları silinir.", "Sil", true, () -> {
                g.remove(goal);
                showGoals();
            });
        }));
        top.addView(more);
        card.addView(top);

        double today = g.amount(goal.id, Goals.day(0));
        TextView p = Ui.text(this, "Bugün: " + Goals.fmt(today) + " / " + Goals.fmt(goal.daily) + " " + goal.unit
                + (today >= goal.daily ? "  ✔" : ""), 14, Ui.TEXT);
        p.setPadding(0, dp(6), 0, dp(6));
        card.addView(p);

        LinearLayout bar = new LinearLayout(this);
        bar.setBackground(Ui.box(this, 0x1422D3EE, 0, 4));
        float ratio = (float) Math.max(0, Math.min(1, today / Math.max(0.0001, goal.daily)));
        View fill = new View(this);
        fill.setBackground(Ui.box(this, ratio >= 1 ? Ui.GOOD : Ui.CYAN, 0, 4));
        bar.addView(fill, new LinearLayout.LayoutParams(0, dp(8), ratio));
        bar.addView(new View(this), new LinearLayout.LayoutParams(0, dp(8), 1 - ratio));
        card.addView(bar, new LinearLayout.LayoutParams(-1, dp(8)));

        WeekBars wb = new WeekBars(this);
        wb.set(g, goal);
        LinearLayout.LayoutParams wl = new LinearLayout.LayoutParams(-1, dp(78));
        wl.topMargin = dp(10);
        card.addView(wb, wl);

        TextView st = Ui.text(this, "Seri: " + g.streak(goal) + " gün · Bu hafta " + g.hitDays(goal, 0) + "/7 gün"
                + (goal.photo ? " · 📷 kamerayla çözülenler sayılıyor" : ""), 12, Ui.DIM);
        st.setPadding(0, dp(6), 0, dp(8));
        card.addView(st);

        LinearLayout btns = new LinearLayout(this);
        double[] quick = "dakika".equals(goal.unit) ? new double[]{5, 15} : new double[]{1, 5};
        for (double q : quick) {
            TextView b = Ui.button(this, "+" + Goals.fmt(q), false);
            b.setOnClickListener(v -> {
                g.addAmount(goal.id, q);
                showGoals();
            });
            LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(0, -2, 1);
            bl.rightMargin = dp(8);
            btns.addView(b, bl);
        }
        TextView custom = Ui.button(this, "Miktar…", false);
        custom.setOnClickListener(v -> {
            EditText e = JDialog.field(this, "ör. 12  (düzeltmek için -3)", false);
            e.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL | InputType.TYPE_NUMBER_FLAG_SIGNED);
            JDialog.base(this, goal.name + " · bugüne ekle", e, "Ekle", false, () -> {
                try {
                    double val = Double.parseDouble(e.getText().toString().trim().replace(',', '.'));
                    g.addAmount(goal.id, val);
                    showGoals();
                } catch (NumberFormatException ignored) {
                    toast("Sayı yazmalısın.");
                }
            }, "Vazgeç").show();
        });
        btns.addView(custom, new LinearLayout.LayoutParams(0, -2, 1.2f));
        card.addView(btns);
        return card;
    }

    /** Hedef ekle (goal == null) ya da düzenle. */
    private void editGoal(Goals g, Goals.Goal goal, String suggestName) {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        EditText name = JDialog.field(this, "Hedefin adı (ör. LGS matematik)", false);
        name.setText(goal != null ? goal.name : suggestName);
        col.addView(name);
        col.addView(Ui.gap(this, 10));
        EditText daily = JDialog.field(this, "Günlük miktar (ör. 20)", false);
        daily.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        if (goal != null) daily.setText(Goals.fmt(goal.daily));
        col.addView(daily);
        col.addView(Ui.gap(this, 10));
        final String[] unit = {goal != null ? goal.unit : "soru"};
        final boolean[] photo = {goal != null ? goal.photo : true};
        TextView u = Ui.button(this, "", false);
        TextView ph = Ui.button(this, "", false);
        Runnable paint = () -> {
            u.setText("Birim: " + unit[0] + "  (değiştirmek için dokun)");
            ph.setText((photo[0] && "soru".equals(unit[0]) ? "☑" : "☐") + "  Kamerayla çözülen sorular sayılsın");
            ph.setAlpha("soru".equals(unit[0]) ? 1f : 0.4f);
        };
        u.setOnClickListener(v -> {
            int i = 0;
            for (int k = 0; k < Goals.UNITS.length; k++) if (Goals.UNITS[k].equals(unit[0])) i = k;
            unit[0] = Goals.UNITS[(i + 1) % Goals.UNITS.length];
            paint.run();
        });
        ph.setOnClickListener(v -> {
            photo[0] = !photo[0];
            paint.run();
        });
        paint.run();
        col.addView(u);
        col.addView(Ui.gap(this, 8));
        col.addView(ph);
        JDialog.base(this, goal == null ? "Yeni hedef" : "Hedefi düzenle", col, "Kaydet", false, () -> {
            String nm = name.getText().toString().trim();
            double d;
            try {
                d = Double.parseDouble(daily.getText().toString().trim().replace(',', '.'));
            } catch (NumberFormatException e) {
                d = 0;
            }
            if (nm.isEmpty() || d <= 0) {
                JDialog.info(this, "Eksik bilgi", "Hedefin adını ve günlük miktarı (0'dan büyük) yazmalısın.");
                return;
            }
            boolean pc = photo[0] && "soru".equals(unit[0]);
            if (goal == null) {
                g.add(nm, unit[0], d, pc);
                Reminders.schedule(this, user);
                askNotifPermission();
            } else {
                goal.name = nm;
                goal.unit = unit[0];
                goal.daily = d;
                goal.photo = pc;
                g.save();
            }
            showGoals();
        }, "Vazgeç").show();
    }

    /** Haftalık analiz: son 14 günün verisiyle Jarvis'ten açık sözlü değerlendirme ister, sohbete yazar. */
    private void runAnalysis() {
        if (user == null || busy) return;
        Goals g = Goals.load(this, user);
        if (g.goals.isEmpty()) {
            toast("Önce bir hedef ekle.");
            showGoals();
            return;
        }
        closeGoals();
        List<ChatStore.Msg> history = chat.last(6);
        ChatStore.Msg m = new ChatStore.Msg("user", "📊 Haftalık hedef analizimi yap", System.currentTimeMillis());
        chat.add(m);
        renderChat();
        voiceTurn = false;
        ask(history, g.analysisPrompt(user), null);
    }

    // ------------------------------------------------------------------ dosyalar (6. adım)
    private boolean installed(String pkg) {
        try {
            getPackageManager().getPackageInfo(pkg, 0);
            return true;
        } catch (PackageManager.NameNotFoundException e) {
            return false;
        }
    }

    private void needTailscale() {
        JDialog.confirm(this, "Tailscale gerekli",
                "Dosyalar bilgisayara Tailscale ile gider. Telefona Tailscale'i kurup bilgisayardaki ile aynı hesapla giriş yap.",
                "Play Store'u aç", false, () -> {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=" + TAILSCALE)));
                    } catch (ActivityNotFoundException e) {
                        startActivity(new Intent(Intent.ACTION_VIEW,
                                Uri.parse("https://play.google.com/store/apps/details?id=" + TAILSCALE)));
                    }
                });
    }

    private void sendToPc() {
        if (!installed(TAILSCALE)) {
            needTailscale();
            return;
        }
        Intent i = new Intent(Intent.ACTION_GET_CONTENT);
        i.setType("*/*");
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        try {
            startActivityForResult(i, REQ_SEND);
        } catch (ActivityNotFoundException e) {
            JDialog.info(this, "Dosya seçilemedi", "Dosya seçecek bir uygulama bulunamadı.");
        }
    }

    private void shareToTailscale(Intent data) {
        if (data == null) return;
        ArrayList<Uri> uris = new ArrayList<>();
        ClipData cd = data.getClipData();
        if (cd != null) for (int k = 0; k < cd.getItemCount(); k++) {
            Uri u = cd.getItemAt(k).getUri();
            if (u != null) uris.add(u);
        }
        if (uris.isEmpty() && data.getData() != null) uris.add(data.getData());
        if (uris.isEmpty()) return;
        Intent s;
        if (uris.size() == 1) {
            s = new Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, uris.get(0));
        } else {
            s = new Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris);
        }
        s.setType("*/*");
        ClipData clip = ClipData.newRawUri("dosya", uris.get(0));
        for (int k = 1; k < uris.size(); k++) clip.addItem(new ClipData.Item(uris.get(k)));
        s.setClipData(clip);
        s.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        s.setPackage(TAILSCALE);
        try {
            startActivity(s);
            toast("Tailscale'de bilgisayarını seç; dosya İndirilenler klasörüne gider.");
        } catch (ActivityNotFoundException e) {
            s.setPackage(null);
            startActivity(Intent.createChooser(s, "Bilgisayara gönder (Tailscale'i seç)"));
        }
    }

    private void openDownloads() {
        try {
            startActivity(new Intent(DownloadManager.ACTION_VIEW_DOWNLOADS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (ActivityNotFoundException e) {
            JDialog.info(this, "Açılamadı", "Telefonun Dosyalar uygulamasında İndirilenler klasörüne bak. "
                    + "Bilgisayardan gelen dosyalar oraya kaydedilir; Tailscale bildirimine dokunarak da açabilirsin.");
        }
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }
}
