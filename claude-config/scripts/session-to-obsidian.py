#!/usr/bin/env python3
"""
Claude Code 会话记录 → Obsidian + Qdrant + Graphiti 统一归档
SessionEnd hook：会话结束时，将完整对话写入三个目标。
SessionStart hook (--scan-all)：扫描未归档会话 + 重试失败项。

目标：
  1. Obsidian — 完整 Markdown 归档（通过 REST API）
  2. Qdrant V3 — 每轮 Q&A 向量记忆（通过 HTTP API）
  3. Graphiti — 会话摘要知识图谱（通过 MCP HTTP）

可靠性：3 次重试 + pending 暂存 + 自动补推，三目标独立互不阻塞。
"""

import hashlib
import json
import sys
import os
import re
import ssl
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ===== 配置 =====
# Obsidian
OBSIDIAN_VAULT_PATH = "会话记录"
OBSIDIAN_API_URL = "https://localhost:27124"
OBSIDIAN_API_KEY = os.environ.get("OBSIDIAN_API_KEY", "")

# Embedding backend 切换:
#   local (默认): 本地 MLX daemon, 4096 维, collection=unified_memories_v3_local
#   dashscope   : 阿里云 v4, 1024 维, collection=unified_memories_v3
EMBED_BACKEND = os.environ.get("EMBED_BACKEND", "local").lower()

# Qdrant V3
QDRANT_URL = "http://localhost:6333"
if EMBED_BACKEND == "local":
    COLLECTION_NAME = "unified_memories_v3_local"
    VECTOR_DIM = 4096
elif EMBED_BACKEND == "dashscope":
    COLLECTION_NAME = "unified_memories_v3"
    VECTOR_DIM = 1024
else:
    raise ValueError(f"未知 EMBED_BACKEND: {EMBED_BACKEND}")

# Graphiti
GRAPHITI_URL = "http://localhost:18001/mcp"

# Embedding
EMBEDDING_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
LOCAL_EMBED_URL = os.environ.get("LOCAL_EMBED_URL", "http://127.0.0.1:8765/embed")

# 本地
LOCAL_DATA_DIR = Path.home() / ".claude" / "scripts" / "hooks" / ".obsidian-session-data"
PENDING_DIR = LOCAL_DATA_DIR / "pending"
TRANSCRIPTS_DIR = Path.home() / ".claude" / "projects" / "-Users-YOUR_USERNAME"

# 通用
CHINA_TZ = timezone(timedelta(hours=8))
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1

# Obsidian REST API 自签名证书
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# 分类 → 重要性映射
CATEGORY_IMPORTANCE = {
    "project": "high", "architecture": "high", "solution": "high",
    "preference": "high", "debug": "high", "feedback": "high",
    "decision": "high", "summary": "high", "fact": "medium",
    "general": "medium", "other": "low", "conversation": "low",
}


# ===== HTTP 工具 =====

