#!/usr/bin/env python3
"""
Remove slskd timestamped duplicate files.

slskd appends _<ticks> (18-19 digit .NET DateTime ticks) when a file already
exists in the download directory, e.g.:
  06. Four Out Of Five.flac              ← original
  06. Four Out Of Five_639094067170147515.flac  ← re-download duplicate

This script finds all *_<ticks>.ext files and deletes them if the original
(without the timestamp) exists in the same folder.

Run outside the container: python3 clean_slskd_dupes.py
"""
import os
import re
from pathlib import Path

MUSIC_PATH = "/mnt/storage/MUSIC"
DRY_RUN = False  # Set to True to preview

AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aac"}

# Matches _<15+ digits> before the extension
TICK_RE = re.compile(r'_\d{15,}$')


def main():
    deleted = 0
    kept = 0

    for root, dirs, files in os.walk(MUSIC_PATH):
        # Skip incomplete downloads
        dirs[:] = [d for d in dirs if d not in {"incomplete", "failed_imports"}]

        audio = {f for f in files if Path(f).suffix.lower() in AUDIO_EXTS}

        for fname in sorted(audio):
            p = Path(fname)
            stem = p.stem
            ext = p.suffix

            m = TICK_RE.search(stem)
            if not m:
                continue  # not a timestamped file

            # Strip the timestamp to get the original base name
            base_stem = stem[:m.start()]
            original_name = base_stem + ext

            if original_name in audio:
                # Original exists → this is a true duplicate
                dup_path = Path(root) / fname
                print(f"DELETE: {dup_path}")
                if not DRY_RUN:
                    try:
                        os.remove(dup_path)
                        deleted += 1
                    except Exception as e:
                        print(f"  ERROR: {e}")
                else:
                    deleted += 1
            else:
                # No original — rename to remove the timestamp
                new_path = Path(root) / original_name
                if not new_path.exists():
                    print(f"RENAME: {Path(root) / fname}  →  {original_name}")
                    kept += 1
                    if not DRY_RUN:
                        try:
                            os.rename(Path(root) / fname, new_path)
                        except Exception as e:
                            print(f"  ERROR rename: {e}")
                else:
                    # Both original and timestamp exist after all? Skip.
                    print(f"SKIP (original exists): {fname}")

    prefix = "[DRY RUN] " if DRY_RUN else ""
    print(f"\n{prefix}Done: deleted={deleted}, renamed={kept}")
    if DRY_RUN:
        print("Set DRY_RUN=False and re-run to apply.")


if __name__ == "__main__":
    main()
