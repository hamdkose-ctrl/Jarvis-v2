package jarvis;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.view.View;

/** Komut Merkezi'ndeki dönen JARVIS çemberi. Durum: boşta / düşünüyor / konuşuyor / hata. */
public class ReactorView extends View {
    public static final int IDLE = 0, THINK = 1, SPEAK = 2, ERROR = 3, LISTEN = 4;

    private int state = IDLE;
    private float level, shown;   // mikrofon ses seviyesi (0..1), dinlerken çekirdek buna göre büyür
    private float a1, a2, a3, pulse;
    private long last;
    private final Paint ring = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint dash = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint arc = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint core = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF rf = new RectF();

    public ReactorView(Context c) {
        super(c);
        ring.setStyle(Paint.Style.STROKE);
        dash.setStyle(Paint.Style.STROKE);
        arc.setStyle(Paint.Style.STROKE);
        arc.setStrokeCap(Paint.Cap.ROUND);
    }

    public void setState(int s) {
        state = s;
        invalidate();
    }

    /** SpeechRecognizer'ın rms değeri (yaklaşık -2..10 dB). */
    public void setLevel(float rmsDb) {
        level = Math.max(0f, Math.min(1f, (rmsDb + 2f) / 12f));
    }

    public int getState() {
        return state;
    }

    @Override
    protected void onDraw(Canvas cv) {
        long now = System.nanoTime();
        float dt = last == 0 ? 0 : Math.min(0.05f, (now - last) / 1e9f);
        last = now;
        float speed = state == THINK ? 3.2f : state == SPEAK ? 1.6f : state == LISTEN ? 1.1f : 0.6f;
        shown += (level - shown) * Math.min(1f, dt * 12f);
        a1 += 40 * speed * dt;
        a2 -= 65 * speed * dt;
        a3 += 110 * speed * dt;
        pulse += dt * (state == SPEAK ? 7f : 2f);

        int col = state == ERROR ? Ui.BAD : state == LISTEN ? Ui.GOOD : Ui.CYAN;
        float w = getWidth(), h = getHeight(), cx = w / 2f, cy = h / 2f;
        float r = Math.min(w, h) / 2f - Ui.dp(getContext(), 3);
        float d = getResources().getDisplayMetrics().density;
        float beat = (float) (0.5 + 0.5 * Math.sin(pulse));

        // dış ince halka
        ring.setColor((col & 0x00FFFFFF) | 0x55000000);
        ring.setStrokeWidth(1.2f * d);
        cv.drawCircle(cx, cy, r, ring);

        // dönen kesikli halka
        cv.save();
        cv.rotate(a1, cx, cy);
        dash.setColor((col & 0x00FFFFFF) | 0x99000000);
        dash.setStrokeWidth(3 * d);
        dash.setPathEffect(new DashPathEffect(new float[]{6 * d, 9 * d}, 0));
        cv.drawCircle(cx, cy, r * 0.86f, dash);
        cv.restore();

        // ters dönen yaylar
        float r2 = r * 0.70f;
        rf.set(cx - r2, cy - r2, cx + r2, cy + r2);
        arc.setColor(col);
        arc.setStrokeWidth(4 * d);
        for (int i = 0; i < 3; i++) cv.drawArc(rf, a2 + i * 120, 70, false, arc);

        float r3 = r * 0.55f;
        rf.set(cx - r3, cy - r3, cx + r3, cy + r3);
        arc.setColor((col & 0x00FFFFFF) | 0xAA000000);
        arc.setStrokeWidth(2 * d);
        for (int i = 0; i < 6; i++) cv.drawArc(rf, a3 + i * 60, 25, false, arc);

        // parlayan iç çekirdek
        float rg = state == LISTEN ? r * (0.40f + 0.22f * shown)
                : r * (0.46f + (state == IDLE ? 0.02f : 0.05f) * beat);
        int inner = state == ERROR ? 0xFFFFC2CB : state == LISTEN ? 0xFFD1FAE5 : 0xFFE0FBFF;
        glow.setShader(new RadialGradient(cx, cy, rg, new int[]{inner, (col & 0x00FFFFFF) | 0xCC000000, 0x00000000},
                new float[]{0f, 0.45f, 1f}, Shader.TileMode.CLAMP));
        cv.drawCircle(cx, cy, rg, glow);
        core.setColor(inner);
        cv.drawCircle(cx, cy, r * 0.12f, core);

        postInvalidateOnAnimation();
    }

    @Override
    protected void onDetachedFromWindow() {
        super.onDetachedFromWindow();
        last = 0;
    }
}
