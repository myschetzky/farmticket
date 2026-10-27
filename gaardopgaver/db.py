"""SQLite-adgang. Hele databasen er én fil (standard: data/gaard.db)."""

import sqlite3
from datetime import datetime
from pathlib import Path

import click
from flask import current_app, g
from flask.cli import with_appcontext


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    get_db().executescript(schema)


def query(sql, args=(), one=False):
    cur = get_db().execute(sql, args)
    rows = cur.fetchall()
    cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def execute(sql, args=()) -> int:
    conn = get_db()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.lastrowid


def has_users() -> bool:
    return query("SELECT 1 FROM users LIMIT 1", one=True) is not None


def active_users():
    return query("SELECT id, name FROM users WHERE active = 1 ORDER BY name")


@click.command("backup")
@with_appcontext
def backup_command():
    """Lav en sikkerhedskopi af databasen i data/backup/."""
    target_dir = Path(current_app.config["DATA_DIR"]) / "backup"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"gaard-{datetime.now():%Y%m%d-%H%M%S}.db"
    dest = sqlite3.connect(target)
    with dest:
        get_db().backup(dest)
    dest.close()
    click.echo(f"Sikkerhedskopi gemt: {target}")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(backup_command)
