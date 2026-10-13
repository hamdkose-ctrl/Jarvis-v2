package jarvis;
import java.util.HashSet;
import java.util.Set;

/** Shared pause reasons; calls may originate from audio worker threads. */
final class WakeHolds {
    private final Set<String> holds = new HashSet<>();
    synchronized void add(String who) { holds.add(who); }
    synchronized boolean remove(String who) { return holds.remove(who); }
    synchronized boolean paused() { return !holds.isEmpty(); }
}
