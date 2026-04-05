#!/usr/bin/env python3
"""
Obsidian Vault → Qdrant V3 + Graphiti 自动同步

将 Obsidian vault 中非「会话记录」的 .md 文件同步到 Qdrant 向量数据库和 Graphiti 知识图谱。
通过 Obsidian REST API 读取文件（绕过 iCloud 权限限制）。

运行模式：
  无参数    — 扫描一次，只处理新增/修改的文件
  --daemon  — 每小时扫描一次（死循环）
  --full    — 忽略 mapping，全量重新同步

依赖：纯标准库，无第三方依赖。
"""

import hashlib
import json
import os
import ssl
import sys
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ===== 配置 =====

# Obsidian
OBSIDIAN_API_URL = "https://localhost:27124"
OBSIDIAN_API_KEY = os.environ.get("OBSIDIAN_API_KEY", "")

# Qdrant V3
QDRANT_URL = "http://localhost:6333"
COLLECTION_NAME = "unified_memories_v3"
VECTOR_DIM = 1024

# Graphiti
GRAPHITI_URL = "http://localhost:18001/mcp"

# Embedding
EMBEDDING_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")

# 本地
LOCAL_DATA_DIR = Path.home() / ".claude" / "scripts" / "hooks" / ".obsidian-session-data"
MAPPING_FILE = LOCAL_DATA_DIR / "obsidian_sync_mapping.json"

# 通用
CHINA_TZ = timezone(timedelta(hours=8))
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1
DAEMON_INTERVAL = 300  # 每5分钟
MIN_CONTENT_LENGTH = 50  # 太短的文件不同步
MAX_CHUNK_CHARS = 4000

# SSL 自签名证书
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

# 跳过的文件夹
SKIP_FOLDERS = {"会话记录"}

# 文件夹 → Qdrant 分类映射
FOLDER_CATEGORY = {
    "二奢软件": "project",
    "复盘": "debug",
    "故障复盘": "debug",
    "Design": "architecture",
    "工具": "project",
    "exports": "project",
}
DEFAULT_CATEGORY = "project"

# 分类 → 重要性
CATEGORY_IMPORTANCE = {
    "project": "high",
    "architecture": "high",
    "debug": "high",
}


# ===== HTTP 工具 =====

def http_request(url: str, data: bytes | None = None, headers: dict | None = None,
                 method: str = "GET", timeout: int = 15,
                 use_ssl_ctx: bool = False) -> tuple[int, str, dict]:
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
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            status, _, _ = http_request(url, data, headers, method, timeout, use_ssl_ctx)
            return 200 <= status < 300
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
            else:
                print(f"  ⚠️ {label} 失败 ({MAX_RETRIES}次重试): {e}", file=sys.stderr)
                return False
    return False


# ===== 服务检测 =====

def obsidian_available() -> bool:
    try:
        http_request(f"{OBSIDIAN_API_URL}/", timeout=5, use_ssl_ctx=True)
        return True
    except Exception:
        return False


def qdrant_available() -> bool:
    try:
        status, _, _ = http_request(
            f"{QDRANT_URL}/collections/{COLLECTION_NAME}", timeout=5)
        return status == 200
    except Exception:
        return False


