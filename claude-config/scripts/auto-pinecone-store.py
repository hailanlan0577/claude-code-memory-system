#!/usr/bin/env /Users/YOUR_USERNAME/mcp-qdrant-memory/venv/bin/python
"""
Stop Hook - Auto store ALL conversation exchanges to Qdrant V3.
已从 Pinecone+Mem0 迁移到 Qdrant V3 (text-embedding-v4, unified_memories_v3).
"""

import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# === Config ===
MAX_CONTENT_LEN = 1500
MIN_USER_MSG_LEN = 3
STATE_DIR = Path.home() / ".claude" / "scripts" / "hooks" / ".store-state"
RECORD_QA_PYTHON = "/Users/YOUR_USERNAME/mcp-qdrant-memory/venv/bin/python"
RECORD_QA_SCRIPT = "/Users/YOUR_USERNAME/mcp-qdrant-memory/record_qa.py"
DASHSCOPE_API_KEY = "YOUR_DASHSCOPE_API_KEY"
GRAPHITI_BASE = "http://localhost:18001"

TRIVIAL_PATTERNS = [
    # 单词问候/确认
    r"^(你好|hello|hi|hey|谢谢|thanks|thank you|ok|好的|明白|嗯|对|是的|好|哦|啊|噢|行|对的|没问题|知道了|收到|好的好的|好好|可以|继续|go|yes|no|nope|yep|sure)[\s!！。.\?？]*$",
    # 纯数字/符号
    r"^[\d\s\.,!?！？。，、\-_]+$",
    # 短重复词
    r"^(.)\1{2,}$",
    # 纯表情或很短的无意义内容
    r"^[\U0001F300-\U0001FFFF\s]{1,5}$",
    # 只是让继续的指令
    r"^(继续|continue|next|下一步|下一个|再来|再说|往下|proceed)[\s!！。]*$",
    # 图片/文件消息占位
    r"^\[图片\]|\[文件\]|\[语音\]|\[视频\]",
    # system-reminder 残留
    r"^\s*$",
]


def log(msg):
    print(f"[AutoRecord-V3] {msg}", file=sys.stderr)


def get_transcript_path():
    try:
        data = sys.stdin.read(1024 * 1024)
        parsed = json.loads(data)
        return parsed.get("transcript_path")
    except Exception:
        return None


def parse_all_exchanges(transcript_path):
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        log(f"Failed to read transcript: {e}")
        return []

    messages = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue

        role = entry.get("type") or entry.get("role")
        content = entry.get("content", "")

        msg = entry.get("message", {})
        if isinstance(msg, dict) and msg.get("role"):
            role = msg.get("role")
            content = msg.get("content", "")

        if not role or role not in ("user", "assistant"):
            if entry.get("type") == "tool_use" or entry.get("tool_name"):
                name = entry.get("tool_name") or entry.get("name", "")
                if name and messages and messages[-1][0] == "assistant":
                    messages[-1][2].add(name)
            continue

        text = ""
        tools = set()
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    if c.get("type") == "text":
                        parts.append(c.get("text", ""))
                    elif c.get("type") == "tool_use":
                        tools.add(c.get("name", ""))
            text = " ".join(parts).strip()

        if not text:
            if role == "assistant" and tools:
                if messages and messages[-1][0] == "assistant":
                    messages[-1][2].update(tools)
                else:
                    messages.append((role, "", tools))
            continue

        if role == "user":
            text = re.sub(r"<system-reminder>.*?</system-reminder>", "", text, flags=re.DOTALL).strip()
            if not text:
                continue

        if messages and messages[-1][0] == role:
            prev_text = messages[-1][1]
            prev_tools = messages[-1][2]
            prev_tools.update(tools)
            messages[-1] = (role, prev_text + "\n" + text if prev_text else text, prev_tools)
        else:
            messages.append((role, text, tools))

    exchanges = []
    i = 0
    while i < len(messages):
        if messages[i][0] == "user":
            user_text = messages[i][1]
            assistant_text = ""
            tools = set()
            if i + 1 < len(messages) and messages[i + 1][0] == "assistant":
                assistant_text = messages[i + 1][1]
                tools = messages[i + 1][2]
                i += 2
            else:
                i += 1
                continue

            if user_text and assistant_text:
                exchanges.append({
                    "user": user_text[:MAX_CONTENT_LEN],
                    "assistant": assistant_text[:MAX_CONTENT_LEN],
                    "tools": list(tools),
                })
        else:
            i += 1

    return exchanges


