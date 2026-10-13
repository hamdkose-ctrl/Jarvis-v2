package android.content;
import java.io.File;
public class Context {
    public File getFilesDir() { throw new UnsupportedOperationException(); }
    public static final int MODE_PRIVATE=0;
    public SharedPreferences getSharedPreferences(String name,int mode) { throw new UnsupportedOperationException(); }
}
