"""把 unified_memories_v3 (1024 维, dashscope) 全量迁移到 unified_memories_v3_local (4096 维, 本地 MLX daemon)。

特性:
- 断点续传: 每 100 条 checkpoint
- 失败不丢: 失败的 ID 不进 done_ids,下次自动重试
- 重试: embed/upsert 各 5 次指数退避
- daemon 健康检查: 失败时等 daemon 恢复再继续

跑法:
    caffeinate -i python3 ~/migrate_to_local.py 2>&1 | tee /tmp/migrate.log
"""
import json
import sys
import time
from pathlib import Path

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

QDRANT_URL = "http://127.0.0.1:6333"
DAEMON_URL = "http://127.0.0.1:8765/embed"
DAEMON_HEALTH = "http://127.0.0.1:8765/health"
SRC_COLLECTION = "unified_memories_v3"
DST_COLLECTION = "unified_memories_v3_local"
BATCH_SIZE = 50  # 减小 batch,降低单批失败影响面
CHECKPOINT_FILE = Path.home() / ".migrate_to_local_progress.json"
ERRORS_FILE = Path.home() / ".migrate_to_local_errors.log"

MAX_RETRIES = 5
BACKOFF_BASE = 2.0  # 2,4,8,16,32 秒

client = QdrantClient(url=QDRANT_URL, timeout=30, check_compatibility=False)
http = httpx.Client(timeout=30, limits=httpx.Limits(max_keepalive_connections=2, max_connections=5))


