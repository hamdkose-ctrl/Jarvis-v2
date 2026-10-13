package jarvis;
import org.json.JSONObject;
public class AndroidSetupHarness {
    public static void main(String[] args) throws Exception {
        JSONObject qr=new JSONObject().put("j","jarvis-android").put("v",2).put("c","a".repeat(43)).put("u","https://pc.tailnet.ts.net/api/android-setup");
        AndroidSetup.endpoint(qr);
        String[] invalid={"http://pc.ts.net/api/android-setup","https://evil.example/api/android-setup","https://pc.ts.net.evil.example/api/android-setup","https://name@pc.ts.net/api/android-setup","https://pc.ts.net:444/api/android-setup","https://pc.ts.net/api/android-setup?code=secret","https://pc.ts.net/other"};
        for(String url:invalid) {
            qr.put("u",url);
            try {AndroidSetup.endpoint(qr);throw new AssertionError("accepted "+url);}
            catch(IllegalArgumentException expected) {}
        }
        System.out.println("AndroidSetup HTTPS host, port, path and credential boundaries passed");
    }
}
