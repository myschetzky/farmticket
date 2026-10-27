"""Tests af Home Assistant-tilstanden (ingress, automatisk login, sensorer)."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from gaardopgaver import create_app
from gaardopgaver.db import query
from gaardopgaver.ha import INGRESS_IP, build_sensors

PREFIX = "/api/hassio_ingress/abc123"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("GAARD_HA", "1")
    return create_app({"DATA_DIR": str(tmp_path), "DATABASE": str(tmp_path / "ha.db"),
                       "SECRET_KEY": "test", "CSRF_ENABLED": False, "TESTING": True})


def ingress_client(app, user_id="u1", username="niklas", name="Niklas", groups="system-admin,system-users"):
    c = app.test_client()
    c.environ_base.update({
        "REMOTE_ADDR": INGRESS_IP,
        "HTTP_X_INGRESS_PATH": PREFIX,
        "HTTP_X_REMOTE_USER_ID": user_id,
        "HTTP_X_REMOTE_USER_NAME": username,
        "HTTP_X_REMOTE_USER_DISPLAY_NAME": name,
    })
    if groups is not None:
        c.environ_base["HTTP_X_REMOTE_USER_GROUPS"] = groups
    return c


def test_ingress_auto_login_creates_user_and_prefixes_links(app):
    c = ingress_client(app)
    resp = c.get("/")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert f'href="{PREFIX}/opgaver"' in html
    assert f'href="{PREFIX}/static/style.css' in html
    assert "Kom i gang" in html  # tom database → tilbud om eksempelopgaver
    with app.app_context():
        u = query("SELECT * FROM users", one=True)
    assert (u["ha_user_id"], u["name"], u["is_admin"]) == ("u1", "Niklas", 1)


def test_redirects_keep_ingress_prefix(app):
    c = ingress_client(app)
    resp = c.post("/opgaver/ny", data={"title": "Skift pære i stald", "category": "Stald og dyr", "priority": "3"})
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith(f"{PREFIX}/opgaver/")


def test_non_admin_ha_user_and_name_sync(app):
    ingress_client(app).get("/")  # administrator først
    c = ingress_client(app, user_id="u2", username="mette", name="Mette", groups="system-users")
    assert c.get("/").status_code == 200
    assert c.get("/brugere").status_code == 403
    ingress_client(app, user_id="u2", username="mette", name="Mette Hansen", groups="system-users").get("/")
    with app.app_context():
        assert query("SELECT name FROM users WHERE ha_user_id = 'u2'", one=True)["name"] == "Mette Hansen"


def test_first_user_admin_when_groups_unknown(app):
    ingress_client(app, groups=None).get("/")
    ingress_client(app, user_id="u2", username="mette", groups=None).get("/")
    with app.app_context():
        admins = {r["username"]: r["is_admin"] for r in query("SELECT username, is_admin FROM users")}
    assert admins == {"niklas": 1, "mette": 0}


def test_deactivated_ha_user_is_blocked(app):
    admin = ingress_client(app)
    admin.get("/")
    other = ingress_client(app, user_id="u2", username="mette", groups="system-users")
    other.get("/")
    with app.app_context():
        uid = query("SELECT id FROM users WHERE ha_user_id = 'u2'", one=True)["id"]
    admin.post(f"/brugere/{uid}", data={"name": "Mette"})  # uden 'active' → deaktiveret
    assert other.get("/").status_code == 403


def test_direct_access_only_allows_feed(app):
    ingress_client(app).get("/")
    with app.app_context():
        token = query("SELECT ical_token FROM users", one=True)["ical_token"]
    direct = app.test_client()
    direct.environ_base["REMOTE_ADDR"] = "172.30.32.1"
    assert direct.get("/").status_code == 403
    assert direct.get("/login").status_code == 403
    # Forfalskede headers fra en anden adresse giver ikke adgang
    direct.environ_base["HTTP_X_REMOTE_USER_ID"] = "u1"
    assert direct.get("/opgaver").status_code == 403
    feed = direct.get(f"/kalender/feed/{token}.ics")
    assert feed.status_code == 200 and "BEGIN:VCALENDAR" in feed.get_data(as_text=True)


def test_profile_shows_internal_feed_url(app):
    html = ingress_client(app).get("/profil").get_data(as_text=True)
    assert ":8099/kalender/feed/" in html
    assert PREFIX + "/kalender/feed" not in html
    assert "Skift adgangskode" not in html


def test_existing_local_user_is_linked(tmp_path, monkeypatch):
    # En database fra den selvstændige version tages i brug i Home Assistant
    plain = create_app({"DATA_DIR": str(tmp_path), "DATABASE": str(tmp_path / "x.db"),
                        "SECRET_KEY": "t", "CSRF_ENABLED": False})
    plain.test_client().post("/opsaetning", data={"name": "Niklas", "username": "niklas",
                                                  "password": "hemmelig", "password2": "hemmelig"})
    monkeypatch.setenv("GAARD_HA", "1")
    app = create_app({"DATA_DIR": str(tmp_path), "DATABASE": str(tmp_path / "x.db"),
                      "SECRET_KEY": "t", "CSRF_ENABLED": False})
    ingress_client(app, groups="system-users").get("/")
    with app.app_context():
        rows = query("SELECT username, ha_user_id, is_admin FROM users")
    assert [tuple(r) for r in rows] == [("niklas", "u1", 1)]


def test_build_sensors(app):
    c = ingress_client(app)
    c.post("/opgaver/ny", data={"title": "Hegn er væltet", "category": "Hegn og stolper", "priority": "1"})
    c.post("/opgaver/ny", data={"title": "Male låge", "category": "Bygninger", "priority": "4"})
    now = datetime.now()
    later = now + timedelta(hours=1)
    c.post("/kalender/ny", data={"ticket_id": "1", "date": later.date().isoformat(),
                                 "start": later.strftime("%H:00"), "end": (later + timedelta(hours=1)).strftime("%H:00")
                                 if later.hour < 23 else "23:59", "user_id": "1"})
    conn = sqlite3.connect(app.config["DATABASE"])
    sensors = build_sensors(conn, now=now)
    conn.close()
    open_s = sensors["sensor.gaardopgaver_aabne_opgaver"]
    assert open_s["state"] == 2
    assert open_s["attributes"]["akut"] == 1 and open_s["attributes"]["lav"] == 1
    assert open_s["attributes"]["uden_tid"] == 1
    assert sensors["sensor.gaardopgaver_akutte_opgaver"]["attributes"]["opgaver"] == ["Hegn er væltet"]
    nxt = sensors["sensor.gaardopgaver_naeste_opgave"]
    assert nxt["state"] == "Hegn er væltet" and nxt["attributes"]["person"] == "Niklas"