def with_retry(fn, what: str, point_id=None):
    """通用重试包装器,指数退避 + 健康检查。返回结果或抛 RuntimeError。"""
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError) as e:
            last_err = e
            wait = BACKOFF_BASE * (2 ** attempt)
            print(f"  ⚠️  {what} 第{attempt+1}/{MAX_RETRIES}次连接失败: {type(e).__name__}, 等 {wait:.0f}s", flush=True)
            time.sleep(wait)
            # 失败两次以上做健康自检
            if attempt >= 1:
                wait_for_daemon()
        except httpx.HTTPStatusError as e:
            last_err = e
            if e.response.status_code >= 500:
                wait = BACKOFF_BASE * (2 ** attempt)
                print(f"  ⚠️  {what} 第{attempt+1}/{MAX_RETRIES}次 5xx: {e.response.status_code}, 等 {wait:.0f}s", flush=True)
                time.sleep(wait)
            else:
                # 4xx 是数据问题,不重试
                raise
        except Exception as e:
            last_err = e
            wait = BACKOFF_BASE * (2 ** attempt)
            print(f"  ⚠️  {what} 第{attempt+1}/{MAX_RETRIES}次异常: {type(e).__name__}: {e}, 等 {wait:.0f}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"{what} 重试 {MAX_RETRIES} 次仍失败: {last_err}")


def wait_for_daemon(max_wait_sec: int = 300) -> None:
    """循环 ping daemon 健康,最多等 5 分钟。"""
    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        try:
            r = httpx.get(DAEMON_HEALTH, timeout=5)
            if r.status_code == 200 and r.json().get("status") == "ok":
                print(f"  ✓ daemon 恢复", flush=True)
                return
        except Exception:
            pass
        time.sleep(3)
    raise RuntimeError(f"daemon 等待 {max_wait_sec}s 仍不可达")


def embed(text: str, text_type: str = "document") -> list[float]:
    def _do():
        resp = http.post(DAEMON_URL, json={"text": text, "text_type": text_type})
        resp.raise_for_status()
        return resp.json()["embedding"]
    return with_retry(_do, "embed")


def upsert_points(points: list[PointStruct]) -> None:
    def _do():
        client.upsert(collection_name=DST_COLLECTION, points=points)
    with_retry(_do, f"upsert(n={len(points)})")


def load_progress() -> dict:
    if CHECKPOINT_FILE.exists():
        p = json.loads(CHECKPOINT_FILE.read_text())
        # 把字符串 offset 转回 int (Qdrant scroll 不接受字符串)
        off = p.get("next_offset")
        if isinstance(off, str) and off.isdigit():
            p["next_offset"] = int(off)
        return p
    return {"done_ids": [], "next_offset": None, "started_at": time.time()}


def save_progress(progress: dict) -> None:
    CHECKPOINT_FILE.write_text(json.dumps(progress))


def log_error(point_id, content_preview: str, err: str) -> None:
    with ERRORS_FILE.open("a") as f:
        f.write(f"{point_id}\t{content_preview[:100]}\t{err}\n")


def main() -> None:
    print("=" * 70, flush=True)
    print("迁移 unified_memories_v3 → unified_memories_v3_local", flush=True)
    print("=" * 70, flush=True)

    src_total = client.count(SRC_COLLECTION).count
    dst_existing = client.count(DST_COLLECTION).count
    print(f"源 collection: {src_total} 条", flush=True)
    print(f"目标 collection 已有: {dst_existing} 条", flush=True)

    wait_for_daemon(max_wait_sec=10)
    h = httpx.get(DAEMON_HEALTH, timeout=5).json()
    print(f"daemon: {h['status']}, dim={h['dim']}, uptime={h['uptime_sec']/60:.1f}min", flush=True)

    progress = load_progress()
    done_ids = set(progress["done_ids"])
    print(f"已迁移(checkpoint): {len(done_ids)} 条", flush=True)
    print(flush=True)

    if len(done_ids) >= src_total:
        print("✅ 所有点已迁移完成", flush=True)
        return

    t_start = time.time()
    migrated_this_run = 0
    failed_this_run = 0
    next_offset = progress.get("next_offset")
    saw_any_skipped_for_retry = False  # 是否拉到了之前失败的旧条目(在已扫过的 offset 之前)

    # 第一轮: 从 next_offset 接着拉(主流程)
    # 第二轮: 如果有失败的(需要重试), 从头再扫一遍, 只处理不在 done_ids 里的
    rounds = 0
    while rounds < 2:
        rounds += 1
        if rounds == 2:
            # 第二轮: 从头扫,只为捡漏失败的
            n_unfinished = src_total - len(done_ids)
            if n_unfinished <= 0:
                break
            print(f"\n=== 第 2 轮: 还差 {n_unfinished} 条未迁,从头扫源捡漏 ===", flush=True)
            next_offset = None

        while True:
            try:
                points, next_offset = client.scroll(
                    collection_name=SRC_COLLECTION,
                    limit=BATCH_SIZE,
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=False,
                )
            except Exception as e:
                print(f"  ⚠️  scroll 失败,等 10s 重试: {e}", flush=True)
                time.sleep(10)
                continue

            if not points:
                break

            batch_to_upsert = []
            for p in points:
                if p.id in done_ids:
                    continue
                content = (p.payload or {}).get("content", "")
                if not content:
                    # 空内容不能 embed,标 done 避免反复重试
                    done_ids.add(p.id)
                    log_error(p.id, "(empty)", "no content field")
                    failed_this_run += 1
                    continue
                try:
                    vec = embed(content, "document")
                    batch_to_upsert.append(PointStruct(id=p.id, vector=vec, payload=p.payload))
                except Exception as e:
                    # 不标 done, 下次自动重试
                    log_error(p.id, content[:80], f"embed: {e}")
                    failed_this_run += 1
                    continue

            if batch_to_upsert:
                ids_in_batch = [pt.id for pt in batch_to_upsert]
                try:
                    upsert_points(batch_to_upsert)
                    # 整批 upsert 成功,标 done
                    for pid in ids_in_batch:
                        done_ids.add(pid)
                    migrated_this_run += len(batch_to_upsert)
                except Exception as e:
                    # 整批失败,不标 done,下次重试
                    print(f"  ⚠️  整批 upsert 失败,本批 {len(batch_to_upsert)} 条留待下次: {e}", flush=True)
                    for pt in batch_to_upsert:
                        log_error(pt.id, "(upsert-batch)", str(e))
                    failed_this_run += len(batch_to_upsert)

            # checkpoint
            progress = {
                "done_ids": sorted(done_ids, key=str),
                "next_offset": next_offset if next_offset else None,
                "started_at": progress.get("started_at", t_start),
                "last_update": time.time(),
            }
            save_progress(progress)

            elapsed = time.time() - t_start
            rate = migrated_this_run / elapsed if elapsed > 0 else 0
            remaining = src_total - len(done_ids)
            eta_min = remaining / rate / 60 if rate > 0 else 0
            print(
                f"  [r{rounds}] 进度 {len(done_ids)}/{src_total} ({100*len(done_ids)/src_total:.1f}%) "
                f"| 本次新迁 {migrated_this_run} | 失败累计 {failed_this_run} "
                f"| 速度 {rate:.1f}/s | ETA {eta_min:.1f} min",
                flush=True,
            )

            if next_offset is None:
                break

    print(flush=True)
    print("=" * 70, flush=True)
    final_dst = client.count(DST_COLLECTION).count
    print(f"✅ 迁移轮次结束", flush=True)
    print(f"  耗时: {(time.time()-t_start)/60:.1f} 分钟", flush=True)
    print(f"  本次新迁移: {migrated_this_run} 条", flush=True)
    print(f"  本次失败累计: {failed_this_run} 条 (详见 {ERRORS_FILE})", flush=True)
    print(f"  目标 collection 总点数: {final_dst}", flush=True)
    print(f"  源 collection 总点数: {src_total}", flush=True)
    if final_dst < src_total:
        print(f"  ⚠️  仍差 {src_total - final_dst} 条,可再跑一次本脚本捡漏", flush=True)


if __name__ == "__main__":
    main()
