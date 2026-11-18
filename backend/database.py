import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent.parent / "database" / "monitoring.db"

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS pod_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pod_name TEXT NOT NULL, namespace TEXT NOT NULL,
            state TEXT NOT NULL, color TEXT NOT NULL,
            restarts INTEGER NOT NULL, recorded_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pod_name TEXT NOT NULL, namespace TEXT NOT NULL,
            message TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            first_seen TEXT NOT NULL, last_seen TEXT NOT NULL
        )""")

def record_snapshot(pods):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        for pod in pods:
            conn.execute(
                "INSERT INTO pod_history (pod_name, namespace, state, color, restarts, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (pod["name"], pod["namespace"], pod["display_state"], pod["color"], pod["restarts"], now)
            )
            if pod["display_state"] == "crash":
                existing = conn.execute(
                    "SELECT id FROM alerts WHERE pod_name=? AND namespace=? AND active=1",
                    (pod["name"], pod["namespace"])
                ).fetchone()
                if existing:
                    conn.execute("UPDATE alerts SET last_seen=?, message=? WHERE id=?",
                                 (now, pod["detail"], existing["id"]))
                else:
                    conn.execute(
                        "INSERT INTO alerts (pod_name, namespace, message, first_seen, last_seen) VALUES (?, ?, ?, ?, ?)",
                        (pod["name"], pod["namespace"], pod["detail"], now, now)
                    )
            else:
                conn.execute("UPDATE alerts SET active=0, last_seen=? WHERE pod_name=? AND namespace=? AND active=1",
                             (now, pod["name"], pod["namespace"]))

def get_history(limit=100):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM pod_history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

def get_alerts():
    with connect() as conn:
        rows = conn.execute("SELECT * FROM alerts ORDER BY active DESC, last_seen DESC LIMIT 200").fetchall()
        return [dict(r) for r in rows]

def acknowledge_alerts():
    with connect() as conn:
        conn.execute("UPDATE alerts SET active=0 WHERE active=1")
