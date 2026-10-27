"""Home Assistant-integration (kun aktiv, når systemet kører som Home Assistant-app).

- Ingress: siderne vises inde i Home Assistant under /api/hassio_ingress/<token>/.
- Login: Home Assistant sender den indloggede bruger med i headers; brugeren oprettes automatisk.
- Sensorer: antal åbne/akutte opgaver, dagens plan og næste opgave sendes til Home Assistant,
  så de kan vises på dashboardet.
"""

import json
import logging
import os
import secrets
import socket
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from flask import abort, current_app, g, request, session
from werkzeug.security import generate_password_hash

from . import db
from .calendar_sync import CalendarSync, HAClient
from .constants import OPEN_STATUSES, PRIORITIES
from .dates import DT_FORMAT, WEEKDAYS_SHORT, fmt_time, now_str

log = logging.getLogger(__name__)

# Home Assistants ingress-proxy kommer altid fra denne adresse.
INGRESS_IP = "172.30.32.2"
HA_ADMIN_GROUP = "system-admin"
OPTIONS_FILE = "/data/options.json"
CORE_API = "http://supervisor/core/api"
PUBLISH_INTERVAL = 300  # sekunder; sensorer genudsendes, så de overlever en genstart af Home Assistant

# Uden for ingress må kun kalender-feedet (beskyttet af personligt token) og statiske filer nås.
DIRECT_ENDPOINTS = {"schedule.ical_feed", "static"}


