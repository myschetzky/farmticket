"""Synkronisering af planlagte tider til en valgfri kalender i Home Assistant (fx Google Kalender).

Gårdopgaver opretter én begivenhed pr. tidsblok i den valgte kalender. Flyttes, ændres eller slettes
en tidsblok, slettes den gamle begivenhed og en ny oprettes (Google-kalendere i Home Assistant kan
oprette og slette, men ikke ændre). Hver begivenhed får et usynligt mærke i beskrivelsen, så den
altid kan genfindes – også hvis noget gik galt halvvejs.
"""

import hashlib
import json
import logging
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from .constants import PRIORITIES
from .dates import DT_FORMAT

log = logging.getLogger(__name__)

FEATURE_CREATE = 1
FEATURE_DELETE = 2
CREATE_WINDOW_DAYS = 30  # tider, der sluttede for mere end 30 dage siden, lægges ikke ind
SETTING_CALENDAR = "sync_calendar"
SETTING_STATUS = "sync_status"
SETTING_INSTALL = "install_id"


class HAError(Exception):
    pass


# ---------- Indstillinger (virker med både Flask- og trådens egen forbindelse) ----------

def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def get_status(conn):
    try:
        return json.loads(get_setting(conn, SETTING_STATUS, "{}"))
    except ValueError:
        return {}


def _install_id(conn):
    value = get_setting(conn, SETTING_INSTALL)
    if not value:
        value = secrets.token_hex(4)
        set_setting(conn, SETTING_INSTALL, value)
    return value


# ---------- Home Assistant-klient (REST + websocket via Supervisor) ----------

class HAClient:
    def __init__(self, token, base="http://supervisor/core"):
        self.token = token
        self.base = base
        self._ws = None
        self._msg_id = 0

    def _rest(self, path):
        req = urllib.request.Request(f"{self.base}{path}", headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read() or b"null")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise HAError(f"Home Assistant svarer ikke ({exc})") from exc

    def states(self):
        return self._rest("/api/states")

    def list_events(self, entity_id, start, end):
        query = urllib.parse.urlencode({"start": start.isoformat(), "end": end.isoformat()})
        return self._rest(f"/api/calendars/{entity_id}?{query}") or []

    def _ws_call(self, payload):
        import websocket  # websocket-client

        try:
            if self._ws is None:
                url = self.base.replace("http://", "ws://").replace("https://", "wss://") + "/websocket"
                ws = websocket.create_connection(url, timeout=20)
                if json.loads(ws.recv()).get("type") != "auth_required":
                    raise HAError("Uventet svar fra Home Assistant")
                ws.send(json.dumps({"type": "auth", "access_token": self.token}))
                if json.loads(ws.recv()).get("type") != "auth_ok":
                    raise HAError("Home Assistant afviste adgangen")
                self._ws = ws
            self._msg_id += 1
            self._ws.send(json.dumps({"id": self._msg_id, **payload}))
            while True:
                msg = json.loads(self._ws.recv())
                if msg.get("id") == self._msg_id and msg.get("type") == "result":
                    break
        except HAError:
            self.close()
            raise
        except Exception as exc:  # noqa: BLE001 – netværk/websocket-fejl af enhver art
            self.close()
            raise HAError(f"Forbindelsen til Home Assistant fejlede ({exc})") from exc
        if not msg.get("success"):
            raise HAError((msg.get("error") or {}).get("message") or "Ukendt fejl fra Home Assistant")
        return msg.get("result")

    def create_event(self, entity_id, event):
        self._ws_call({"type": "calendar/event/create", "entity_id": entity_id, "event": event})

    def delete_event(self, entity_id, uid):
        self._ws_call({"type": "calendar/event/delete", "entity_id": entity_id, "uid": uid})

    def close(self):
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None


def list_calendars(client):
    """Alle kalendere i Home Assistant: [{entity_id, name, can_sync}], sorteret efter navn."""
    result = []
    for s in client.states():
        if not s.get("entity_id", "").startswith("calendar."):
            continue
        features = int(s.get("attributes", {}).get("supported_features") or 0)
        result.append({
            "entity_id": s["entity_id"],
            "name": s.get("attributes", {}).get("friendly_name") or s["entity_id"],
            "can_sync": bool(features & FEATURE_CREATE and features & FEATURE_DELETE),
        })
    return sorted(result, key=lambda c: c["name"].lower())


# ---------- Selve synkroniseringen ----------

SLOT_SQL = """
SELECT s.id, s.starts_at, s.ends_at, s.note, t.title, t.priority, t.location, u.name AS user_name
  FROM time_slots s JOIN tickets t ON t.id = s.ticket_id
  LEFT JOIN users u ON u.id = s.user_id
"""


