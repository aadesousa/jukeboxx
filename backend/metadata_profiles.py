from database import get_db

SUPPORTED_TYPES = ["albums", "singles", "eps", "compilations", "live"]


async def list_profiles() -> list:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM metadata_profiles ORDER BY is_default DESC, name ASC")
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def get_profile(profile_id: int) -> dict | None:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM metadata_profiles WHERE id = ?", (profile_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def create_profile(data: dict) -> int:
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO metadata_profiles
               (name, include_albums, include_singles, include_eps, include_compilations, include_live, is_default)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                data["name"],
                int(bool(data.get("include_albums", True))),
                int(bool(data.get("include_singles", False))),
                int(bool(data.get("include_eps", True))),
                int(bool(data.get("include_compilations", False))),
                int(bool(data.get("include_live", False))),
                int(bool(data.get("is_default", False))),
            ),
        )
        new_id = cur.lastrowid
        if data.get("is_default"):
            await db.execute(
                "UPDATE metadata_profiles SET is_default = 0 WHERE id != ?", (new_id,)
            )
        await db.commit()
        return new_id
    finally:
        await db.close()


async def update_profile(profile_id: int, data: dict):
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM metadata_profiles WHERE id = ?", (profile_id,))
        existing = await cur.fetchone()
        if not existing:
            return
        existing = dict(existing)

        name = data.get("name", existing["name"])
        inc_albums = int(bool(data.get("include_albums", existing["include_albums"])))
        inc_singles = int(bool(data.get("include_singles", existing["include_singles"])))
        inc_eps = int(bool(data.get("include_eps", existing["include_eps"])))
        inc_comp = int(bool(data.get("include_compilations", existing["include_compilations"])))
        inc_live = int(bool(data.get("include_live", existing["include_live"])))
        is_default = int(bool(data.get("is_default", existing["is_default"])))

        await db.execute(
            """UPDATE metadata_profiles
               SET name=?, include_albums=?, include_singles=?, include_eps=?,
                   include_compilations=?, include_live=?, is_default=?
               WHERE id=?""",
            (name, inc_albums, inc_singles, inc_eps, inc_comp, inc_live, is_default, profile_id),
        )
        if is_default:
            await db.execute(
                "UPDATE metadata_profiles SET is_default = 0 WHERE id != ?", (profile_id,)
            )
        await db.commit()
    finally:
        await db.close()


async def delete_profile(profile_id: int):
    db = await get_db()
    try:
        # Unlink artists using this profile
        await db.execute(
            "UPDATE monitored_artists SET metadata_profile_id = NULL WHERE metadata_profile_id = ?",
            (profile_id,),
        )
        await db.execute("DELETE FROM metadata_profiles WHERE id = ?", (profile_id,))
        await db.commit()
    finally:
        await db.close()
