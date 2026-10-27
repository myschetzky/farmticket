"""Tests af synkronisering til en kalender i Home Assistant (fx Google Kalender)."""

import sqlite3
import uuid
from datetime import date, datetime, timedelta

import pytest

from gaardopgaver import create_app
from gaardopgaver.calendar_sync import SETTING_CALENDAR, CalendarSync, HAError, get_status, set_setting
from gaardopgaver.ha import INGRESS_IP


class FakeHA:
    """Opfører sig som Home Assistants kalender-API: opret/slet/søg og en liste af kalender-entiteter."""

    def __init__(self):
        self.calendars = {"calendar.familie": 3, "calendar.lokal": 7, "calendar.helligdage": 0}
        self.events = {e: [] for e in self.calendars}
        self.fail = False
        self.calls = []

    def states(self):
        return [{"entity_id": e, "attributes": {"friendly_name": e.split(".")[1].title(), "supported_features": f}}
                for e, f in self.calendars.items()] + [{"entity_id": "light.stald", "attributes": {}}]

    def list_events(self, entity_id, start, end):
        if self.fail:
            raise HAError("Home Assistant svarer ikke")
        return [ev for ev in self.events[entity_id]
                if datetime.fromisoformat(ev["start"]) < end and datetime.fromisoformat(ev["end"]) > start]

    def create_event(self, entity_id, event):
        self.calls.append(("create", entity_id, event["summary"]))
        self.events[entity_id].append({**event, "uid": str(uuid.uuid4())})

    def delete_event(self, entity_id, uid):
        self.calls.append(("delete", entity_id, uid))
        before = len(self.events[entity_id])
        self.events[entity_id] = [e for e in self.events[entity_id] if e["uid"] != uid]
        if len(self.events[entity_id]) == before:
            raise HAError("Event not found")

    def close(self):
        pass


@pytest.fixture
def fake():
    return FakeHA()


@pytest.fixture
def app(tmp_path, monkeypatch, fake):
    monkeypatch.setenv("GAARD_HA", "1")
    return create_app({"DATA_DIR": str(tmp_path), "DATABASE": str(tmp_path / "s.db"), "SECRET_KEY": "t",
                       "CSRF_ENABLED": False, "TESTING": True, "HA_CLIENT_FACTORY": lambda: fake})


@pytest.fixture
def client(app):
    c = app.test_client()
    c.environ_base.update({"REMOTE_ADDR": INGRESS_IP, "HTTP_X_INGRESS_PATH": "/api/hassio_ingress/x",
                           "HTTP_X_REMOTE_USER_ID": "u1", "HTTP_X_REMOTE_USER_NAME": "niklas",
                           "HTTP_X_REMOTE_USER_DISPLAY_NAME": "Niklas", "HTTP_X_REMOTE_USER_GROUPS": "system-admin"})
    c.post("/opgaver/ny", data={"title": "Skifte stolper", "category": "Hegn og stolper", "priority": "2",
                                "location": "Ridebane"})
    return c


TOMORROW = (date.today() + timedelta(days=1)).isoformat()


def add_slot(client, start="08:00", end="10:00", day=TOMORROW):
    client.post("/kalender/ny", data={"ticket_id": "1", "date": day, "start": start, "end": end, "user_id": "1"})


def sync(app, fake):
    conn = sqlite3.connect(app.config["DATABASE"])
    try:
        return CalendarSync(conn, fake).run()
    finally:
        conn.close()


def enable(app, entity="calendar.familie"):
    conn = sqlite3.connect(app.config["DATABASE"])
    set_setting(conn, SETTING_CALENDAR, entity)
    conn.close()


def test_nothing_happens_when_disabled(app, client, fake):
    add_slot(client)
    assert sync(app, fake)["ok"] and fake.calls == []


def test_creates_event_with_details(app, client, fake):
    add_slot(client)
    enable(app)
    status = sync(app, fake)
    assert status == {**status, "ok": True, "created": 1, "count": 1}
    [ev] = fake.events["calendar.familie"]
    assert ev["summary"] == "Skifte stolper (Niklas)"
    assert ev["location"] == "Ridebane"
    assert "Prioritet: Høj" in ev["description"]
    assert datetime.fromisoformat(ev["start"]).strftime("%Y-%m-%d %H:%M") == f"{TOMORROW} 08:00"
    # Ingen ændringer → ingen kald
    fake.calls.clear()
    sync(app, fake)
    assert fake.calls == []


