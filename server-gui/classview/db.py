"""SQLite: панели, записи, журнал подключений."""
import sqlite3
import time
from pathlib import Path

from .config import DATA_DIR
from .naming import natural_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS panels(
  hostname TEXT PRIMARY KEY,
  corpus   TEXT NOT NULL DEFAULT '',
  room     TEXT NOT NULL DEFAULT '',
  ip       TEXT NOT NULL DEFAULT '',
  note     TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS recordings(
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  hostname TEXT NOT NULL,
  path     TEXT NOT NULL,
  started  REAL NOT NULL,
  stopped  REAL,
  operator TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS log(
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       REAL NOT NULL,
  operator TEXT NOT NULL,
  hostname TEXT NOT NULL,
  event    TEXT NOT NULL,
  detail   TEXT NOT NULL DEFAULT ''
);
"""


class DB:
    def __init__(self, path=None):
        path = Path(path or DATA_DIR / "classview.db")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --- панели ---
    def panels(self):
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM panels")]
        rows.sort(key=lambda r: (natural_key(r["corpus"]), natural_key(r["room"]), r["hostname"]))
        return rows

    def panel(self, hostname):
        r = self.conn.execute("SELECT * FROM panels WHERE hostname=?", (hostname,)).fetchone()
        return dict(r) if r else None

    def save_panel(self, hostname, corpus, room, ip, note, old_hostname=None):
        with self.conn:
            if old_hostname and old_hostname != hostname:
                self.conn.execute("DELETE FROM panels WHERE hostname=?", (old_hostname,))
            self.conn.execute(
                "INSERT INTO panels(hostname,corpus,room,ip,note) VALUES(?,?,?,?,?) "
                "ON CONFLICT(hostname) DO UPDATE SET corpus=excluded.corpus, room=excluded.room, "
                "ip=excluded.ip, note=excluded.note",
                (hostname, corpus, room, ip, note))

    def import_panel(self, hostname, corpus, room, ip):
        """Импорт из CSV: заметку не трогаем."""
        with self.conn:
            self.conn.execute(
                "INSERT INTO panels(hostname,corpus,room,ip) VALUES(?,?,?,?) "
                "ON CONFLICT(hostname) DO UPDATE SET corpus=excluded.corpus, room=excluded.room, ip=excluded.ip",
                (hostname, corpus, room, ip))

    def set_ip(self, hostname, ip):
        with self.conn:
            self.conn.execute("UPDATE panels SET ip=? WHERE hostname=?", (ip, hostname))

    def delete_panel(self, hostname):
        with self.conn:
            self.conn.execute("DELETE FROM panels WHERE hostname=?", (hostname,))

    # --- записи ---
    def add_recording(self, hostname, path, operator):
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO recordings(hostname,path,started,operator) VALUES(?,?,?,?)",
                (hostname, path, time.time(), operator))
            return cur.lastrowid

    def finish_recording(self, rec_id):
        with self.conn:
            self.conn.execute("UPDATE recordings SET stopped=? WHERE id=?", (time.time(), rec_id))

    def recordings(self):
        return [dict(r) for r in self.conn.execute("SELECT * FROM recordings ORDER BY started DESC")]

    def recordings_before(self, ts):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM recordings WHERE stopped IS NOT NULL AND started < ?", (ts,))]

    def delete_recording(self, rec_id):
        with self.conn:
            self.conn.execute("DELETE FROM recordings WHERE id=?", (rec_id,))

    # --- журнал ---
    def log_event(self, operator, hostname, event, detail=""):
        with self.conn:
            self.conn.execute(
                "INSERT INTO log(ts,operator,hostname,event,detail) VALUES(?,?,?,?,?)",
                (time.time(), operator, hostname, event, detail))

    def log_entries(self, limit=2000):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM log ORDER BY ts DESC LIMIT ?", (limit,))]
