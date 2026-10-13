package jarvis;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

import com.hamdi.jarvis.R;

import java.util.Calendar;

/**
 * Hedef hatırlatmaları: her kullanıcı için seçtiği saatte günlük bildirim; pazar günleri haftalık analiz daveti.
 * Telefon yeniden başlayınca alarmlar yeniden kurulur.
 */
public class Reminders extends BroadcastReceiver {
    public static final String CH_REMIND = "hatirlatma";
    public static final String CH_WAKE = "uyandirma";
    static final String ACTION_FIRE = "jarvis.HATIRLAT";
    public static final String EXTRA_USER = "kullanici";
    public static final String EXTRA_ANALYZE = "analiz";

    public static void channels(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null) return;
        NotificationChannel r = new NotificationChannel(CH_REMIND, "Hedef hatırlatmaları", NotificationManager.IMPORTANCE_DEFAULT);
        r.setDescription("Günlük hedef hatırlatması ve haftalık analiz");
        nm.createNotificationChannel(r);
        NotificationChannel w = new NotificationChannel(CH_WAKE, "Uyandırma dinlemesi", NotificationManager.IMPORTANCE_LOW);
        w.setDescription("Jarvis uyandırma kelimesini dinlerken görünen bildirim");
        w.setShowBadge(false);
        nm.createNotificationChannel(w);
    }

    private static PendingIntent pending(Context c, User u) {
        Intent i = new Intent(c, Reminders.class).setAction(ACTION_FIRE).putExtra(EXTRA_USER, u.slug());
        return PendingIntent.getBroadcast(c, u.slug().hashCode(), i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    /** Kullanıcının hatırlatma alarmını kurar ya da (kapalıysa) kaldırır. */
    public static void schedule(Context c, User u) {
        AlarmManager am = c.getSystemService(AlarmManager.class);
        if (am == null) return;
        PendingIntent pi = pending(c, u);
        am.cancel(pi);
        if (u.remindMin < 0) return;
        Calendar t = Calendar.getInstance();
        t.set(Calendar.HOUR_OF_DAY, u.remindMin / 60);
        t.set(Calendar.MINUTE, u.remindMin % 60);
        t.set(Calendar.SECOND, 0);
        if (t.getTimeInMillis() <= System.currentTimeMillis() + 30_000) t.add(Calendar.DAY_OF_YEAR, 1);
        am.setInexactRepeating(AlarmManager.RTC_WAKEUP, t.getTimeInMillis(), AlarmManager.INTERVAL_DAY, pi);
    }

    public static void scheduleAll(Context c) {
        for (User u : new Store(c).users()) schedule(c, u);
    }

    public static void cancel(Context c, User u) {
        AlarmManager am = c.getSystemService(AlarmManager.class);
        if (am != null) am.cancel(pending(c, u));
    }

    @Override
    public void onReceive(Context c, Intent in) {
        String a = in.getAction();
        if (Intent.ACTION_BOOT_COMPLETED.equals(a) || Intent.ACTION_MY_PACKAGE_REPLACED.equals(a)) {
            scheduleAll(c);
            return;
        }
        if (!ACTION_FIRE.equals(a)) return;
        User u = new Store(c).find(in.getStringExtra(EXTRA_USER));
        if (u == null) return;
        Goals g = Goals.load(c, u);
        if (g.goals.isEmpty()) return;
        channels(c);
        boolean sunday = Calendar.getInstance().get(Calendar.DAY_OF_WEEK) == Calendar.SUNDAY;
        String left = g.remaining();
        String title, text;
        if (sunday) {
            title = u.name + ", haftalık analizin hazır";
            text = (left.isEmpty() ? "Bugünkü hedefler tamam 👏 " : left + ". ") + "Haftanın değerlendirmesi için dokun.";
        } else if (left.isEmpty()) {
            return;     // hepsi tamamsa rahatsız etme
        } else {
            title = u.name + ", bugünkü hedeflerin";
            text = left + ". Küçük bir oturumla tamamlayabilirsin.";
        }
        Intent open = new Intent(c, MainActivity.class).putExtra(EXTRA_USER, u.slug())
                .putExtra(EXTRA_ANALYZE, sunday)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(c, 100 + u.slug().hashCode(), open,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification n = new Notification.Builder(c, CH_REMIND)
                .setSmallIcon(R.drawable.ic_stat_jarvis)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(pi)
                .setAutoCancel(true)
                .setColor(Ui.CYAN)
                .build();
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        try {
            if (nm != null) nm.notify(200 + Math.abs(u.slug().hashCode() % 1000), n);
        } catch (SecurityException ignored) {    // bildirim izni verilmemiş
        }
    }
}