def graphiti_available() -> bool:
    try:
        http_request(
            GRAPHITI_URL, timeout=5,
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


# ===== Obsidian API =====

def obsidian_list_dir(dirpath: str = "") -> list[str]:
    """列出 vault 指定目录下的条目（文件和子目录）"""
    encoded = urllib.request.quote(dirpath, safe="/") if dirpath else ""
    url = f"{OBSIDIAN_API_URL}/vault/{encoded}"
    if not url.endswith("/"):
        url += "/"
    _, body, _ = http_request(
        url,
        headers={"Authorization": f"Bearer {OBSIDIAN_API_KEY}"},
        timeout=15, use_ssl_ctx=True)
    return json.loads(body).get("files", [])


def obsidian_list_files() -> list[str]:
    """递归列出 vault 中所有 .md 文件（排除 SKIP_FOLDERS）"""
    result: list[str] = []
    dirs_to_scan: list[str] = [""]  # 从根目录开始

    while dirs_to_scan:
        current_dir = dirs_to_scan.pop()
        try:
            entries = obsidian_list_dir(current_dir)
        except Exception as e:
            print(f"  ⚠️ 列目录失败 {current_dir or '/'}: {e}", file=sys.stderr)
            continue

        for entry in entries:
            # 拼接完整路径
            full_path = f"{current_dir}{entry}" if current_dir else entry

            if entry.endswith("/"):
                # 子目录：检查是否需要跳过
                folder_name = entry.rstrip("/")
                top_folder = current_dir.split("/")[0] if current_dir else folder_name
                if top_folder in SKIP_FOLDERS:
                    continue
                dirs_to_scan.append(full_path)
            elif entry.endswith(".md"):
                # .md 文件：检查顶级文件夹是否需要跳过
                top_folder = full_path.split("/")[0] if "/" in full_path else ""
                if top_folder in SKIP_FOLDERS:
                    continue
                result.append(full_path)

    return result


def obsidian_get_file(path: str) -> str | None:
    """通过 REST API 读取文件内容"""
    try:
        encoded = urllib.request.quote(path, safe="/")
        _, body, _ = http_request(
            f"{OBSIDIAN_API_URL}/vault/{encoded}",
            headers={"Authorization": f"Bearer {OBSIDIAN_API_KEY}",
                     "Accept": "text/markdown"},
            timeout=15, use_ssl_ctx=True)
        return body
    except Exception as e:
        print(f"  ⚠️ 读取失败 {path}: {e}", file=sys.stderr)
        return None


# ===== Embedding & Qdrant =====

def get_embeddings_batch(texts: list[str]) -> list[list[float]] | None:
    if not DASHSCOPE_API_KEY:
        return None
    all_embeddings: list[list[float]] = []
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
                sorted_data = sorted(resp["data"], key=lambda x: x["index"])
                all_embeddings.extend([d["embedding"] for d in sorted_data])
                break
            except Exception as e:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))
                else:
                    print(f"  ⚠️ Embedding API 失败: {e}", file=sys.stderr)
                    return None
    return all_embeddings


def make_obsidian_point_id(path: str, chunk_index: int) -> str:
    """基于文件路径+分块索引的稳定 ID，同一文件同一位置始终相同"""
    key = f"obsidian:{path}:chunk-{chunk_index}"
    md5_bytes = hashlib.md5(key.encode("utf-8")).digest()
    return str(uuid.UUID(bytes=md5_bytes))


def qdrant_upsert(points: list[dict]) -> bool:
    if not points:
        return True
    payload = json.dumps({"points": points}).encode("utf-8")
    return http_retry(
        f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points",
        payload, {"Content-Type": "application/json"},
        "PUT", 30, False, "Qdrant upsert")


def qdrant_delete_points(point_ids: list[str]) -> bool:
    if not point_ids:
        return True
    payload = json.dumps({"points": point_ids}).encode("utf-8")
    return http_retry(
        f"{QDRANT_URL}/collections/{COLLECTION_NAME}/points/delete",
        payload, {"Content-Type": "application/json"},
        "POST", 15, False, "Qdrant delete")


# ===== Graphiti =====

def parse_sse(text: str) -> list[dict]:
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


def graphiti_init_session() -> str | None:
    """初始化 Graphiti MCP session，返回 session_id"""
    try:
        init_payload = json.dumps({
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "obsidian-sync", "version": "1.0"},
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
            parsed = parse_sse(body)
            if not parsed:
                return None
        return session_id
    except Exception as e:
        print(f"  ⚠️ Graphiti init 失败: {e}", file=sys.stderr)
        return None


def graphiti_add_memory(session_id: str, name: str, body_text: str) -> bool:
    """写入一条记忆到 Graphiti"""
    try:
        call_payload = json.dumps({
            "jsonrpc": "2.0",
            "id": "add_memory",
            "method": "tools/call",
            "params": {
                "name": "add_memory",
                "arguments": {
                    "name": name[:200],
                    "episode_body": body_text[:5000],
                    "group_id": "claude_code",
                    "source": "text",
                    "source_description": "obsidian-sync-qdrant",
                },
            },
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Mcp-Session-Id": session_id,
        }
        http_request(GRAPHITI_URL, call_payload, headers, "POST", 60)
        return True
    except Exception as e:
        print(f"  ⚠️ Graphiti add_memory 失败: {e}", file=sys.stderr)
        return False


# ===== 分类 & 分块 =====

def classify_file(path: str) -> str:
    """根据文件夹判断 Qdrant 分类"""
    if "/" in path:
        top_folder = path.split("/")[0]
        return FOLDER_CATEGORY.get(top_folder, DEFAULT_CATEGORY)
    return DEFAULT_CATEGORY


def split_document(content: str) -> list[str]:
    """将大文档按段落分块，每块不超过 MAX_CHUNK_CHARS"""
    if len(content) <= MAX_CHUNK_CHARS:
        return [content]

    # 按二级标题分割
    sections: list[str] = []
    current: list[str] = []
    for line in content.split("\n"):
        if line.startswith("## ") and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))

    # 贪心合并：将小段合并到 MAX_CHUNK_CHARS 以内
    chunks: list[str] = []
    buffer = ""
    for section in sections:
        if len(section) > MAX_CHUNK_CHARS:
            # 段落本身超长，按空行再分
            if buffer:
                chunks.append(buffer)
                buffer = ""
            paragraphs = section.split("\n\n")
            for para in paragraphs:
                if len(buffer) + len(para) + 2 <= MAX_CHUNK_CHARS:
                    buffer = f"{buffer}\n\n{para}" if buffer else para
                else:
                    if buffer:
                        chunks.append(buffer)
                    # 硬截断
                    if len(para) > MAX_CHUNK_CHARS:
                        for j in range(0, len(para), MAX_CHUNK_CHARS):
                            chunks.append(para[j:j + MAX_CHUNK_CHARS])
                        buffer = ""
                    else:
                        buffer = para
        elif len(buffer) + len(section) + 2 <= MAX_CHUNK_CHARS:
            buffer = f"{buffer}\n\n{section}" if buffer else section
        else:
            if buffer:
                chunks.append(buffer)
            buffer = section
    if buffer:
        chunks.append(buffer)

    return chunks if chunks else [content[:MAX_CHUNK_CHARS]]


