package org.json;
import java.io.Serializable;
import java.util.*;
public class JSONArray implements Serializable {
    private final List<Object> values=new ArrayList<>();
    public JSONArray() {}
    public JSONArray(Collection<?> items) { values.addAll(items); }
    public JSONArray(String value) throws JSONException {
        if(value.equals("[]"))return;
        JSONArray parsed=new JSONObject(value).optJSONArray("array");
        values.addAll(parsed.values);
    }
    public JSONArray put(Object v) { values.add(v); return this; }
    public int length() { return values.size(); }
    public JSONObject getJSONObject(int i) throws JSONException { return (JSONObject)values.get(i); }
    public String getString(int i) throws JSONException { return (String)values.get(i); }
    public String optString(int i,String fallback) { return i<values.size()?values.get(i).toString():fallback; }
    public String toString() { try { return new JSONObject().put("array",this).toString(); } catch(JSONException e) { throw new IllegalStateException(e); } }
}