def _local(value):
    """'YYYY-MM-DD HH:MM' (lokal tid) -> tidszone-bevidst datetime."""
    return datetime.strptime(value, DT_FORMAT).astimezone()


def build_event(slot, marker):
    lines = [f"Prioritet: {PRIORITIES[slot['priority']]}"]
    if slot["user_name"]:
        lines.append(f"Udføres af: {slot['user_name']}")
    if slot["note"]:
        lines.append(f"Note: {slot['note']}")
    lines += ["", f"Planlagt i Gårdopgaver [{marker}]"]
    summary = slot["title"] + (f" ({slot['user_name']})" if slot["user_name"] else "")
    event = {
        "summary": summary,
        "description": "\n".join(lines),
        "start": _local(slot["starts_at"]).isoformat(),
        "end": _local(slot["ends_at"]).isoformat(),
    }
    if slot["location"]:
        event["location"] = slot["location"]
    return event


def fingerprint(event):
    return hashlib.sha1(json.dumps(event, sort_keys=True).encode()).hexdigest()


class CalendarSync:
    def __init__(self, conn, client):
        self.conn = conn
        self.client = client
        self.conn.row_factory = sqlite3.Row

    def _find_uid(self, entity_id, marker, starts_at, ends_at):
        start = _local(starts_at) - timedelta(minutes=1)
        end = _local(ends_at) + timedelta(minutes=1)
        for ev in self.client.list_events(entity_id, start, end):
            if f"[{marker}]" in (ev.get("description") or ""):
                return ev.get("uid")
        return None

    def _remove(self, row, marker):
        """Slet begivenheden, hvis den stadig findes (den kan være slettet manuelt i kalenderen)."""
        uid = self._find_uid(row["entity_id"], marker, row["starts_at"], row["ends_at"])
        if uid:
            self.client.delete_event(row["entity_id"], uid)
        self.conn.execute("DELETE FROM calendar_events WHERE slot_id = ?", (row["slot_id"],))
        self.conn.commit()

    def run(self, now=None):
        now = now or datetime.now()
        entity = get_setting(self.conn, SETTING_CALENDAR) or None
        install = _install_id(self.conn)
        slots = {r["id"]: r for r in self.conn.execute(SLOT_SQL)}
        rows = {r["slot_id"]: r for r in self.conn.execute("SELECT * FROM calendar_events")}
        created = removed = 0
        try:
            # 1) Fjern begivenheder for slettede/ændrede tider og fra en tidligere valgt kalender.
            for slot_id, row in rows.items():
                slot = slots.get(slot_id)
                marker = f"gaardopgaver:{install}:{slot_id}"
                keep = (slot is not None and row["entity_id"] == entity
                        and row["fingerprint"] == fingerprint(build_event(slot, marker)))
                if not keep:
                    self._remove(row, marker)
                    removed += 1

            # 2) Opret begivenheder for tider, der ikke er i kalenderen endnu.
            if entity:
                synced = {r["slot_id"] for r in self.conn.execute("SELECT slot_id FROM calendar_events")}
                cutoff = (now - timedelta(days=CREATE_WINDOW_DAYS)).strftime(DT_FORMAT)
                for slot_id, slot in sorted(slots.items(), key=lambda kv: kv[1]["starts_at"]):
                    if slot_id in synced or slot["ends_at"] < cutoff:
                        continue
                    marker = f"gaardopgaver:{install}:{slot_id}"
                    event = build_event(slot, marker)
                    # Findes den allerede (fx efter en afbrudt synkronisering)? Så genbruges den.
                    uid = self._find_uid(entity, marker, slot["starts_at"], slot["ends_at"])
                    if not uid:
                        self.client.create_event(entity, event)
                        uid = self._find_uid(entity, marker, slot["starts_at"], slot["ends_at"])
                    self.conn.execute(
                        "INSERT INTO calendar_events (slot_id, entity_id, uid, fingerprint, starts_at, ends_at)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (slot_id, entity, uid, fingerprint(event), slot["starts_at"], slot["ends_at"]),
                    )
                    self.conn.commit()
                    created += 1
            status = {"ok": True, "time": now.strftime(DT_FORMAT), "created": created, "removed": removed,
                      "count": self.conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]}
        except HAError as exc:
            if get_status(self.conn).get("error") != str(exc):  # samme fejl logges kun én gang
                log.warning("Kalendersynkronisering fejlede: %s", exc)
            status = {"ok": False, "time": now.strftime(DT_FORMAT), "error": str(exc)}
        finally:
            self.client.close()
        set_setting(self.conn, SETTING_STATUS, json.dumps(status))
        return status
