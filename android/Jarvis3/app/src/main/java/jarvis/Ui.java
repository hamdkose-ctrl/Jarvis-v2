package jarvis;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.view.Gravity;
import android.view.View;
import android.widget.TextView;

/** Komut Merkezi renkleri ve küçük görünüm yardımcıları (tüm ekran kodla çiziliyor). */
public final class Ui {
    private Ui() {}

    public static final int BG = 0xFFE8F0FB;
    public static final int PANEL = 0xFFF9FCFF;
    public static final int PANEL2 = 0xFFE2EFFB;
    public static final int LINE = 0xFFC5D7EC;
    public static final int CYAN = 0xFF237DD0;
    public static final int CYAN_DIM = 0xFF185A96;
    public static final int TEXT = 0xFF183651;
    public static final int DIM = 0xFF56718D;
    public static final int MUTED = 0xFF60788F;
    public static final int BAD = 0xFFC93651;
    public static final int WHITE = 0xFFFFFFFF;
    public static final int GOLD = 0xFFE4B344;
    public static final int GOOD = 0xFF15845D;

    public static final android.os.Handler MAIN = new android.os.Handler(android.os.Looper.getMainLooper());

    public static final Typeface MONO = Typeface.create(Typeface.MONOSPACE, Typeface.NORMAL);
    public static final Typeface MONO_B = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD);

    public static GradientDrawable background() {
        return new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{0xFFDCEAF9, 0xFFF3F7FC, 0xFFDCEAF9});
    }

    public static int dp(Context c, float v) {
        return Math.round(v * c.getResources().getDisplayMetrics().density);
    }

    public static GradientDrawable box(Context c, int fill, int stroke, float radiusDp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dp(c, radiusDp));
        if (stroke != 0) g.setStroke(dp(c, 1), stroke);
        return g;
    }

    /** Dokununca camgöbeği dalga çıkan arka plan. */
    public static Drawable press(Context c, Drawable content) {
        return new RippleDrawable(ColorStateList.valueOf(0x5522D3EE), content, null);
    }

    public static TextView text(Context c, String s, float sp, int color) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(sp);
        t.setTextColor(color);
        return t;
    }

    /** Yazılı düğme. primary=true dolu camgöbeği, false çerçeveli. */
    public static TextView button(Context c, String s, boolean primary) {
        TextView b = text(c, s, 15, primary ? WHITE : CYAN);
        b.setTypeface(Typeface.DEFAULT_BOLD);
        b.setGravity(Gravity.CENTER);
        b.setPadding(dp(c, 18), dp(c, 12), dp(c, 18), dp(c, 12));
        b.setBackground(press(c, box(c, primary ? CYAN : 0x1422D3EE, primary ? 0 : LINE, 10)));
        b.setMinHeight(dp(c, 44));
        b.setClickable(true);
        b.setFocusable(true);
        return b;
    }

    /** Sabit yükseklikte boşluk. (Boyutu açıkça verilmezse boş View kalan tüm alanı kaplıyor.) */
    public static View gap(Context c, float hDp) {
        View v = new View(c);
        v.setLayoutParams(new android.widget.LinearLayout.LayoutParams(1, dp(c, hDp)));
        return v;
    }

    /** Model cevabında kalan markdown işaretlerini temizler (cevap sesli de okunacak). */
    public static String clean(String s) {
        if (s == null) return "";
        String t = s.replace("**", "").replace("__", "").replace("`", "");
        t = t.replaceAll("(?m)^#{1,6}\\s*", "");
        t = t.replaceAll("(?m)^\\s*[*\\-•]\\s+", "• ");
        return t.trim();
    }
}