class IngressMiddleware:
    """Lad Flask generere links med ingress-præfikset, så alle URL'er virker inde i Home Assistant."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_INGRESS_PATH", "")
        if prefix and environ.get("REMOTE_ADDR") == INGRESS_IP:
            environ["SCRIPT_NAME"] = prefix.rstrip("/")
        return self.wsgi_app(environ, start_response)


def is_ingress():
    return request.remote_addr == INGRESS_IP


def guard_request():
    """Kaldes før hver forespørgsel i Home Assistant-tilstand. Logger brugeren ind via ingress."""
    if not is_ingress():
        if request.endpoint in DIRECT_ENDPOINTS:
            return
        abort(403, "Åbn Gårdopgaver via Home Assistant.")

    ha_id = request.headers.get("X-Remote-User-Id")
    if not ha_id:
        return  # ældre Home Assistant uden brugerheaders: almindeligt login bruges i stedet
    username = request.headers.get("X-Remote-User-Name") or f"ha-{ha_id[:8]}"
    name = request.headers.get("X-Remote-User-Display-Name") or username
    groups = request.headers.get("X-Remote-User-Groups")
    is_ha_admin = groups is not None and HA_ADMIN_GROUP in groups.split(",")

    user = sync_user(ha_id, username, name, is_ha_admin, groups_known=groups is not None)
    if not user["active"]:
        session.clear()
        abort(403, "Din adgang til Gårdopgaver er deaktiveret. Kontakt en administrator.")
    if session.get("user_id") != user["id"]:
        session.clear()
        session["user_id"] = user["id"]
    g.user = user


def sync_user(ha_id, username, name, is_ha_admin, groups_known=True):
    """Find eller opret brugeren, der hører til Home Assistant-brugeren."""
    user = db.query("SELECT * FROM users WHERE ha_user_id = ?", (ha_id,), one=True)
    if user is None:
        # Knyt til en eksisterende lokal bruger med samme brugernavn (fx efter flytning af data).
        user = db.query(
            "SELECT * FROM users WHERE username = ? AND ha_user_id IS NULL", (username,), one=True
        )
        if user is not None:
            db.execute("UPDATE users SET ha_user_id = ? WHERE id = ?", (ha_id, user["id"]))
        else:
            # Første bruger bliver administrator, hvis Home Assistant ikke fortæller om grupper.
            make_admin = is_ha_admin or (not groups_known and not db.has_users())
            unique = username
            n = 2
            while db.query("SELECT 1 FROM users WHERE username = ?", (unique,), one=True):
                unique = f"{username}{n}"
                n += 1
            db.execute(
                "INSERT INTO users (username, name, password_hash, is_admin, ical_token, created_at, ha_user_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (unique, name, generate_password_hash(secrets.token_urlsafe(32)), 1 if make_admin else 0,
                 secrets.token_urlsafe(24), now_str(), ha_id),
            )
    else:
        if user["name"] != name:
            db.execute("UPDATE users SET name = ? WHERE id = ?", (name, user["id"]))
    if is_ha_admin:
        # Administratorer i Home Assistant er altid administratorer her. Andre kan forfremmes manuelt.
        db.execute("UPDATE users SET is_admin = 1 WHERE ha_user_id = ? AND is_admin = 0", (ha_id,))
    return db.query("SELECT * FROM users WHERE ha_user_id = ?", (ha_id,), one=True)


def feed_base_url():
    """Adresse, som Home Assistant selv kan hente kalender-feedet fra (internt netværk)."""
    return f"http://{socket.gethostname()}:{current_app.config['HA_PORT']}"


def load_options():
    try:
        with open(OPTIONS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# ---------- Sensorer til Home Assistant-dashboardet ----------

def build_sensors(conn, now=None):
    """Byg sensor-tilstande ud fra databasen. Returnerer {entity_id: {"state":…, "attributes":…}}."""
    now = now or datetime.now()
    now_s = now.strftime(DT_FORMAT)
    today = now.date()
    conn.row_factory = sqlite3.Row
    open_list = ", ".join(f"'{s}'" for s in OPEN_STATUSES)

    counts = {r["priority"]: r["n"] for r in conn.execute(
        f"SELECT priority, COUNT(*) AS n FROM tickets WHERE status IN ({open_list}) GROUP BY priority")}
    total = sum(counts.values())
    waiting = conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'venter'").fetchone()[0]
    overdue = conn.execute(
        f"SELECT COUNT(*) FROM tickets WHERE status IN ({open_list}) AND due_date < ?",
        (today.isoformat(),)).fetchone()[0]
    unplanned = conn.execute(
        f"""SELECT COUNT(*) FROM tickets t WHERE status IN ({open_list}) AND status != 'venter'
             AND NOT EXISTS (SELECT 1 FROM time_slots s WHERE s.ticket_id = t.id AND s.ends_at >= ?)""",
        (now_s,)).fetchone()[0]
    acute = [r["title"] for r in conn.execute(
        f"SELECT title FROM tickets WHERE status IN ({open_list}) AND priority = 1 ORDER BY created_at")]

    slots = conn.execute(
        """SELECT s.starts_at, s.ends_at, t.title, t.priority, t.location, u.name AS user_name
             FROM time_slots s JOIN tickets t ON t.id = s.ticket_id
             LEFT JOIN users u ON u.id = s.user_id
            WHERE s.ends_at >= ? AND s.starts_at < ? ORDER BY s.starts_at""",
        (now_s, (today + timedelta(days=7)).isoformat())).fetchall()

    def item(s, with_day=False):
        d = date.fromisoformat(s["starts_at"][:10])
        entry = {"tid": f"{fmt_time(s['starts_at'])}–{fmt_time(s['ends_at'])}", "opgave": s["title"],
                 "person": s["user_name"] or "", "prioritet": PRIORITIES[s["priority"]]}
        if with_day:
            entry["dag"] = f"{WEEKDAYS_SHORT[d.weekday()]} {d.day}/{d.month}"
        return entry

    plan_today = [item(s) for s in slots if s["starts_at"][:10] <= today.isoformat()]
    plan_week = [item(s, with_day=True) for s in slots]
    nxt = slots[0] if slots else None

    return {
        "sensor.gaardopgaver_aabne_opgaver": {
            "state": total,
            "attributes": {
                "friendly_name": "Åbne gårdopgaver",
                "icon": "mdi:clipboard-list-outline",
                "unit_of_measurement": "opgaver",
                "akut": counts.get(1, 0), "hoej": counts.get(2, 0),
                "normal": counts.get(3, 0), "lav": counts.get(4, 0),
                "venter": waiting, "over_deadline": overdue, "uden_tid": unplanned,
                "i_dag": plan_today, "kommende_7_dage": plan_week,
            },
        },
        "sensor.gaardopgaver_akutte_opgaver": {
            "state": len(acute),
            "attributes": {
                "friendly_name": "Akutte gårdopgaver",
                "icon": "mdi:alert-circle-outline",
                "unit_of_measurement": "opgaver",
                "opgaver": acute,
            },
        },
        "sensor.gaardopgaver_naeste_opgave": {
            "state": (nxt["title"][:250] if nxt else "Intet planlagt"),
            "attributes": {
                "friendly_name": "Næste gårdopgave",
                "icon": "mdi:calendar-clock",
                "start": nxt["starts_at"].replace(" ", "T") if nxt else None,
                "slut": nxt["ends_at"].replace(" ", "T") if nxt else None,
                "person": (nxt["user_name"] or "") if nxt else "",
                "sted": (nxt["location"] or "") if nxt else "",
                "prioritet": PRIORITIES[nxt["priority"]] if nxt else "",
            },
        },
    }


class SensorPublisher(threading.Thread):
    """Sender sensorer og synkroniserer kalenderen ved ændringer og hvert 5. minut."""

    def __init__(self, db_path, token, calendar_entity=None):
        super().__init__(daemon=True, name="ha-sensorer")
        self.db_path = db_path
        self.token = token
        self.calendar_entity = calendar_entity
        self._changed = threading.Event()
        self._warned = False

    def notify_change(self):
        self._changed.set()

    def run(self):
        changed = False
        while True:
            try:
                self.publish(refresh_calendar=changed)
            except Exception:  # noqa: BLE001 – må aldrig stoppe tråden
                log.exception("Kunne ikke opdatere sensorer i Home Assistant")
            try:
                self.sync_calendar()
            except Exception:  # noqa: BLE001
                log.exception("Kalendersynkronisering fejlede")
            changed = self._changed.wait(PUBLISH_INTERVAL)
            if changed:
                self._changed.wait(2)  # saml flere hurtige ændringer i én opdatering
                self._changed.clear()

    def sync_calendar(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        try:
            CalendarSync(conn, HAClient(self.token)).run()
        finally:
            conn.close()

    def _call(self, method, path, payload=None):
        req = urllib.request.Request(
            f"{CORE_API}{path}", method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status

    def publish(self, refresh_calendar=False):
        conn = sqlite3.connect(self.db_path)
        try:
            sensors = build_sensors(conn)
        finally:
            conn.close()
        try:
            for entity_id, body in sensors.items():
                self._call("POST", f"/states/{entity_id}", body)
            self._warned = False
        except (urllib.error.URLError, OSError) as exc:
            if not self._warned:
                log.warning("Home Assistant kunne ikke nås (%s). Prøver igen senere.", exc)
                self._warned = True
            return
        if refresh_calendar and self.calendar_entity:
            try:
                self._call("GET", f"/states/{self.calendar_entity}")
                self._call("POST", "/services/homeassistant/update_entity",
                           {"entity_id": self.calendar_entity})
            except (urllib.error.URLError, OSError):
                pass  # kalenderen er valgfri; findes den ikke, gør vi ingenting


def init_app(app):
    """Slå Home Assistant-tilstand til (kaldes fra create_app, når GAARD_HA=1)."""
    app.wsgi_app = IngressMiddleware(app.wsgi_app)
    # Unikt cookienavn, så vi ikke deler session-cookie med andre apps på samme Home Assistant-adresse.
    app.config["SESSION_COOKIE_NAME"] = "gaardopgaver_session"

    token = os.environ.get("SUPERVISOR_TOKEN")
    if token and not app.config.get("TESTING"):
        options = load_options()
        publisher = SensorPublisher(app.config["DATABASE"], token, options.get("kalender_entitet") or None)
        publisher.start()
        app.extensions["ha_publisher"] = publisher

        @app.after_request
        def _notify(response):
            if request.method == "POST" and response.status_code < 400:
                publisher.notify_change()
            return response
