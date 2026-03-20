"""Quality Profiles API — Phase 2"""
import logging

from fastapi import APIRouter, HTTPException

from database import get_db

log = logging.getLogger("jukeboxx.quality")
router = APIRouter(prefix="/quality-profiles", tags=["quality"])

ALLOWED_FORMATS = {"flac", "mp3_320", "mp3_256", "mp3_128", "opus", "any"}


@router.get("")
async def list_profiles():
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM quality_profiles ORDER BY is_default DESC, name ASC"
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


@router.post("")
async def create_profile(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name required")
    preferred_format = body.get("preferred_format", "any")
    if preferred_format not in ALLOWED_FORMATS:
        raise HTTPException(400, f"preferred_format must be one of {ALLOWED_FORMATS}")
    min_bitrate = int(body.get("min_bitrate", 0))
    upgrade_allowed = 1 if body.get("upgrade_allowed", True) else 0

    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id FROM quality_profiles WHERE name = ?", (name,)
        )
        if await cur.fetchone():
            raise HTTPException(409, "Profile name already exists")
        await db.execute(
            """INSERT INTO quality_profiles (name, preferred_format, min_bitrate, upgrade_allowed)
               VALUES (?, ?, ?, ?)""",
            (name, preferred_format, min_bitrate, upgrade_allowed),
        )
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid() as id")
        profile_id = (await cur.fetchone())["id"]
        return {"id": profile_id, "name": name}
    finally:
        await db.close()


@router.get("/{profile_id}")
async def get_profile(profile_id: int):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT * FROM quality_profiles WHERE id = ?", (profile_id,)
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Profile not found")
        return dict(row)
    finally:
        await db.close()


@router.put("/{profile_id}")
async def update_profile(profile_id: int, body: dict):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, is_default FROM quality_profiles WHERE id = ?", (profile_id,)
        )
        existing = await cur.fetchone()
        if not existing:
            raise HTTPException(404, "Profile not found")
        if existing["is_default"]:
            raise HTTPException(400, "Cannot modify the default 'Any' profile")

        allowed = {"name", "preferred_format", "min_bitrate", "upgrade_allowed"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if "preferred_format" in updates and updates["preferred_format"] not in ALLOWED_FORMATS:
            raise HTTPException(400, f"preferred_format must be one of {ALLOWED_FORMATS}")
        if not updates:
            raise HTTPException(400, "No valid fields to update")

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [profile_id]
        await db.execute(
            f"UPDATE quality_profiles SET {set_clause} WHERE id = ?", params
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@router.delete("/{profile_id}")
async def delete_profile(profile_id: int):
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT id, is_default FROM quality_profiles WHERE id = ?", (profile_id,)
        )
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Profile not found")
        if row["is_default"]:
            raise HTTPException(400, "Cannot delete the default 'Any' profile")
        await db.execute("DELETE FROM quality_profiles WHERE id = ?", (profile_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()
