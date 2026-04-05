"""Migrate claude_code data from Mac Mini Qdrant (SSH tunnel) to local Docker Qdrant."""
import json
import urllib.request
import time

SOURCE = "http://localhost:6333"
TARGET = "http://localhost:16333"
COLLECTION = "unified_memories_v3"
BATCH_SIZE = 100

def post_json(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

def put_json(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())

def main():
    src_info = get_json(f"{SOURCE}/collections/{COLLECTION}")
    src_count = src_info["result"]["points_count"]
    print(f"Source total points: {src_count}")

    offset = None
    total_migrated = 0
    batch_num = 0

    while True:
        payload = {
            "limit": BATCH_SIZE,
            "with_payload": True,
            "with_vector": True,
            "filter": {"must_not": [{"key": "source", "match": {"value": "openclaw"}}]}
        }
        if offset is not None:
            payload["offset"] = offset

        data = post_json(f"{SOURCE}/collections/{COLLECTION}/points/scroll", payload)
        points = data["result"]["points"]
        if not points:
            break

        formatted = [{"id": p["id"], "vector": p["vector"], "payload": p["payload"]} for p in points]
        put_json(f"{TARGET}/collections/{COLLECTION}/points", {"points": formatted})

        batch_num += 1
        total_migrated += len(points)
        print(f"Batch {batch_num}: {len(points)} points (total: {total_migrated})")

        offset = data["result"].get("next_page_offset")
        if offset is None:
            break
        time.sleep(0.1)

    tgt_info = get_json(f"{TARGET}/collections/{COLLECTION}")
    target_count = tgt_info["result"]["points_count"]
    print(f"\nDone! Source: {src_count}, Target: {target_count}, Migrated: {total_migrated}")

if __name__ == "__main__":
    main()
