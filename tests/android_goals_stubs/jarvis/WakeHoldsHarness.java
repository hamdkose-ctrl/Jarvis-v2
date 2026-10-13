package jarvis;
public class WakeHoldsHarness {
    private static void require(boolean ok) { if(!ok) throw new AssertionError(); }
    public static void main(String[] args) throws Exception {
        WakeHolds holds=new WakeHolds();
        holds.add("mic"); holds.add("tts"); holds.add("tts");
        require(holds.remove("tts") && holds.paused());
        require(!holds.remove("tts") && holds.paused());
        require(holds.remove("mic") && !holds.paused());
        Thread[] workers=new Thread[8];
        for(int i=0;i<workers.length;i++) {
            final String reason="worker"+i;
            workers[i]=new Thread(()->{for(int n=0;n<1000;n++){holds.add(reason);holds.paused();holds.remove(reason);}});
            workers[i].start();
        }
        for(Thread worker:workers) worker.join();
        require(!holds.paused());
        System.out.println("WakeHolds concurrent and duplicate reasons passed");
    }
}
