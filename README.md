# Gårdopgaver

Et lille ticket-system til landejendommen. Opret opgaver, der skal udbedres, prioritér dem og læg tid i en fælles kalender.

- **Opgaver** med titel, beskrivelse, kategori, sted, prioritet, status, ansvarlig, estimeret tid og deadline
- **Prioritering**: Akut / Høj / Normal / Lav. Listerne sorteres efter prioritet, så deadline, så alder
- **Kalender**: ugevisning (dagsliste på mobil). Klik i et tomt felt for at planlægge en opgave på det tidspunkt. En opgave kan have flere tidsblokke
- **Overblik**: dagens plan, de næste 7 dage, opgaver over deadline og åbne opgaver, der endnu ikke har tid i kalenderen
- **Historik og noter** på hver opgave (fx “sikringen sprang igen efter regn”). Ændringer af status, prioritet, ansvarlig og planlagt tid logges automatisk
- **Advarsel ved dobbeltbooking**, når samme person er sat på to ting på samme tid
- **Abonnér i telefonens kalender** via et personligt iCal-link (iPhone, Google Kalender, Outlook)
- Fungerer på mobil, tablet og computer. Hele brugerfladen er på dansk

## Teknologivalg

**Python + Flask + SQLite**, med server-renderede sider og ét stylesheet. Der er ingen JavaScript-build og ingen ekstern database.

- Der er kun to afhængigheder: Flask (webframework) og waitress (produktionsserver, som også kører på Windows)
- Alle data ligger i **én fil** (`data/gaard.db`), som er nem at tage backup af og flytte
- Kører fint på en gammel bærbar, en NAS eller en Raspberry Pi på gårdens netværk
- Der er ingen CDN'er eller eksterne tjenester, så systemet virker også uden internet (kun lokalt netværk)
- Koden er omkring 1.400 linjer Python plus HTML-skabeloner, fordelt på få, overskuelige filer

## Installation

Det kræver **Python 3.10 eller nyere**.

```bash
git clone <repo-url> gaardopgaver
cd gaardopgaver

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Start

```bash
python run.py
```

Åbn derefter **http://localhost:8000**. Ved første start bliver du bedt om at oprette den første bruger. Den bliver administrator, og du kan vælge at få de tre eksempelopgaver lagt ind. Andre brugere opretter du bagefter under **Brugere**.

Fra telefoner og andre computere på samme netværk bruger du serverens IP-adresse, fx `http://192.168.1.20:8000`. `run.py` udskriver adressen ved start.

| Valgmulighed | Betydning |
|---|---|
| `python run.py --port 8080` | Brug en anden port |
| `python run.py --host 127.0.0.1` | Kun adgang fra selve maskinen |
| `python run.py --dev` | Udviklingstilstand med automatisk genindlæsning |

## Hvor gemmes data?

| Fil | Indhold |
|---|---|
| `data/gaard.db` | SQLite-databasen med brugere, opgaver, kalendertider og noter |
| `data/secret_key` | Nøgle til login-sessioner. Den laves automatisk; slettes den, bliver alle logget ud |
| `data/backup/` | Sikkerhedskopier, se nedenfor |

Databasen og tabellerne oprettes automatisk ved første start. Mappen kan flyttes med miljøvariablen `GAARD_DATA_DIR=/sti/til/data`.

### Backup

```bash
flask --app gaardopgaver backup
```

Kommandoen laver en konsistent kopi i `data/backup/gaard-ÅÅÅÅMMDD-TTMMSS.db` og kan køres, mens systemet kører. Kopiér den gerne videre til en USB-disk eller cloud-mappe. En simpel natlig backup på Linux (`crontab -e`):

```
0 3 * * * cd /home/pi/gaardopgaver && .venv/bin/flask --app gaardopgaver backup
```

Gendannelse: stop serveren, kopiér backup-filen til `data/gaard.db`, og start igen.

### Glemt adgangskode

```bash
flask --app gaardopgaver nulstil-kode BRUGERNAVN
```

## Kør det permanent (Raspberry Pi / Linux)

Opret `/etc/systemd/system/gaardopgaver.service`:

```ini
[Unit]
Description=Gårdopgaver
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/gaardopgaver
ExecStart=/home/pi/gaardopgaver/.venv/bin/python run.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now gaardopgaver
```

På Windows kan `python run.py` lægges i Opgavestyring (Task Scheduler) med udløseren “Ved opstart”.

**Adgang udefra:** Systemet er lavet til det lokale netværk. Hvis I vil bruge det hjemmefra eller over mobildata, så brug en VPN som fx Tailscale eller WireGuard i stedet for at åbne en port i routeren direkte.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Projektstruktur

```
run.py                      start af serveren
gaardopgaver/
  __init__.py               app-opsætning, login-krav, CSRF-beskyttelse
  constants.py              prioriteter, statusser, kategorier og eksempelopgaver
  schema.sql                databasetabeller
  db.py                     SQLite-hjælpere og backup-kommando
  auth.py                   login, første opsætning, brugere og profil
  tickets.py                overblik, opgaveliste, opret/rediger, status og noter
  schedule.py               ugekalender, tidsblokke og iCal-feed
  dates.py                  danske datoformater
  templates/                HTML-sider (Jinja)
  static/style.css          udseende
tests/test_app.py           automatiske tests
```

## Antagelser (kan let justeres)

| Område | Valg | Hvor det ændres |
|---|---|---|
| Prioriteter | Akut (sikkerhed, dyr eller drift i fare), Høj (få dage), Normal (et par uger), Lav (når der er tid) | `constants.py` |
| Statusser | Ny → Planlagt → I gang → Venter (materialer/håndværker) → Udført / Annulleret. En opgave skifter selv fra *Ny* til *Planlagt*, når den får tid i kalenderen | `constants.py` |
| Kategorier | El og belysning, Hegn og stolper, Ridebane, Stald og dyr, Bygninger, Vand og VVS, Maskiner og redskaber, Have og arealer, Andet | `constants.py` |
| Sted | Fritekst med forslag fra tidligere opgaver (Ridebane, Carport …) | – |
| Roller | **Administrator** kan administrere brugere og slette opgaver. **Bruger** kan alt andet: oprette, redigere, prioritere og planlægge. Alle ser alle opgaver, fordi det er en lille husstand med tillid | `auth.py` |
| Kalender | En tidsblok ligger inden for én dag. Flerdagsarbejde lægges som flere blokke. Ugevisningen viser kl. 6–22 og udvides automatisk, hvis noget ligger udenfor | `schedule.py` |
| Ansvarlig | Når en opgave uden ansvarlig får tid i kalenderen, bliver den person, der skal udføre den, automatisk ansvarlig | `schedule.py` |
| Dobbeltbooking | Giver en advarsel, men blokerer ikke | `schedule.py` |
| Tid | Alt gemmes som lokal dansk tid | – |
| Sletning | Kun administratorer kan slette. Ellers anbefales status *Annulleret*, så historikken bevares | – |

Ikke med i første version, men oplagte udvidelser: billeder af skaden, gentagne opgaver (fx årligt eftersyn af hegn), e-mail-/push-notifikationer og træk-og-slip i kalenderen.
