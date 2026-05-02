"""把 Qdrant 里 high importance + 非 obsidian 来源 + 非 project 类的记忆,补迁到 Graphiti。

类别白名单 (~288 条):
  solution, debug, architecture, decision, summary, feedback, preference

特性:
- 断点续传: ~/.backfill_graphiti_progress.json 记 done_ids
- 限速: add_memory 之间 sleep 控制 (避免 graphiti 队列爆)
- 失败可重试: 失败的不进 done_ids,下次再跑
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

QDRANT_URL = "http://127.0.0.1:6333"
COLLECTION = "unified_memories_v3_local"
GRAPHITI_URL = "http://127.0.0.1:18001/mcp"
GROUP_ID = "claude_code"
CHECKPOINT_FILE = Path.home() / ".backfill_graphiti_progress.json"
INCLUDE_CATEGORIES = ["solution", "debug", "architecture", "decision", "summary", "feedback", "preference"]
EXCLUDE_SOURCES = ["obsidian_vault"]  # obsidian-sync 会单独处理

# 限速: 每个 add_memory 之间间隔(秒)
# Graphiti 35B 处理一个 episode 约 60s,设小点让队列堆但别堆太狠
SLEEP_BETWEEN = 5

http_client = QdrantClient(url=QDRANT_URL, timeout=30, check_compatibility=False)


def load_progress() -> dict:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"done_ids": [], "started_at": time.time()}


def save_progress(p: dict) -> None:
    CHECKPOINT_FILE.write_text(json.dumps(p))


def graphiti_init_session() -> str:
    """初始化 MCP session,返回 session_id。"""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "backfill-graphiti", "version": "1.0"},
        }
    }).encode("utf-8")
    req = urllib.request.Request(GRAPHITI_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    resp = urllib.request.urlopen(req, timeout=15)
    sid = resp.headers.get("mcp-session-id", "")
    if not sid:
        raise RuntimeError("未获取到 mcp-session-id")
    # 发送 notifications/initialized
    init_done = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8")
    req2 = urllib.request.Request(GRAPHITI_URL, data=init_done, method="POST")
    req2.add_header("Content-Type", "application/json")
    req2.add_header("Mcp-Session-Id", sid)
    req2.add_header("Accept", "application/json, text/event-stream")
    try:
        urllib.request.urlopen(req2, timeout=10)
    except Exception:
        pass
    return sid


def graphiti_add_memory(session_id: str, name: str, body: str) -> bool:
    """通过 MCP 调 Graphiti add_memory。返回是否成功。"""
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000),
        "method": "tools/call",
        "params": {
            "name": "add_memory",
            "arguments": {
                "name": name[:200],
                "episode_body": body[:4000],
                "group_id": GROUP_ID,
                "source": "text",
                "source_description": "qdrant-backfill 2026-05-02",
            },
        },
    }).encode("utf-8")
    req = urllib.request.Request(GRAPHITI_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Mcp-Session-Id", session_id)
    req.add_header("Accept", "application/json, text/event-stream")
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        body_text = resp.read().decode("utf-8")
        return "queued" in body_text or "success" in body_text.lower()
    except Exception as e:
        print(f"  ⚠️ add_memory 失败: {e}", flush=True)
        return False


def main() -> None:
    print(f"=== Qdrant → Graphiti 补迁 ({GROUP_ID}) ===", flush=True)
    print(f"  类别: {INCLUDE_CATEGORIES}", flush=True)
    print(f"  排除 source: {EXCLUDE_SOURCES}", flush=True)
    print(f"  限速: {SLEEP_BETWEEN}s/条", flush=True)
    print(flush=True)

    progress = load_progress()
    done_ids = set(progress["done_ids"])
    print(f"已迁移: {len(done_ids)}", flush=True)

    # 拉所有符合条件的点 (importance=high, category in 白名单, source 不在排除)
    print("拉 Qdrant 数据...", flush=True)
    points = []
    offset = None
    while True:
        batch, offset = http_client.scroll(
            collection_name=COLLECTION,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="importance", match=MatchValue(value="high")),
                    FieldCondition(key="category", match=MatchAny(any=INCLUDE_CATEGORIES)),
                ],
                must_not=[
                    FieldCondition(key="source", match=MatchAny(any=EXCLUDE_SOURCES)),
                ],
            ),
            limit=200, offset=offset,
            with_payload=True, with_vectors=False,
        )
        if not batch:
            break
        points.extend(batch)
        if offset is None:
            break
    print(f"目标记忆: {len(points)} 条", flush=True)

    todo = [p for p in points if p.id not in done_ids]
    print(f"待迁移: {len(todo)} 条 (已迁 {len(points) - len(todo)})", flush=True)
    if not todo:
        print("✅ 全部已迁移", flush=True)
        return

    eta_min = len(todo) * SLEEP_BETWEEN / 60
    eta_min += len(todo) * 60 / 60  # graphiti 异步,实际 60s/条但脚本不等
    print(f"预估总耗时: ~{len(todo) * SLEEP_BETWEEN / 60:.0f} 分钟塞完队列, graphiti 后台再处理 ~{len(todo) * 60 / 3600:.1f} 小时", flush=True)
    print(flush=True)

    print("初始化 Graphiti session...", flush=True)
    sid = graphiti_init_session()
    print(f"  session: {sid[:20]}...", flush=True)
    print(flush=True)

    t0 = time.time()
    succeeded = 0
    failed = 0
    for i, p in enumerate(todo, 1):
        payload = p.payload or {}
        content = payload.get("content", "")
        if not content:
            done_ids.add(p.id)
            continue
        category = payload.get("category", "general")
        created = payload.get("created_at", "?")[:10]
        name = f"[{created}] [{category}] {content[:80].replace(chr(10), ' ')}"

        if graphiti_add_memory(sid, name, content):
            succeeded += 1
            done_ids.add(p.id)
        else:
            failed += 1

        # checkpoint 每 10 条
        if i % 10 == 0:
            save_progress({"done_ids": sorted(done_ids, key=str), "last_update": time.time()})
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            remaining = (len(todo) - i) / rate if rate > 0 else 0
            print(f"  [{i}/{len(todo)}] 成功 {succeeded} 失败 {failed} | "
                  f"速度 {rate:.1f}/s | ETA {remaining/60:.1f} min", flush=True)

        time.sleep(SLEEP_BETWEEN)

    save_progress({"done_ids": sorted(done_ids, key=str), "last_update": time.time()})
    print(flush=True)
    print(f"=== 投递完成 ===", flush=True)
    print(f"  耗时: {(time.time()-t0)/60:.1f} 分钟", flush=True)
    print(f"  成功投递: {succeeded}", flush=True)
    print(f"  失败: {failed}", flush=True)
    print(f"  Graphiti 队列处理还需 ~{succeeded * 60 / 3600:.1f} 小时,挂着等就行", flush=True)


if __name__ == "__main__":
    main()
