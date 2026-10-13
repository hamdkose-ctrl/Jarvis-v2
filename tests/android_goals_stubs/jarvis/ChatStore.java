package jarvis;
public class ChatStore {
    public static class Msg {
        public String text="",img="",role="user";
        public boolean mine() { return role.equals("user"); }
    }
}
