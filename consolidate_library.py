#!/usr/bin/env python3
"""
Consolidate duplicate album folders in the jukeboxx music library.

Strategy:
  1. Group tracks from DB by (artist, album) — exact tag match.
  2. For each album in multiple folders, pick the canonical (most audio files).
  3. Move unique tracks (by filename) from other folders into canonical.
  4. If a source folder has ALL its audio files already present in canonical
     (by filename), or had all unique files successfully moved, delete it.

Run outside the container: python3 consolidate_library.py
"""
import os
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = "/home/eve/jukeboxx/data/jukeboxx.db"
MUSIC_PATH = "/mnt/storage/MUSIC"
DB_PATH_PREFIX = "/music"
HOST_PATH_PREFIX = MUSIC_PATH
DRY_RUN = False   # Set to True to preview without changes

AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aac"}
SKIP_FOLDER_PARTS = {"incomplete", "failed_imports", "Playlists"}


def host_path(p: str) -> str:
    if p.startswith(DB_PATH_PREFIX + "/") or p == DB_PATH_PREFIX:
        return HOST_PATH_PREFIX + p[len(DB_PATH_PREFIX):]
    return p


def is_audio(p: Path) -> bool:
    return p.suffix.lower() in AUDIO_EXTS


def audio_files(folder: str) -> list[Path]:
    try:
        return [f for f in Path(folder).iterdir() if f.is_file() and is_audio(f)]
    except Exception:
        return []


def is_excluded(folder: str) -> bool:
    p = Path(folder)
    if str(p) == MUSIC_PATH:
        return True
    return any(part in SKIP_FOLDER_PARTS for part in p.parts)


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT id, path, artist, album_artist, album
        FROM tracks
        WHERE album IS NOT NULL AND (artist IS NOT NULL OR album_artist IS NOT NULL)
        ORDER BY album, COALESCE(album_artist, artist)
    """)
    rows = cur.fetchall()
    conn.close()

    album_folders: dict[tuple, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        path = host_path(row["path"])
        if not os.path.exists(path):
            continue
        folder = str(Path(path).parent)
        if is_excluded(folder):
            continue
        artist = (row["album_artist"] or row["artist"] or "").strip().lower()
        album = (row["album"] or "").strip().lower()
        if not album:
            continue
        album_folders[(artist, album)][folder].append(path)

    multi = {k: v for k, v in album_folders.items() if len(v) > 1}
    print(f"Albums in multiple folders: {len(multi)}")
    print(f"DRY_RUN={DRY_RUN}\n")

    total_moved = 0
    total_deleted = 0
    total_skipped = 0
    move_errors = 0

    for (artist, album), folders in sorted(multi.items()):
        canonical = max(folders.keys(), key=lambda f: len(audio_files(f)))
        canonical_names = {f.name for f in audio_files(canonical)}
        others = {f: tracks for f, tracks in folders.items() if f != canonical}

        print(f"\nAlbum: {artist!r} / {album!r}")
        print(f"  Canonical ({len(canonical_names)} files): {canonical}")

        for src_folder, _tracks in others.items():
            src_audio = audio_files(src_folder)
            src_names = {f.name for f in src_audio}
            unique_names = src_names - canonical_names
            dup_names = src_names & canonical_names

            print(f"  Other    ({len(src_audio)} files, {len(unique_names)} unique, {len(dup_names)} dup): {src_folder}")

            failed_moves: set[str] = set()

            if unique_names:
                for fname in sorted(unique_names):
                    src = Path(src_folder) / fname
                    dst = Path(canonical) / fname
                    print(f"    MOVE: {fname}")
                    if not DRY_RUN:
                        try:
                            shutil.move(str(src), str(dst))
                            total_moved += 1
                            canonical_names.add(fname)
                        except Exception as e:
                            print(f"    ERROR: {e}")
                            failed_moves.add(fname)
                            move_errors += 1

            if dup_names:
                print(f"    SKIP ({len(dup_names)} dups already in canonical)")
                total_skipped += len(dup_names)

            # Can we delete? Yes if no unique files failed to move.
            can_delete = not failed_moves
            if can_delete:
                print(f"  RMDIR: {src_folder}")
                if not DRY_RUN:
                    try:
                        shutil.rmtree(src_folder)
                        total_deleted += 1
                    except Exception as e:
                        print(f"  ERROR rmdir: {e}")
            else:
                print(f"  KEEP ({len(failed_moves)} move failures): {src_folder}")

    prefix = "[DRY RUN] " if DRY_RUN else ""
    print(f"\n{prefix}Done: moved={total_moved}, deleted_dirs={total_deleted}, "
          f"skipped_dups={total_skipped}, move_errors={move_errors}")
    if DRY_RUN:
        print("Set DRY_RUN=False and re-run to apply changes.")


if __name__ == "__main__":
    main()
