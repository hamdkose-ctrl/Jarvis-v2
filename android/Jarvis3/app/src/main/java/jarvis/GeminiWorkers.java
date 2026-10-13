package jarvis;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Small bounded pool: one slow request cannot hold every conversation hostage. */
final class GeminiWorkers implements AutoCloseable {
    private final ThreadPoolExecutor executor = new ThreadPoolExecutor(
            2, 2, 30, TimeUnit.SECONDS, new ArrayBlockingQueue<>(8));
    GeminiWorkers() { executor.allowCoreThreadTimeOut(true); }
    boolean submit(Runnable work) {
        try { executor.execute(work); return true; }
        catch (RejectedExecutionException e) { return false; }
    }
    public void close() { executor.shutdownNow(); }
}
