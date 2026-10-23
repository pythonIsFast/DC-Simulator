"""Export/import of the whole local database as one file (.dcsave = gzip-compressed SQLite snapshot).

Used to move saves between devices (PC <-> phone). Nothing leaves the device by itself: the player carries the file.
"""
import glob
import gzip
import os
import shutil
import sqlite3
import tempfile
import time

MAX_BYTES = 80 * 1024 * 1024
KEEP_BACKUPS = 3


class TransferError(Exception):
    pass


def worlds_of(db_path):
    """[{id, name, tick}] of a database file (read only)."""
    conn = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    try:
        return [{"id": r[0], "name": r[1], "tick": r[2]} for r in conn.execute("SELECT id, name, tick FROM worlds ORDER BY id")]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def export_bytes(db_path):
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "snap.sqlite3")
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(snap)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode = DELETE")
        finally:
            dst.close()
            src.close()
        with open(snap, "rb") as f:
            return gzip.compress(f.read(), 9)


def _open_snapshot(blob, tmp, schema_version):
    """Unpack and validate an uploaded file. Returns the path of the unpacked database."""
    if not blob or len(blob) > MAX_BYTES:
        raise TransferError("This is not a valid save file.")
    try:
        raw = gzip.decompress(blob)
    except (OSError, EOFError, ValueError):
        raise TransferError("This is not a valid save file.")
    if not raw.startswith(b"SQLite format 3"):
        raise TransferError("This is not a valid save file.")
    path = os.path.join(tmp, "import.sqlite3")
    with open(path, "wb") as f:
        f.write(raw)
    conn = sqlite3.connect(path)
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise TransferError("The save file is damaged.")
        if conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'worlds'").fetchone()[0] != 1:
            raise TransferError("This is not a Datacenter Tycoon save file.")
        if conn.execute("PRAGMA user_version").fetchone()[0] > schema_version:
            raise TransferError("The save is from a newer version of the game. Update the game first.")
    except sqlite3.Error:
        raise TransferError("This is not a valid save file.")
    finally:
        conn.close()
    return path


def inspect(blob, schema_version):
    """Validate a file without changing anything. Returns its worlds."""
    with tempfile.TemporaryDirectory() as tmp:
        return worlds_of(_open_snapshot(blob, tmp, schema_version))


def _prune_backups(db_path):
    backups = sorted(glob.glob(db_path + ".bak-*"), key=os.path.getmtime, reverse=True)
    for old in backups[KEEP_BACKUPS:]:
        try:
            os.remove(old)
        except OSError:
            pass


def restore(blob, db_path, schema_version, apply_schema):
    """Replace the local database with the file. The old database is kept as a backup copy."""
    with tempfile.TemporaryDirectory() as tmp:
        snap = _open_snapshot(blob, tmp, schema_version)
        if os.path.exists(db_path):
            shutil.copyfile(db_path, "%s.bak-%d" % (db_path, int(time.time())))
        src = sqlite3.connect(snap)
        dst = sqlite3.connect(db_path, timeout=30)
        try:
            src.backup(dst)
            apply_schema(dst)
        except sqlite3.Error as exc:
            raise TransferError("Could not restore the save: %s" % exc)
        finally:
            dst.close()
            src.close()
    _prune_backups(db_path)
    return worlds_of(db_path)
