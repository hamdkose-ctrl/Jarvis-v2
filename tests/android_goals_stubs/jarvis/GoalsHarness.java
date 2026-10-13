package jarvis;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.lang.reflect.*;
public class GoalsHarness {
    private static void require(boolean ok,String message) { if(!ok) throw new AssertionError(message); }
    public static void main(String[] args) throws Exception {
        File file=new File(args[0],"goals_a.json");
        Goals screen=Goals.loadFile(file);
        Goals.Goal goal=screen.add("math","soru",10,true);
        Goals chat=Goals.loadFile(file);
        require(screen==chat,"different snapshots for same file");
        chat.addAmount(goal.id,5);
        goal.name="edited"; screen.save();
        require(screen.amount(goal.id,Goals.day(0))==5,"screen erased chat progress");
        Thread a=new Thread(()->{for(int i=0;i<20;i++)screen.addAmount(goal.id,1);});
        Thread b=new Thread(()->{for(int i=0;i<20;i++)chat.addAmount(goal.id,1);});
        a.start(); b.start(); a.join(); b.join();
        require(screen.amount(goal.id,Goals.day(0))==45,"concurrent increments lost");
        require(Goals.loadFile(new File(args[0],"goals_b.json")).goals.isEmpty(),"profile leak");
        byte[] previous=Files.readAllBytes(file.toPath());
        android.util.AtomicFile.fail=true;
        screen.addAmount(goal.id,1);
        require(Arrays.equals(previous,Files.readAllBytes(file.toPath())),"disk failure damaged old file");
        android.util.AtomicFile.fail=false; screen.save();
        Field cache=Goals.class.getDeclaredField("OPEN"); cache.setAccessible(true);
        ((Map<?,?>)cache.get(null)).clear();
        Goals restored=Goals.loadFile(file);
        require(restored.amount(goal.id,Goals.day(0))==46,"retry did not persist progress");
        require(restored.find(goal.id).name.equals("edited"),"edit missing after reload");
        restored.deleteFile(); restored.addAmount(goal.id,1);
        require(!file.exists() && restored.goals.isEmpty(),"late callback resurrected deleted goal");
        System.out.println("Goals: stale screen, concurrent increments, profile isolation, disk retry, reload and deletion passed (Android/JSON substitutes).");
    }
}