def http_request(url: str, data: bytes | None = None, headers: dict | None = None,
                 method: str = "GET", timeout: int = 15,
                 use_ssl_ctx: bool = False) -> tuple[int, str, dict]:
    """通用 HTTP 请求，返回 (status, body, response_headers)"""
    req = urllib.request.Request(url, data=data, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    ctx = _SSL_CTX if (use_ssl_ctx or url.startswith("https://")) else None
    resp = urllib.request.urlopen(req, context=ctx, timeout=timeout)
    body = resp.read().decode("utf-8")
    resp_headers = {k.lower(): v for k, v in resp.headers.items()}
    return resp.status, body, resp_headers


def http_retry(url: str, data: bytes | None = None, headers: dict | None = None,
               method: str = "PUT", timeout: int = 15,
               use_ssl_ctx: bool = False, label: str = "") -> bool:
    """带重试的 HTTP 请求，返回是否成功"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            status, _, _ = http_request(url, data, headers, method, timeout, use_ssl_ctx)
            return 200 <= status < 300
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            else:
                print(f"⚠️ {label} 失败 ({MAX_RETRIES}次重试): {e}", file=sys.stderr)
                return False
    return False


# ===== Obsidian API =====

def obsidian_available() -> bool:
    try:
        http_request(f"{OBSIDIAN_API_URL}/", timeout=5, use_ssl_ctx=True)
        return True
    except Exception:
        return False


def obsidian_put(vault_path: str, content: str) -> bool:
    url = f"{OBSIDIAN_API_URL}/vault/{urllib.request.quote(vault_path, safe='/')}"
    return http_retry(url, content.encode("utf-8"),
                      {"Authorization": f"Bearer {OBSIDIAN_API_KEY}",
                       "Content-Type": "text/markdown"},
                      "PUT", 15, True, f"Obsidian PUT {vault_path}")


def obsidian_delete(vault_path: str) -> bool:
    url = f"{OBSIDIAN_API_URL}/vault/{urllib.request.quote(vault_path, safe='/')}"
    try:
        http_request(url, method="DELETE",
                     headers={"Authorization": f"Bearer {OBSIDIAN_API_KEY}"},
                     timeout=10, use_ssl_ctx=True)
        return True
    except Exception:
        return False


# ===== Qdrant API =====

def qdrant_available() -> bool:
    try:
        status, body, _ = http_request(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}", timeout=5)
        return status == 200
    except Exception:
        return False


def _get_embeddings_local(texts: list[str]) -> list[list[float]] | None:
    """本地 MLX daemon 单条调用,循环处理。"""
    all_embeddings: list[list[float]] = []
    for text in texts:
        payload = json.dumps({"text": text, "text_type": "document"}).encode("utf-8")
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                _, body, _ = http_request(
                    LOCAL_EMBED_URL, payload,
                    {"Content-Type": "application/json"}, "POST", 60)
                all_embeddings.append(json.loads(body)["embedding"])
                break
            except Exception as e:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
                else:
                    print(f"⚠️ 本地 daemon embedding 失败: {e}", file=sys.stderr)
                    return None
    return all_embeddings


def _get_embeddings_dashscope(texts: list[str]) -> list[list[float]] | None:
    """批量调用阿里云 text-embedding-v4 生成向量"""
    if not DASHSCOPE_API_KEY:
        return None
    all_embeddings = []
    batch_size = 6
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        payload = json.dumps({
            "model": "text-embedding-v4",
            "input": batch,
            "dimensions": VECTOR_DIM,
            "encoding_format": "float",
        }).encode("utf-8")

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                _, body, _ = http_request(
                    EMBEDDING_API_URL, payload,
                    {"Authorization": f"Bearer {DASHSCOPE_API_KEY}",
                     "Content-Type": "application/json"},
                    "POST", 30)
                resp = json.loads(body)
                # 按 index 排序确保顺序正确
                sorted_data = sorted(resp["data"], key=lambda x: x["index"])
                all_embeddings.extend([d["embedding"] for d in sorted_data])
                break
            except Exception as e:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
                else:
                    print(f"⚠️ Embedding API 失败: {e}", file=sys.stderr)
                    return None
    return all_embeddings


def get_embeddings_batch(texts: list[str]) -> list[list[float]] | None:
    if EMBED_BACKEND == "local":
        return _get_embeddings_local(texts)
    return _get_embeddings_dashscope(texts)


def make_point_id(content: str) -> str:
    """生成 Qdrant point ID（MD5 → UUID 格式）"""
    md5_bytes = hashlib.md5(content.encode("utf-8")).digest()
    return str(uuid.UUID(bytes=md5_bytes))


def qdrant_upsert(points: list[dict]) -> bool:
    """批量写入 Qdrant"""
    if not points:
        return True
    payload = json.dumps({"points": points}).encode("utf-8")
    return http_retry(
        f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points",
        payload, {"Content-Type": "application/json"},
        "PUT", 30, False, "Qdrant upsert")


def write_rounds_to_qdrant(messages: list[dict], first_ts: str | None) -> bool:
    """将每轮 Q&A 写入 Qdrant 向量记忆

    配对逻辑：将一个 user 消息后的所有 assistant 消息合并为一轮。
    遇到下一个 user 消息时，先保存当前积累的轮次，再开始新轮。
    """
    rounds = []
    current_user = None
    assistant_parts: list[str] = []

    def _flush_round() -> None:
        """将积累的 user + assistant_parts 保存为一轮"""
        if current_user and assistant_parts:
            user_text = current_user["text"][:1000]
            merged = "\n\n".join(assistant_parts)[:4000]
            content = f"[问] {user_text}\n[答] {merged}"
            rounds.append({
                "content": content,
                "timestamp": current_user.get("timestamp", ""),
            })

    for m in messages:
        if m["role"] == "user":
            _flush_round()
            current_user = m
            assistant_parts = []
        elif m["role"] == "assistant" and current_user and m["text"]:
            assistant_parts.append(m["text"])

    _flush_round()  # 最后一轮

    if not rounds:
        return True

    # 批量生成向量
    texts = [r["content"] for r in rounds]
    embeddings = get_embeddings_batch(texts)
    if not embeddings:
        return False

    # 构建日期 tag
    try:
        dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00")).astimezone(CHINA_TZ)
        date_tag = dt.strftime("%Y-%m-%d")
    except Exception:
        date_tag = datetime.now(CHINA_TZ).strftime("%Y-%m-%d")

    # 构建 points
    now_iso = datetime.now(CHINA_TZ).isoformat()
    points = []
    for i, (r, emb) in enumerate(zip(rounds, embeddings)):
        points.append({
            "id": make_point_id(r["content"]),
            "vector": emb,
            "payload": {
                "content": r["content"],
                "category": "conversation",
                "tags": f"{date_tag},qa-hook,round-{i+1}",
                "importance": "low",
                "source": "claude_code",
                "created_at": now_iso,
                "timestamp": int(time.time()),
                "version": "v3",
            },
        })

    return qdrant_upsert(points)


# ===== Graphiti API =====

def graphiti_available() -> bool:
    try:
        http_request(f"http://localhost:18001/mcp", timeout=5,
                     data=json.dumps({
                         "jsonrpc": "2.0", "id": 0, "method": "initialize",
                         "params": {
                             "protocolVersion": "2024-11-05",
                             "capabilities": {"tools": {}},
                             "clientInfo": {"name": "health-check", "version": "1.0"},
                         }
                     }).encode("utf-8"),
                     headers={"Content-Type": "application/json",
                              "Accept": "application/json, text/event-stream"},
                     method="POST")
        return True
    except Exception:
        return False


def parse_sse(text: str) -> list[dict]:
    """解析 SSE 格式响应"""
    msgs = []
    for line in text.splitlines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if data:
                try:
                    msgs.append(json.loads(data))
                except Exception:
                    pass
    return msgs


def write_session_to_graphiti(messages: list[dict],
                              first_ts: str | None, last_ts: str | None) -> bool:
    """将会话摘要写入 Graphiti 知识图谱"""
    # 构建摘要
    user_msgs = [m for m in messages if m["role"] == "user"]
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]

    # 取前 3 轮的摘要
    summary_parts = []
    round_idx = 0
    current_user = None
    for m in messages:
        if m["role"] == "user":
            current_user = m
        elif m["role"] == "assistant" and current_user:
            round_idx += 1
            if round_idx <= 3:
                q = current_user["text"][:200]
                a = m["text"][:300]
                summary_parts.append(f"Round {round_idx}: [问] {q}\n[答] {a}")
            current_user = None

    if round_idx > 3:
        summary_parts.append(f"... 共 {round_idx} 轮对话")

    try:
        dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00")).astimezone(CHINA_TZ)
        date_str = dt.strftime("%Y-%m-%d")
    except Exception:
        date_str = datetime.now(CHINA_TZ).strftime("%Y-%m-%d")

    topic = extract_topic(messages)
    episode_body = "\n\n".join(summary_parts)
    name = f"[{date_str}] {topic}"

    # Step 1: Initialize MCP session
    try:
        init_payload = json.dumps({
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "session-hook", "version": "1.0"},
            }
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }

        _, body, resp_headers = http_request(
            GRAPHITI_URL, init_payload, headers, "POST", 15)
        session_id = resp_headers.get("mcp-session-id", "")

        if not session_id:
            # 尝试从 SSE body 解析
            parsed = parse_sse(body)
            if not parsed:
                print("⚠️ Graphiti: 无法获取 session ID", file=sys.stderr)
                return False
    except Exception as e:
        print(f"⚠️ Graphiti initialize 失败: {e}", file=sys.stderr)
        return False

    # Step 2: Call add_memory
    try:
        call_payload = json.dumps({
            "jsonrpc": "2.0",
            "id": "add_memory",
            "method": "tools/call",
            "params": {
                "name": "add_memory",
                "arguments": {
                    "name": name[:200],
                    "episode_body": episode_body[:5000],
                    "group_id": "claude_code",
                    "source": "text",
                    "source_description": "session-to-obsidian hook",
                },
            },
        }).encode("utf-8")

        headers["Mcp-Session-Id"] = session_id
        _, body, _ = http_request(GRAPHITI_URL, call_payload, headers, "POST", 30)
        return True
    except Exception as e:
        print(f"⚠️ Graphiti add_memory 失败: {e}", file=sys.stderr)
        return False


# ===== 转录解析 =====

def find_latest_transcript() -> Path | None:
    jsonl_files = list(TRANSCRIPTS_DIR.glob("*.jsonl"))
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda f: f.stat().st_mtime)


def parse_transcript(filepath: Path) -> tuple[list, str | None, str | None, str | None]:
    messages = []
    session_id = None
    first_ts = None
    last_ts = None

    with open(filepath) as f:
        for line in f:
            try:
                d = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            msg_type = d.get("type")
            timestamp = d.get("timestamp", "")

            if msg_type == "user" and d.get("userType") == "external":
                if not session_id:
                    session_id = d.get("sessionId", "")
                if not first_ts and timestamp:
                    first_ts = timestamp

                content = d["message"].get("content", "")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    parts = []
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            parts.append(c.get("text", ""))
                        elif isinstance(c, dict) and c.get("type") == "image":
                            parts.append("[图片]")
                    text = "\n".join(parts)
                else:
                    text = str(content)

                text = re.sub(r"<system-reminder>[\s\S]*?</system-reminder>", "", text)
                text = re.sub(r"<local-command-caveat>[\s\S]*?</local-command-caveat>", "", text)
                text = re.sub(r"<command-name>[\s\S]*?</command-name>", "", text)
                text = re.sub(r"<command-message>[\s\S]*?</command-message>", "", text)
                text = re.sub(r"<command-args>[\s\S]*?</command-args>", "", text)
                text = re.sub(r"<local-command-stdout>[\s\S]*?</local-command-stdout>", "", text)
                text = re.sub(r"<task-notification>[\s\S]*?</task-notification>", "", text)
                text = text.strip()

                if not text:
                    continue

                skip_patterns = [
                    r"^Base directory for this skill:",
                    r"^This session is being continued from",
                    r"^<context-window-compacted>",
                    r"^Tool loaded\.$",
                    r"^Human:",
                ]
                if any(re.match(p, text) for p in skip_patterns):
                    continue

                messages.append({"role": "user", "text": text, "timestamp": timestamp})
                last_ts = timestamp

            elif msg_type == "assistant":
                content_items = d["message"].get("content", [])
                parts = []
                tools_used = []

                for c in content_items:
                    if not isinstance(c, dict):
                        continue
                    ct = c.get("type")
                    if ct == "text":
                        t = c.get("text", "").strip()
                        if t:
                            parts.append(t)
                    elif ct == "tool_use":
                        tool_name = c.get("name", "unknown")
                        tool_input = c.get("input", {})
                        if tool_name in ("Read", "Glob", "Grep"):
                            param = tool_input.get("file_path") or tool_input.get("pattern") or tool_input.get("path", "")
                            tools_used.append(f"`{tool_name}`: {param}")
                        elif tool_name == "Bash":
                            cmd = tool_input.get("command", "")
                            if len(cmd) > 120:
                                cmd = cmd[:120] + "..."
                            tools_used.append(f"`Bash`: `{cmd}`")
                        elif tool_name == "Edit":
                            tools_used.append(f"`Edit`: {tool_input.get('file_path', '')}")
                        elif tool_name == "Write":
                            tools_used.append(f"`Write`: {tool_input.get('file_path', '')}")
                        elif tool_name.startswith("mcp__"):
                            tools_used.append(f"`{tool_name.split('__')[-1]}`")
                        else:
                            tools_used.append(f"`{tool_name}`")

                text = "\n\n".join(parts)
                if not text and not tools_used:
                    continue

                msg = {"role": "assistant", "text": text, "timestamp": timestamp}
                if tools_used:
                    msg["tools"] = tools_used
                messages.append(msg)
                last_ts = timestamp

    return messages, session_id, first_ts, last_ts


# ===== 格式化 =====

def extract_topic(messages: list) -> str:
    for m in messages:
        if m["role"] == "user":
            text = m["text"].replace("\n", " ").strip()
            if len(text) > 40:
                text = text[:40]
            text = re.sub(r'[/\\:*?"<>|]', "", text)
            if text:
                return text
    return "未命名会话"


def format_timestamp(ts_str: str) -> str:
    if not ts_str:
        return ""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(CHINA_TZ)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts_str[:19]


def format_datetime(ts_str: str) -> str:
    if not ts_str:
        return ""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(CHINA_TZ)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ts_str[:19]


def generate_markdown(messages: list, session_id: str | None,
                      first_ts: str | None, last_ts: str | None, filepath: Path) -> str:
    topic = extract_topic(messages)
    user_count = sum(1 for m in messages if m["role"] == "user")
    assistant_count = sum(1 for m in messages if m["role"] == "assistant")

    lines = [f"# {topic}", "",
             f"> 时间：{format_datetime(first_ts)} ~ {format_datetime(last_ts)}",
             f"> 轮数：用户 {user_count} 轮，Claude {assistant_count} 轮",
             f"> 来源：`{filepath.name}`"]
    if session_id:
        lines.append(f"> Session：`{session_id[:12]}...`")
    lines.extend(["", "---", ""])

    round_num = 0
    for m in messages:
        ts = format_timestamp(m["timestamp"])
        if m["role"] == "user":
            round_num += 1
            text = m["text"][:2000]
            if len(m["text"]) > 2000:
                text += "\n\n... (已截断)"
            lines.extend([f"## Round {round_num}", "", f"**用户** `{ts}`", "", text, ""])
        elif m["role"] == "assistant":
            lines.extend([f"**Claude** `{ts}`", ""])
            if m.get("tools"):
                lines.extend(["<details><summary>工具调用</summary>", ""])
                lines.extend([f"- {t}" for t in m["tools"]])
                lines.extend(["", "</details>", ""])
            text = m["text"][:3000]
            if len(m["text"]) > 3000:
                text += "\n\n... (已截断)"
            if text:
                lines.append(text)
            lines.extend(["", "---", ""])

    return "\n".join(lines)


# ===== 映射 + 暂存 =====

def load_mapping() -> dict:
    mapping_file = LOCAL_DATA_DIR / "session_mapping.json"
    if not mapping_file.exists():
        return {}
    try:
        return json.loads(mapping_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_mapping(stem: str, **kwargs) -> None:
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    mapping = load_mapping()
    if stem not in mapping:
        mapping[stem] = {}
    mapping[stem].update(kwargs)
    (LOCAL_DATA_DIR / "session_mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2)
    )


def save_to_pending(filename: str, content: str, stem: str, mtime: float) -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "filename": filename, "stem": stem, "mtime": mtime,
        "content": content,
        "created": datetime.now(CHINA_TZ).isoformat(),
    }
    (PENDING_DIR / f"{stem}.json").write_text(
        json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    print(f"📦 已暂存到本地待推送队列: {filename}", file=sys.stderr)


def flush_pending(obsidian_ok: bool) -> int:
    if not PENDING_DIR.exists():
        return 0
    pending_files = list(PENDING_DIR.glob("*.json"))
    if not pending_files:
        return 0

    flushed = 0
    for pf in pending_files:
        try:
            entry = json.loads(pf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pf.unlink(missing_ok=True)
            continue

        if not obsidian_ok:
            continue

        vault_path = f"{OBSIDIAN_VAULT_PATH}/{entry['filename']}"
        if obsidian_put(vault_path, entry["content"]):
            save_mapping(entry["stem"], filename=entry["filename"], mtime=entry["mtime"])
            pf.unlink(missing_ok=True)
            flushed += 1
            print(f"  补推成功: {entry['filename']}", file=sys.stderr)
        else:
            print(f"  ⚠️ 补推仍失败: {entry['filename']}", file=sys.stderr)
    return flushed


# ===== 核心处理 =====

def process_one(transcript: Path,
                obsidian_ok: bool, qdrant_ok: bool, graphiti_ok: bool) -> str | None:
    """处理单个转录文件，写入三个目标"""
    mapping = load_mapping()
    entry = mapping.get(transcript.stem, {})
    transcript_mtime = transcript.stat().st_mtime

    # 检查各目标是否需要处理
    obsidian_done = entry.get("mtime", 0) >= transcript_mtime
    qdrant_done = entry.get("qdrant_done", False) and obsidian_done
    graphiti_done = entry.get("graphiti_done", False) and obsidian_done

    if obsidian_done and qdrant_done and graphiti_done:
        return None  # 全部已完成

    # 解析转录
    messages, session_id, first_ts, last_ts = parse_transcript(transcript)
    if not messages or len(messages) < 2:
        return None

    topic = extract_topic(messages)
    try:
        dt = datetime.fromisoformat(first_ts.replace("Z", "+00:00")).astimezone(CHINA_TZ)
        date_prefix = dt.strftime("%Y-%m-%d_%H%M%S")
    except Exception:
        date_prefix = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    filename = f"{date_prefix}_{topic}.md"
    result_parts = []

    # ── Obsidian ──
    if not obsidian_done:
        vault_path = f"{OBSIDIAN_VAULT_PATH}/{filename}"
        old_filename = entry.get("filename")

        if old_filename and old_filename != filename:
            obsidian_delete(f"{OBSIDIAN_VAULT_PATH}/{old_filename}")

        md = generate_markdown(messages, session_id, first_ts, last_ts, transcript)

        if not obsidian_ok:
            save_to_pending(filename, md, transcript.stem, transcript_mtime)
        elif obsidian_put(vault_path, md):
            save_mapping(transcript.stem, filename=filename, mtime=transcript_mtime)
            is_update = "filename" in entry
            result_parts.append(f"Obsidian{'(更新)' if is_update else ''}")
        else:
            save_to_pending(filename, md, transcript.stem, transcript_mtime)

    # ── Qdrant ──
    if not qdrant_done and qdrant_ok:
        if write_rounds_to_qdrant(messages, first_ts):
            save_mapping(transcript.stem, qdrant_done=True)
            result_parts.append("Qdrant")
        else:
            print(f"  ⚠️ Qdrant 写入失败: {filename}", file=sys.stderr)

    # ── Graphiti ──
    if not graphiti_done and graphiti_ok:
        if write_session_to_graphiti(messages, first_ts, last_ts):
            save_mapping(transcript.stem, graphiti_done=True)
            result_parts.append("Graphiti")
        else:
            print(f"  ⚠️ Graphiti 写入失败: {filename}", file=sys.stderr)

    if result_parts:
        targets = "+".join(result_parts)
        return f"{filename} [{targets}]"
    return None


def main():
    if not OBSIDIAN_API_KEY:
        print("⚠️ OBSIDIAN_API_KEY 未设置，跳过归档", file=sys.stderr)
        sys.exit(0)

    scan_all = "--scan-all" in sys.argv

    # 检测各服务可用性
    obsidian_ok = obsidian_available()
    qdrant_ok = qdrant_available()
    graphiti_ok = graphiti_available()

    status = []
    if not obsidian_ok:
        status.append("Obsidian❌")
    if not qdrant_ok:
        status.append("Qdrant❌")
    if not graphiti_ok:
        status.append("Graphiti❌")
    if status:
        print(f"⚠️ 服务不可用: {', '.join(status)}", file=sys.stderr)

    if scan_all:
        # 先补推 Obsidian pending
        if obsidian_ok:
            flushed = flush_pending(obsidian_ok)
            if flushed:
                print(f"补推暂存队列: {flushed} 个成功", file=sys.stderr)

        # 扫描所有 JSONL
        jsonl_files = sorted(TRANSCRIPTS_DIR.glob("*.jsonl"),
                             key=lambda f: f.stat().st_mtime)
        processed = 0
        for transcript in jsonl_files:
            result = process_one(transcript, obsidian_ok, qdrant_ok, graphiti_ok)
            if result:
                print(f"  归档: {result}", file=sys.stderr)
                processed += 1

        pending_count = len(list(PENDING_DIR.glob("*.json"))) if PENDING_DIR.exists() else 0
        msg = f"扫描完成: {len(jsonl_files)} 个会话, 新归档 {processed} 个"
        if pending_count:
            msg += f", 待推送 {pending_count} 个"
        print(msg, file=sys.stderr)

    else:
        # SessionEnd: 只处理最新的
        transcript = find_latest_transcript()
        if not transcript:
            sys.exit(0)
        result = process_one(transcript, obsidian_ok, qdrant_ok, graphiti_ok)
        if result:
            print(f"Session saved: {result}", file=sys.stderr)
        elif not obsidian_ok:
            print("⚠️ 已暂存，下次启动时自动补推", file=sys.stderr)


if __name__ == "__main__":
    main()