# ===== Mapping 管理 =====

def load_mapping() -> dict:
    if MAPPING_FILE.exists():
        return json.loads(MAPPING_FILE.read_text("utf-8"))
    return {}


def save_mapping(mapping: dict) -> None:
    LOCAL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MAPPING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), "utf-8")
    tmp.rename(MAPPING_FILE)


# ===== 核心同步 =====

def content_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def write_file_to_qdrant(path: str, content: str, category: str) -> list[str]:
    """分块写入 Qdrant，返回所有 point ID"""
    chunks = split_document(content)
    total = len(chunks)

    # 构建 embedding 输入
    texts = [f"[Obsidian] {path}\n\n{chunk}" for chunk in chunks]
    embeddings = get_embeddings_batch(texts)
    if not embeddings or len(embeddings) != len(texts):
        return []

    now_iso = datetime.now(CHINA_TZ).isoformat()
    date_tag = datetime.now(CHINA_TZ).strftime("%Y-%m-%d")
    importance = CATEGORY_IMPORTANCE.get(category, "high")

    points = []
    point_ids = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        pid = make_obsidian_point_id(path, i)
        point_ids.append(pid)
        chunk_tag = f"chunk-{i + 1}of{total}" if total > 1 else "full"
        points.append({
            "id": pid,
            "vector": embedding,
            "payload": {
                "content": f"[Obsidian] {path}\n\n{chunk}",
                "category": category,
                "tags": f"{date_tag},obsidian-sync,{path},{chunk_tag}",
                "importance": importance,
                "source": "obsidian_vault",
                "created_at": now_iso,
                "timestamp": int(time.time()),
                "version": "v3",
                "obsidian_path": path,
            },
        })

    if qdrant_upsert(points):
        return point_ids
    return []


def process_file(path: str, content: str, mapping: dict,
                 qdrant_ok: bool, graphiti_ok: bool,
                 graphiti_session: str | None) -> dict | None:
    """处理单个文件，返回更新后的 mapping entry（或 None 表示跳过）"""
    chash = content_hash(content)
    entry = mapping.get(path, {})

    # 内容没变且都已完成 → 跳过
    if (entry.get("content_hash") == chash
            and entry.get("qdrant_done")
            and entry.get("graphiti_done")):
        return None

    category = classify_file(path)
    result = dict(entry)  # 不可变：创建新 dict
    result["content_hash"] = chash
    result["category"] = category
    result["content_length"] = len(content)

    actions = []

    # Qdrant
    if qdrant_ok and (entry.get("content_hash") != chash or not entry.get("qdrant_done")):
        # 先删旧 chunks（内容变化时 chunk 数可能变）
        old_ids = entry.get("qdrant_point_ids", [])
        if old_ids and entry.get("content_hash") != chash:
            qdrant_delete_points(old_ids)

        point_ids = write_file_to_qdrant(path, content, category)
        if point_ids:
            result["qdrant_point_ids"] = point_ids
            result["qdrant_done"] = True
            result["chunk_count"] = len(point_ids)
            actions.append("Qdrant")
        else:
            result["qdrant_done"] = False

    # Graphiti
    if (graphiti_ok and graphiti_session
            and (entry.get("content_hash") != chash or not entry.get("graphiti_done"))):
        filename = path.rsplit("/", 1)[-1].replace(".md", "")
        date_str = datetime.now(CHINA_TZ).strftime("%Y-%m-%d")
        name = f"[{date_str}] [Obsidian] {filename}"
        if graphiti_add_memory(graphiti_session, name, content[:2000]):
            result["graphiti_done"] = True
            actions.append("Graphiti")
        else:
            result["graphiti_done"] = False

    result["synced_at"] = datetime.now(CHINA_TZ).isoformat()

    if actions:
        print(f"  同步: {path} [{'+'.join(actions)}]", file=sys.stderr)
    return result


