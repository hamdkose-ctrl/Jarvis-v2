package org.json;
import java.io.*;
import java.util.*;
/** Structural JSON stand-in with deep round trips. Actual JSON/Android is not tested. */
public class JSONObject implements Serializable {
    private Map<String,Object> values=new LinkedHashMap<>();
    public JSONObject() {}
    public JSONObject(Map<String,?> map) { values.putAll(map); }
    @SuppressWarnings("unchecked")
    public JSONObject(String value) throws JSONException {
        try (ObjectInputStream in=new ObjectInputStream(new ByteArrayInputStream(Base64.getDecoder().decode(value)))) {
            values=(Map<String,Object>)in.readObject();
        } catch(Exception e) { throw new JSONException(e.toString()); }
    }
    public JSONObject put(String k,Object v) throws JSONException { values.put(k,v); return this; }
    public boolean has(String k) { return values.containsKey(k); }
    public JSONArray optJSONArray(String k) { return (JSONArray)values.get(k); }
    public JSONObject optJSONObject(String k) { return (JSONObject)values.get(k); }
    public JSONObject getJSONObject(String k) throws JSONException { return (JSONObject)values.get(k); }
    public String optString(String k) { return optString(k,""); }
    public String optString(String k,String fallback) { Object v=values.get(k); return v==null?fallback:v.toString(); }
    public double optDouble(String k,double fallback) { Object v=values.get(k); return v==null?fallback:((Number)v).doubleValue(); }
    public int optInt(String k,int fallback) { Object v=values.get(k); return v==null?fallback:((Number)v).intValue(); }
    public boolean optBoolean(String k,boolean fallback) { Object v=values.get(k); return v==null?fallback:(Boolean)v; }
    public double getDouble(String k) throws JSONException { return ((Number)values.get(k)).doubleValue(); }
    public JSONArray names() { JSONArray a=new JSONArray(); for(String k:values.keySet()) a.put(k); return a; }
    public String toString() {
        try { ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            try(ObjectOutputStream out=new ObjectOutputStream(bytes)) { out.writeObject(values); }
            return Base64.getEncoder().encodeToString(bytes.toByteArray());
        } catch(IOException e) { throw new IllegalStateException(e); }
    }
}
