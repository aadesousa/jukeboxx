"""Indexer management — Prowlarr/Torznab/Newznab."""
import json
import logging
import httpx
from database import get_db

log = logging.getLogger("jukeboxx.indexers")

SUPPORTED_TYPES = ["prowlarr", "torznab", "newznab"]


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["categories"] = json.loads(d.get("categories") or "[]")
    except Exception:
        d["categories"] = []
    try:
        d["extra_config"] = json.loads(d.get("extra_config") or "{}")
    except Exception:
        d["extra_config"] = {}
    return d


async def list_indexers() -> list:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM indexers ORDER BY priority ASC, id ASC"
        )
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        await db.close()


async def get_indexer(indexer_id: int) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM indexers WHERE id = ?", (indexer_id,))
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None
    finally:
        await db.close()


async def create_indexer(data: dict) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COALESCE(MAX(priority), -1) + 1 FROM indexers"
        )
        row = await cur.fetchone()
        next_priority = row[0] if row else 0
        cur = await db.execute(
            """INSERT INTO indexers
               (name, type, enabled, priority, url, api_key, categories, extra_config)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["name"],
                data["type"],
                int(data.get("enabled", 1)),
                next_priority,
                data.get("url", ""),
                data.get("api_key", ""),
                json.dumps(data.get("categories", [])),
                json.dumps(data.get("extra_config", {})),
            ),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_indexer(indexer_id: int, data: dict):
    db = await get_db()
    try:
        fields = []
        values = []
        for field in ["name", "enabled", "url", "api_key"]:
            if field in data:
                fields.append(f"{field} = ?")
                values.append(data[field])
        if "categories" in data:
            fields.append("categories = ?")
            values.append(json.dumps(data["categories"]))
        if "extra_config" in data:
            fields.append("extra_config = ?")
            values.append(json.dumps(data["extra_config"]))
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(indexer_id)
        await db.execute(
            f"UPDATE indexers SET {', '.join(fields)} WHERE id = ?", values
        )
        await db.commit()
    finally:
        await db.close()


async def delete_indexer(indexer_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM indexers WHERE id = ?", (indexer_id,))
        await db.commit()
    finally:
        await db.close()


async def reorder_indexers(ordered_ids: list):
    db = await get_db()
    try:
        for priority, iid in enumerate(ordered_ids):
            await db.execute(
                "UPDATE indexers SET priority = ? WHERE id = ?", (priority, iid)
            )
        await db.commit()
    finally:
        await db.close()


async def test_indexer(indexer_id: int) -> dict:
    idx = await get_indexer(indexer_id)
    if not idx:
        return {"ok": False, "message": "Indexer not found"}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            if idx["type"] == "prowlarr":
                url = idx["url"].rstrip("/")
                headers = {"X-Api-Key": idx["api_key"]} if idx["api_key"] else {}
                r = await client.get(f"{url}/api/v1/indexer", headers=headers)
                if r.status_code == 200:
                    return {"ok": True, "message": f"Prowlarr: {len(r.json())} indexers"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}

            elif idx["type"] in ("torznab", "newznab"):
                r = await client.get(idx["url"], params={"t": "caps", "apikey": idx["api_key"]})
                if r.status_code == 200:
                    return {"ok": True, "message": "Feed reachable"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}

            return {"ok": False, "message": f"Unknown type: {idx['type']}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
