package android.util;
import java.io.*;
import java.nio.file.*;
/** JVM-only fault-injection substitute, not an Android implementation test. */
public class AtomicFile {
    public static boolean fail;
    private final File base, pending;
    public AtomicFile(File f) { base=f; pending=new File(f+".new"); }
    public FileInputStream openRead() throws IOException { return new FileInputStream(base); }
    public FileOutputStream startWrite() throws IOException {
        if (fail) throw new IOException("injected disk failure");
        return new FileOutputStream(pending);
    }
    public void finishWrite(FileOutputStream out) throws IOException {
        out.getFD().sync(); out.close();
        Files.move(pending.toPath(),base.toPath(),StandardCopyOption.REPLACE_EXISTING);
    }
    public void failWrite(FileOutputStream out) {
        try { out.close(); Files.deleteIfExists(pending.toPath()); } catch(IOException ignored) {}
    }
    public void delete() { base.delete(); pending.delete(); }
}
