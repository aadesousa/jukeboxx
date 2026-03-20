from database import get_db


async def list_profiles() -> list:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM release_profiles ORDER BY is_default DESC, name ASC")
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_profile(profile_id: int) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM release_profiles WHERE id = ?", (profile_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def create_profile(data: dict) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO release_profiles (name, required_words, ignored_words, preferred_words, score_boost, is_default) VALUES (?, ?, ?, ?, ?, ?)",
            (data["name"], data.get("required_words", ""), data.get("ignored_words", ""), data.get("preferred_words", ""), int(data.get("score_boost", 0)), int(bool(data.get("is_default", False))))
        )
        new_id = cur.lastrowid
        if data.get("is_default"):
            await db.execute("UPDATE release_profiles SET is_default=0 WHERE id!=?", (new_id,))
        await db.commit()
        return new_id
    finally:
        await db.close()


async def update_profile(profile_id: int, data: dict):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM release_profiles WHERE id=?", (profile_id,))
        ex = await cur.fetchone()
        if not ex:
            return
        ex = dict(ex)
        is_default = int(bool(data.get("is_default", ex["is_default"])))
        await db.execute(
            "UPDATE release_profiles SET name=?, required_words=?, ignored_words=?, preferred_words=?, score_boost=?, is_default=? WHERE id=?",
            (data.get("name", ex["name"]), data.get("required_words", ex["required_words"]), data.get("ignored_words", ex["ignored_words"]), data.get("preferred_words", ex["preferred_words"]), int(data.get("score_boost", ex["score_boost"])), is_default, profile_id)
        )
        if is_default:
            await db.execute("UPDATE release_profiles SET is_default=0 WHERE id!=?", (profile_id,))
        await db.commit()
    finally:
        await db.close()


async def delete_profile(profile_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM release_profiles WHERE id=?", (profile_id,))
        await db.commit()
    finally:
        await db.close()