def test_moved_slot_is_replaced(app, client, fake):
    add_slot(client)
    enable(app)
    sync(app, fake)
    client.post("/kalender/1", data={"ticket_id": "1", "date": TOMORROW, "start": "13:00", "end": "15:00",
                                     "user_id": "1"})
    status = sync(app, fake)
    assert (status["created"], status["removed"]) == (1, 1)
    [ev] = fake.events["calendar.familie"]
    assert datetime.fromisoformat(ev["start"]).hour == 13


def test_ticket_title_change_updates_event(app, client, fake):
    add_slot(client)
    enable(app)
    sync(app, fake)
    client.post("/opgaver/1/rediger", data={"title": "Skifte 3 stolper", "category": "Hegn og stolper",
                                            "priority": "2", "status": "planlagt", "location": "Ridebane"})
    sync(app, fake)
    assert [e["summary"] for e in fake.events["calendar.familie"]] == ["Skifte 3 stolper (Niklas)"]


def test_deleted_slot_and_manual_deletion(app, client, fake):
    add_slot(client)
    add_slot(client, "13:00", "14:00")
    enable(app)
    sync(app, fake)
    assert len(fake.events["calendar.familie"]) == 2
    client.post("/kalender/1/slet")
    fake.events["calendar.familie"] = [e for e in fake.events["calendar.familie"] if "08:00" not in e["start"]
                                       and "T08:00" not in e["start"]]  # slettet manuelt i Google først
    status = sync(app, fake)
    assert status["ok"] and status["count"] == 1
    client.post("/kalender/2/slet")
    sync(app, fake)
    assert fake.events["calendar.familie"] == []


def test_switch_calendar_and_disable(app, client, fake):
    add_slot(client)
    enable(app)
    sync(app, fake)
    enable(app, "calendar.lokal")
    sync(app, fake)
    assert fake.events["calendar.familie"] == [] and len(fake.events["calendar.lokal"]) == 1
    enable(app, "")
    status = sync(app, fake)
    assert fake.events["calendar.lokal"] == [] and status["count"] == 0


def test_old_slots_are_not_backfilled(app, client, fake):
    add_slot(client, day=(date.today() - timedelta(days=40)).isoformat())
    add_slot(client)
    enable(app)
    sync(app, fake)
    assert len(fake.events["calendar.familie"]) == 1


def test_interrupted_sync_does_not_duplicate(app, client, fake):
    add_slot(client)
    enable(app)
    sync(app, fake)
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.execute("DELETE FROM calendar_events")  # som om programmet stoppede lige efter oprettelsen
    conn.commit()
    conn.close()
    sync(app, fake)
    assert len(fake.events["calendar.familie"]) == 1


def test_ha_unreachable_is_reported(app, client, fake):
    add_slot(client)
    enable(app)
    fake.fail = True
    status = sync(app, fake)
    assert not status["ok"] and "svarer ikke" in status["error"]
    fake.fail = False
    assert sync(app, fake)["count"] == 1
    conn = sqlite3.connect(app.config["DATABASE"])
    assert get_status(conn)["ok"]
    conn.close()


def test_settings_page(app, client, fake):
    html = client.get("/indstillinger").get_data(as_text=True)
    assert "calendar.familie" in html and "calendar.lokal" in html
    assert "Helligdage – kan ikke bruges" in html and "light.stald" not in html
    assert client.post("/indstillinger", data={"action": "save", "calendar": "calendar.helligdage"},
                       follow_redirects=True).get_data(as_text=True).count("kan ikke bruges") >= 1
    client.post("/indstillinger", data={"action": "save", "calendar": "calendar.familie"})
    conn = sqlite3.connect(app.config["DATABASE"])
    assert conn.execute("SELECT value FROM settings WHERE key = 'sync_calendar'").fetchone()[0] == "calendar.familie"
    conn.close()


def test_settings_admin_only(app, client):
    other = app.test_client()
    other.environ_base.update({"REMOTE_ADDR": INGRESS_IP, "HTTP_X_REMOTE_USER_ID": "u2",
                               "HTTP_X_REMOTE_USER_NAME": "mette", "HTTP_X_REMOTE_USER_GROUPS": "system-users"})
    assert other.get("/indstillinger").status_code == 403
