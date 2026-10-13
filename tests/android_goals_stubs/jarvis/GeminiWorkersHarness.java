package jarvis;
import java.util.concurrent.*;
public class GeminiWorkersHarness {
    public static void main(String[] args) throws Exception {
        CountDownLatch started=new CountDownLatch(2),release=new CountDownLatch(1);
        try(GeminiWorkers workers=new GeminiWorkers()) {
            Runnable slow=()->{started.countDown();try{release.await();}catch(InterruptedException e){Thread.currentThread().interrupt();}};
            if(!workers.submit(slow)||!workers.submit(slow)||!started.await(3,TimeUnit.SECONDS))
                throw new AssertionError("second request blocked by first");
            for(int n=0;n<8;n++)if(!workers.submit(()->{}))throw new AssertionError("queue capacity");
            if(workers.submit(()->{}))throw new AssertionError("unbounded queue");
            release.countDown();
        } finally { release.countDown(); }
        System.out.println("GeminiWorkers independent execution and queue bound passed");
    }
}
