package jarvis;

import android.app.Activity;
import android.app.Dialog;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Jarvis temasına uygun koyu/camgöbeği iletişim kutuları (sistemin beyaz kutuları yerine). */
public final class JDialog {
    private JDialog() {}

    public interface Done {
        void run();
    }

    public interface TwoFields {
        void ok(String a, String b);
    }

    static Dialog base(Activity a, String title, View body, String okText, boolean danger, Done ok, String cancelText) {
        Dialog d = new Dialog(a);
        d.requestWindowFeature(Window.FEATURE_NO_TITLE);
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(a, 20);
        box.setPadding(p, p, p, Ui.dp(a, 14));
        box.setBackground(Ui.box(a, Ui.PANEL, Ui.LINE, 16));

        TextView t = Ui.text(a, title, 17, Ui.CYAN);
        t.setTypeface(Ui.MONO_B);
        box.addView(t);
        if (body != null) {
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            lp.topMargin = Ui.dp(a, 12);
            box.addView(body, lp);
        }
        LinearLayout row = new LinearLayout(a);
        row.setGravity(Gravity.END);
        LinearLayout.LayoutParams rl = new LinearLayout.LayoutParams(-1, -2);
        rl.topMargin = Ui.dp(a, 18);
        box.addView(row, rl);
        if (cancelText != null) {
            TextView c = Ui.button(a, cancelText, false);
            c.setOnClickListener(v -> d.dismiss());
            row.addView(c);
        }
        if (okText != null) {
            TextView o = Ui.button(a, okText, true);
            if (danger) o.setBackground(Ui.press(a, Ui.box(a, Ui.BAD, 0, 10)));
            LinearLayout.LayoutParams ol = new LinearLayout.LayoutParams(-2, -2);
            ol.leftMargin = Ui.dp(a, 10);
            row.addView(o, ol);
            o.setOnClickListener(v -> {
                d.dismiss();
                if (ok != null) ok.run();
            });
        }
        d.setContentView(box);
        Window w = d.getWindow();
        if (w != null) {
            w.setBackgroundDrawable(new ColorDrawable(0));
            w.setLayout(Math.min(a.getResources().getDisplayMetrics().widthPixels - Ui.dp(a, 32), Ui.dp(a, 420)),
                    ViewGroup.LayoutParams.WRAP_CONTENT);
        }
        return d;
    }

    private static TextView body(Activity a, String msg) {
        TextView m = Ui.text(a, msg, 15, Ui.TEXT);
        m.setLineSpacing(0, 1.15f);
        return m;
    }

    public static void info(Activity a, String title, String msg) {
        base(a, title, body(a, msg), "Tamam", false, null, null).show();
    }

    public static void confirm(Activity a, String title, String msg, String okText, boolean danger, Done ok) {
        base(a, title, body(a, msg), okText, danger, ok, "Vazgeç").show();
    }

    public static EditText field(Activity a, String hint, boolean secret) {
        EditText e = new EditText(a);
        e.setHint(hint);
        e.setTextColor(Ui.TEXT);
        e.setHintTextColor(Ui.MUTED);
        e.setTextSize(15);
        e.setSingleLine(true);
        e.setPadding(Ui.dp(a, 12), Ui.dp(a, 10), Ui.dp(a, 12), Ui.dp(a, 10));
        e.setBackground(Ui.box(a, Ui.BG, Ui.LINE, 10));
        if (secret) {
            e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
            e.setTypeface(Typeface.MONOSPACE);
        } else {
            e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_WORDS);
        }
        return e;
    }

    public interface Pick {
        void picked(int index);
    }

    /** Basit menü: bir satıra dokununca kapanır ve onu seçer. */
    public static void menu(Activity a, String title, String[] items, Pick onPick) {
        LinearLayout col = new LinearLayout(a);
        col.setOrientation(LinearLayout.VERTICAL);
        Dialog[] holder = new Dialog[1];
        for (int i = 0; i < items.length; i++) {
            TextView r = Ui.text(a, items[i], 16, Ui.TEXT);
            r.setPadding(Ui.dp(a, 14), Ui.dp(a, 14), Ui.dp(a, 14), Ui.dp(a, 14));
            r.setBackground(Ui.press(a, Ui.box(a, 0x1422D3EE, Ui.LINE, 12)));
            final int k = i;
            r.setOnClickListener(v -> {
                if (holder[0] != null) holder[0].dismiss();
                onPick.picked(k);
            });
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
            if (i > 0) lp.topMargin = Ui.dp(a, 8);
            col.addView(r, lp);
        }
        holder[0] = base(a, title, col, null, false, null, "Vazgeç");
        holder[0].show();
    }

    /** Liste seçimi: her dokunuşta onPick çağrılır (örn. sesi hemen dinletmek için), "Tamam" ile onOk. */
    public static void choose(Activity a, String title, String[] items, String[] subs, int checked, Pick onPick, Pick onOk) {
        LinearLayout col = new LinearLayout(a);
        col.setOrientation(LinearLayout.VERTICAL);
        final int[] sel = {checked};
        TextView[] rows = new TextView[items.length];
        for (int i = 0; i < items.length; i++) {
            TextView r = Ui.text(a, "", 15, Ui.TEXT);
            r.setPadding(Ui.dp(a, 12), Ui.dp(a, 10), Ui.dp(a, 12), Ui.dp(a, 10));
            rows[i] = r;
            final int k = i;
            r.setOnClickListener(v -> {
                sel[0] = k;
                for (int j = 0; j < rows.length; j++) paintRow(a, rows[j], items[j], subs == null ? null : subs[j], j == sel[0]);
                if (onPick != null) onPick.picked(k);
            });
            paintRow(a, r, items[i], subs == null ? null : subs[i], i == checked);
            col.addView(r, new LinearLayout.LayoutParams(-1, -2));
        }
        android.widget.ScrollView sv = new android.widget.ScrollView(a);
        sv.addView(col);
        sv.setLayoutParams(new LinearLayout.LayoutParams(-1, Math.min(Ui.dp(a, 360), Ui.dp(a, 52) * items.length)));
        base(a, title, sv, "Tamam", false, () -> onOk.picked(sel[0]), "Vazgeç").show();
    }

    private static void paintRow(Activity a, TextView r, String item, String sub, boolean on) {
        r.setText(sub == null ? (on ? "●  " : "○  ") + item : (on ? "●  " : "○  ") + item + "\n    " + sub);
        r.setTextColor(on ? Ui.CYAN : Ui.TEXT);
        r.setBackground(Ui.press(a, Ui.box(a, on ? 0x1422D3EE : 0, on ? Ui.LINE : 0, 10)));
    }

    /** İki alanlı form (elle kullanıcı ekleme). */
    public static void two(Activity a, String title, String note, String hint1, String hint2, TwoFields ok) {
        LinearLayout col = new LinearLayout(a);
        col.setOrientation(LinearLayout.VERTICAL);
        if (note != null) {
            TextView n = Ui.text(a, note, 13, Ui.DIM);
            col.addView(n);
            col.addView(Ui.gap(a, 10));
        }
        EditText e1 = field(a, hint1, false);
        EditText e2 = field(a, hint2, true);
        col.addView(e1);
        col.addView(Ui.gap(a, 10));
        col.addView(e2);
        base(a, title, col, "Kaydet", false,
                () -> ok.ok(e1.getText().toString().trim(), e2.getText().toString().trim()), "Vazgeç").show();
    }
}