def should_skip(user_msg):
    if len(user_msg.strip()) < MIN_USER_MSG_LEN:
        return True
    for pat in TRIVIAL_PATTERNS:
        if re.match(pat, user_msg.strip(), re.IGNORECASE):
            return True
    return False


def get_exchange_id(exchange, index):
    raw = f"{index}:{exchange['user'][:200]}:{exchange['assistant'][:200]}"
    return hashlib.md5(raw.encode()).hexdigest()


def load_state(transcript_path):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / (hashlib.md5(transcript_path.encode()).hexdigest() + ".json")
    try:
        with open(state_file, "r") as f:
            return set(json.load(f).get("stored_ids", []))
    except Exception:
        return set()


def save_state(transcript_path, stored_ids):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / (hashlib.md5(transcript_path.encode()).hexdigest() + ".json")
    with open(state_file, "w") as f:
        json.dump({"stored_ids": list(stored_ids), "updated": datetime.now().isoformat()}, f)


def store_to_qdrant_v3(user_msg, assistant_msg, tags_list):
    """调用 record_qa.py 写入 Qdrant V3 (unified_memories_v3)."""
    try:
        env = os.environ.copy()
        env["DASHSCOPE_API_KEY"] = DASHSCOPE_API_KEY
        env["NO_PROXY"] = "localhost,127.0.0.1"

        tags_str = ",".join(tags_list)
        result = subprocess.run(
            [RECORD_QA_PYTHON, RECORD_QA_SCRIPT,
             user_msg, assistant_msg,
             "conversation",
             tags_str],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True
        else:
            log(f"record_qa.py error: {result.stderr.strip()}")
            return False
    except Exception as e:
        log(f"Qdrant V3 store failed: {e}")
        return False


def store_to_graphiti(content, name):
    """通过 SSE 协议调用 Graphiti MCP add_memory（fire-and-forget）."""
    try:
        import httpx
        q = queue.Queue()
        stop_evt = threading.Event()

        def sse_keep_alive():
            try:
                with httpx.Client(timeout=None, trust_env=False) as c:
                    with c.stream("GET", f"{GRAPHITI_BASE}/sse") as r:
                        for line in r.iter_lines():
                            if line.startswith("data:"):
                                session_url = GRAPHITI_BASE + line[5:].strip()
                                q.put(session_url)
                                stop_evt.wait(15)
                                break
            except Exception as e:
                q.put(None)

        t = threading.Thread(target=sse_keep_alive, daemon=True)
        t.start()

        session_url = q.get(timeout=5)
        if not session_url:
            log("Graphiti: failed to get session URL")
            return False

        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {
                "name": "add_memory",
                "arguments": {
                    "name": name,
                    "episode_body": content,
                    "group_id": "claude_code"
                }
            }
        }
        with httpx.Client(timeout=10, trust_env=False) as c:
            r = c.post(session_url, json=payload)
            stop_evt.set()
            if r.status_code == 202:
                return True
            log(f"Graphiti: unexpected status {r.status_code}")
            return False
    except Exception as e:
        log(f"Graphiti store failed: {e}")
        return False


DEBUG_KEYWORDS = ["修复", "bug", "fixed", "根因", "报错", "错误", "失败", "traceback",
                  "exception", "error", "fix", "解决了", "问题出在", "原因是", "调试"]
FEEDBACK_KEYWORDS = ["用户纠正", "不对", "重新", "你理解错了", "不应该", "不要这样",
                     "改成", "以后要", "以后不要", "你做错了", "不是这样"]


