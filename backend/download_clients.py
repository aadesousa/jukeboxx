"""Download client management — Lidarr-style abstraction."""
import json
import logging
import httpx
from database import get_db

log = logging.getLogger("jukeboxx.download_clients")

SUPPORTED_TYPES = ["spotizerr", "metube", "qbittorrent", "slskd", "sabnzbd"]


def _row_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["extra_config"] = json.loads(d.get("extra_config") or "{}")
    except Exception:
        d["extra_config"] = {}
    d["password"] = "***" if d.get("password") else ""
    return d


async def list_clients() -> list:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM download_clients ORDER BY priority ASC, id ASC"
        )
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        await db.close()


async def get_client(client_id: int) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM download_clients WHERE id = ?", (client_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["extra_config"] = json.loads(d.get("extra_config") or "{}")
        except Exception:
            d["extra_config"] = {}
        return d  # raw including password for internal use
    finally:
        await db.close()


async def create_client(data: dict) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT COALESCE(MAX(priority), -1) + 1 FROM download_clients"
        )
        row = await cur.fetchone()
        next_priority = row[0] if row else 0
        cur = await db.execute(
            """INSERT INTO download_clients
               (name, type, enabled, priority, host, port, username, password,
                url_base, api_key, use_ssl, extra_config)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["name"],
                data["type"],
                int(data.get("enabled", 1)),
                next_priority,
                data.get("host", ""),
                int(data.get("port", 0)),
                data.get("username", ""),
                data.get("password", ""),
                data.get("url_base", ""),
                data.get("api_key", ""),
                int(data.get("use_ssl", 0)),
                json.dumps(data.get("extra_config", {})),
            ),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def update_client(client_id: int, data: dict):
    db = await get_db()
    try:
        fields = []
        values = []
        for field in [
            "name", "enabled", "host", "port", "username",
            "url_base", "api_key", "use_ssl",
        ]:
            if field in data:
                fields.append(f"{field} = ?")
                values.append(data[field])
        # Password: only update if non-empty and not placeholder
        if data.get("password") and data["password"] != "***":
            fields.append("password = ?")
            values.append(data["password"])
        if "extra_config" in data:
            fields.append("extra_config = ?")
            values.append(json.dumps(data["extra_config"]))
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(client_id)
        await db.execute(
            f"UPDATE download_clients SET {', '.join(fields)} WHERE id = ?", values
        )
        await db.commit()
    finally:
        await db.close()


async def delete_client(client_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM download_clients WHERE id = ?", (client_id,))
        await db.commit()
    finally:
        await db.close()


async def reorder_clients(ordered_ids: list):
    db = await get_db()
    try:
        for priority, cid in enumerate(ordered_ids):
            await db.execute(
                "UPDATE download_clients SET priority = ? WHERE id = ?",
                (priority, cid),
            )
        await db.commit()
    finally:
        await db.close()


async def test_client(client_id: int) -> dict:
    raw = await get_client(client_id)
    if not raw:
        return {"ok": False, "message": "Client not found"}
    ctype = raw["type"]
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            if ctype == "spotizerr":
                url = raw.get("url_base", "").rstrip("/")
                r = await client.get(f"{url}/api/v1/album/test")
                if r.status_code in (200, 400, 404, 422):
                    return {"ok": True, "message": "Spotizerr reachable"}
                return {"ok": False, "message": f"HTTP {r.status_code}"}

            elif ctype == "qbittorrent":
                scheme = "https" if raw["use_ssl"] else "http"
                base = f"{scheme}://{raw['host']}:{raw['port']}{raw.get('url_base','')}"
                r = await client.get(f"{base}/api/v2/app/version")
                if r.status_code == 200:
                    return {"ok": True, "message": f"qBittorrent {r.text.strip()}"}
                return {"ok": False, "message": "Not reachable"}

            elif ctype == "sabnzbd":
                scheme = "https" if raw["use_ssl"] else "http"
                base = f"{scheme}://{raw['host']}:{raw['port']}{raw.get('url_base','')}"
                r = await client.get(
                    f"{base}/api",
                    params={"mode": "version", "apikey": raw["api_key"], "output": "json"},
                )
                data = r.json()
                if data.get("version"):
                    return {"ok": True, "message": f"SABnzbd {data['version']}"}
                return {"ok": False, "message": "Not reachable or bad API key"}

            elif ctype == "slskd":
                base = raw.get("url_base", "").rstrip("/")
                headers = {"X-API-Key": raw["api_key"]} if raw.get("api_key") else {}
                r = await client.get(f"{base}/api/v0/application", headers=headers)
                if r.status_code == 200:
                    return {"ok": True, "message": "slskd connected"}
                if r.status_code == 401:
                    return {"ok": False, "message": "Bad API key"}
                return {"ok": False, "message": "Not reachable"}

            elif ctype == "metube":
                base = raw.get("url_base", "").rstrip("/")
                r = await client.get(f"{base}/")
                if r.status_code in (200, 404):
                    return {"ok": True, "message": "MeTube reachable"}
                return {"ok": False, "message": "Not reachable"}

            return {"ok": False, "message": f"Unknown client type: {ctype}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
