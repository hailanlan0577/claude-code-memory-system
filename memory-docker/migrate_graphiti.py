"""Import Graphiti episodes into local MCP server."""
import json, urllib.request, time

LOCAL_MCP = "http://localhost:28001/mcp"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

def post_mcp(payload, sid):
    h = {**HEADERS, "Mcp-Session-Id": sid} if sid else HEADERS
    req = urllib.request.Request(LOCAL_MCP, data=json.dumps(payload).encode(), headers=h)
    resp = urllib.request.urlopen(req, timeout=120)
    sid_out = resp.headers.get("Mcp-Session-Id") or sid
    text = resp.read().decode()
    for line in text.split("\n"):
        if line.startswith("data: "):
            return json.loads(line[6:]), sid_out
    return None, sid_out

def main():
    episodes = json.load(open("/tmp/graphiti_episodes.json"))
    print(f"Importing {len(episodes)} episodes...")

    # Initialize
    r, sid = post_mcp({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"migrator","version":"1.0"}}}, None)
    post_mcp({"jsonrpc":"2.0","method":"notifications/initialized"}, sid)
    print(f"Session: {sid}")

    ok = fail = 0
    for i, ep in enumerate(episodes):
        try:
            r, _ = post_mcp({"jsonrpc":"2.0","id":i+10,"method":"tools/call","params":{"name":"add_memory","arguments":{"name":ep["name"],"episode_body":ep["content"],"group_id":"claude_code","source":ep.get("source","text"),"source_description":ep.get("source_description","")}}}, sid)
            ok += 1
            if (i+1) % 10 == 0:
                print(f"  [{i+1}/{len(episodes)}] {ok} ok, {fail} fail")
        except Exception as e:
            fail += 1
            print(f"  [{i+1}] FAILED: {str(e)[:80]}")
        time.sleep(0.5)

    print(f"\nDone! OK: {ok}, Failed: {fail}, Total: {len(episodes)}")

if __name__ == "__main__":
    main()