def detect_and_store_reminders(exchanges, transcript_path):
    """扫描交换内容，检测 debug/feedback 信号，存储提醒记忆。"""
    combined = " ".join(
        ex["user"][:300] + " " + ex["assistant"][:300]
        for ex in exchanges
    ).lower()

    has_debug = any(kw.lower() in combined for kw in DEBUG_KEYWORDS)
    has_feedback = any(kw.lower() in combined for kw in FEEDBACK_KEYWORDS)

    if not has_debug and not has_feedback:
        return

    session_id = hashlib.md5(transcript_path.encode()).hexdigest()[:8]
    today = datetime.now().strftime("%Y-%m-%d")

    if has_debug:
        reminder = (
            f"[自检提醒 {today}] Stop Hook 检测到本次会话含 debug/修复 相关内容（session {session_id}）。"
            f"请确认已存储 debug 分类记忆（CLAUDE.md 规范：每次 bug 修复必存1条）。"
        )
        store_to_qdrant_v3(
            f"[自动检测] 会话 {session_id} 发现疑似 bug 修复内容",
            reminder,
            [today, "hook", "debug-reminder", "source:claude_code"]
        )
        log(f"⚠️  检测到 debug 信号，已存储提醒记忆")

    if has_feedback:
        reminder = (
            f"[自检提醒 {today}] Stop Hook 检测到本次会话含用户纠正相关内容（session {session_id}）。"
            f"请确认已存储 feedback 分类记忆（CLAUDE.md 规范：每次用户纠正必存1条）。"
        )
        store_to_qdrant_v3(
            f"[自动检测] 会话 {session_id} 发现疑似用户纠正内容",
            reminder,
            [today, "hook", "feedback-reminder", "source:claude_code"]
        )
        log(f"⚠️  检测到 feedback 信号，已存储提醒记忆")


def clean_old_state_files():
    if not STATE_DIR.exists():
        return
    cutoff = time.time() - 7 * 24 * 3600
    for f in STATE_DIR.glob("*.json"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except Exception:
            pass


def main():
    transcript_path = get_transcript_path()
    if not transcript_path:
        log("No transcript_path received")
        return

    exchanges = parse_all_exchanges(transcript_path)
    if not exchanges:
        return

    stored_ids = load_state(transcript_path)
    today = datetime.now().strftime("%Y-%m-%d")
    new_count = 0

    for i, ex in enumerate(exchanges):
        eid = get_exchange_id(ex, i)

        if eid in stored_ids:
            continue

        if should_skip(ex["user"]):
            stored_ids.add(eid)
            continue

        tags = [today, "hook", "source:claude_code"]
        skip_tools = {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent", "ToolSearch"}
        for t in ex["tools"]:
            if t not in skip_tools:
                tags.append(t)
        tags = tags[:8]

        ok = store_to_qdrant_v3(ex["user"], ex["assistant"], tags)
        if ok:
            stored_ids.add(eid)
            new_count += 1
            log(f"Qdrant V3 stored exchange #{i+1}")
        else:
            log(f"Qdrant V3 failed exchange #{i+1}, will retry next session")

        # Graphiti: best-effort，失败不阻塞
        today_str = datetime.now().strftime("%Y-%m-%d")
        graphiti_name = f"[{today_str}] hook exchange #{i+1}"
        graphiti_body = f"用户: {ex['user']}\n\nClaude: {ex['assistant']}"
        if store_to_graphiti(graphiti_body, graphiti_name):
            log(f"Graphiti stored exchange #{i+1}")
        else:
            log(f"Graphiti skipped exchange #{i+1} (offline or error)")

    save_state(transcript_path, stored_ids)
    clean_old_state_files()

    # S6: debug/feedback 分类自检
    if exchanges:
        detect_and_store_reminders(exchanges, transcript_path)

    if new_count > 0:
        log(f"Stored {new_count} new exchange(s) to Qdrant V3 + Graphiti ({len(exchanges)} total in transcript)")
    else:
        log(f"No new exchanges ({len(exchanges)} total, all already recorded)")


if __name__ == "__main__":
    main()
