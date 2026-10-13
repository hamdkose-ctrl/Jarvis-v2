package jarvis;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.view.View;

/** Bir hedefin son 7 günü: hedefe ulaşılan günler dolu camgöbeği, eksik günler oranında, boş günler sönük. */
public class WeekBars extends View {
    private final double[] values = new double[7];
    private final String[] labels = new String[7];
    private double target = 1;
    private final Paint bar = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint txt = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint line = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF rf = new RectF();

    public WeekBars(Context c) {
        super(c);
        txt.setColor(Ui.MUTED);
        txt.setTextAlign(Paint.Align.CENTER);
        txt.setTextSize(Ui.dp(c, 10));
        txt.setTypeface(Ui.MONO);
        line.setColor(Ui.LINE);
        line.setStrokeWidth(Ui.dp(c, 1));
    }

    public void set(Goals g, Goals.Goal goal) {
        target = Math.max(0.0001, goal.daily);
        for (int i = 0; i < 7; i++) {
            int off = i - 6;
            values[i] = g.amount(goal.id, Goals.day(off));
            labels[i] = off == 0 ? "bugün" : Goals.dayLabel(off);
        }
        invalidate();
    }

    @Override
    protected void onDraw(Canvas c) {
        float w = getWidth(), h = getHeight();
        float lab = Ui.dp(getContext(), 16);
        float top = Ui.dp(getContext(), 4), bottom = h - lab;
        float slot = w / 7f, bw = slot * 0.56f, r = Ui.dp(getContext(), 4);
        // hedef çizgisi
        float ty = bottom - (bottom - top) * (float) Math.min(1, 1.0 / 1.25);
        c.drawLine(0, ty, w, ty, line);
        for (int i = 0; i < 7; i++) {
            double ratio = Math.min(1.25, values[i] / target);
            float x = slot * i + (slot - bw) / 2f;
            float bh = (float) ((bottom - top) * ratio / 1.25);
            if (values[i] <= 0) {
                bar.setColor(0x2222D3EE);
                rf.set(x, bottom - Ui.dp(getContext(), 3), x + bw, bottom);
            } else {
                bar.setColor(values[i] >= target ? Ui.CYAN : 0x9922D3EE);
                rf.set(x, bottom - Math.max(bh, Ui.dp(getContext(), 3)), x + bw, bottom);
            }
            c.drawRoundRect(rf, r, r, bar);
            txt.setColor(i == 6 ? Ui.CYAN : Ui.MUTED);
            c.drawText(labels[i] == null ? "" : labels[i], slot * i + slot / 2f, h - Ui.dp(getContext(), 3), txt);
        }
    }
}