def handle_deletions(mapping: dict, current_files: set[str], qdrant_ok: bool) -> int:
    """检测已删除文件，从 Qdrant 删除对应记录"""
    deleted_count = 0
    for path in list(mapping.keys()):
        if path in current_files:
            continue
        if mapping[path].get("deleted"):
            continue

        entry = mapping[path]
        if qdrant_ok:
            old_ids = entry.get("qdrant_point_ids", [])
            if old_ids:
                qdrant_delete_points(old_ids)

        mapping[path] = {
            **entry,
            "deleted": True,
            "deleted_at": datetime.now(CHINA_TZ).isoformat(),
            "qdrant_point_ids": [],
        }
        print(f"  删除: {path}", file=sys.stderr)
        deleted_count += 1
    return deleted_count


def sync_once(full: bool = False) -> None:
    """执行一次完整同步"""
    print(f"[{datetime.now(CHINA_TZ).strftime('%H:%M:%S')}] 开始同步...", file=sys.stderr)

    # 服务检测
    if not obsidian_available():
        print("  ⚠️ Obsidian 不可用，跳过", file=sys.stderr)
        return
    qdrant_ok = qdrant_available()
    graphiti_ok = graphiti_available()

    status_parts = []
    if not qdrant_ok:
        status_parts.append("Qdrant❌")
    if not graphiti_ok:
        status_parts.append("Graphiti❌")
    if status_parts:
        print(f"  ⚠️ 服务不可用: {', '.join(status_parts)}", file=sys.stderr)
    if not qdrant_ok and not graphiti_ok:
        print("  ⚠️ Qdrant 和 Graphiti 都不可用，跳过", file=sys.stderr)
        return

    # 列出文件
    try:
        files = obsidian_list_files()
    except Exception as e:
        print(f"  ⚠️ 列出文件失败: {e}", file=sys.stderr)
        return

    print(f"  发现 {len(files)} 个 .md 文件（已排除会话记录）", file=sys.stderr)

    # 加载 mapping
    mapping = load_mapping()
    if full:
        # 全量模式：清空所有 content_hash 强制重检
        for entry in mapping.values():
            entry["content_hash"] = ""
        print("  全量模式：忽略缓存，重新同步所有文件", file=sys.stderr)

    # Graphiti session（整批只初始化一次）
    graphiti_session = graphiti_init_session() if graphiti_ok else None

    # 处理文件
    synced = 0
    skipped = 0
    failed = 0
    current_files = set(files)

    for idx, path in enumerate(files, 1):
        try:
            content = obsidian_get_file(path)
            if content is None:
                failed += 1
                continue
            if len(content.strip()) < MIN_CONTENT_LENGTH:
                skipped += 1
                continue

            result = process_file(
                path, content, mapping,
                qdrant_ok, graphiti_ok, graphiti_session)
            if result is None:
                skipped += 1
            else:
                mapping[path] = result
                synced += 1
                # 每同步 5 个文件保存一次 mapping（防中断丢失进度）
                if synced % 5 == 0:
                    save_mapping(mapping)
        except Exception as e:
            print(f"  ⚠️ 处理失败 {path}: {e}", file=sys.stderr)
            failed += 1

    # 删除检测
    deleted = handle_deletions(mapping, current_files, qdrant_ok)

    # 保存 mapping
    save_mapping(mapping)

    print(
        f"  完成: 同步 {synced}, 跳过 {skipped}, 失败 {failed}, 删除 {deleted}",
        file=sys.stderr,
    )


# ===== 入口 =====

def main() -> None:
    if not OBSIDIAN_API_KEY:
        print("⚠️ OBSIDIAN_API_KEY 未设置，退出", file=sys.stderr)
        sys.exit(1)

    daemon = "--daemon" in sys.argv
    full = "--full" in sys.argv

    if daemon:
        print(f"Obsidian 同步守护进程启动（间隔 {DAEMON_INTERVAL}s）", file=sys.stderr)
        while True:
            try:
                sync_once(full=False)
            except Exception as e:
                print(f"⚠️ 同步异常: {e}", file=sys.stderr)
            time.sleep(DAEMON_INTERVAL)
    else:
        sync_once(full=full)


if __name__ == "__main__":
    main()
