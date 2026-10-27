# Gårdopgaver

Et lille ticket-system til landejendommen. Opret opgaver, der skal udbedres, prioritér dem og læg tid i en fælles kalender. Det kører som en **app i Home Assistant** (tidligere kaldt add-on) med eget punkt i sidepanelet og sensorer til dashboardet.

- **Opgaver** med titel, beskrivelse, kategori, sted, prioritet, status, ansvarlig, estimeret tid og deadline
- **Prioritering:** Akut, Høj, Normal og Lav. Listerne sorteres efter prioritet, derefter deadline og derefter alder
- **Kalender:** ugevisning, der bliver til en dagsliste på mobil. Klik i et tomt felt for at planlægge en opgave dér. En opgave kan have flere tidsblokke
- **Overblik:** dagens plan, de næste 7 dage, opgaver over deadline og åbne opgaver uden tid i kalenderen
- **Historik og noter** på hver opgave. Advarsel ved dobbeltbooking
- **I Home Assistant:**
  - Sidepanel for alle brugere og automatisk login med Home Assistant-brugeren
  - Sensorer: åbne og akutte opgaver, dagens plan og næste opgave
  - Kalenderkort via Remote Calendar
- Hele brugerfladen er på dansk

## Installation i Home Assistant

Det kræver Home Assistant OS eller Supervised, altså en installation med app-butik.

### Fra GitHub (anbefalet)

1. Gå til **Indstillinger → Apps**, og åbn butikken. Menuen hed tidligere *Tilføjelsesprogrammer*.
2. Tryk på ⋮ øverst til højre → **Repositories**. Tilføj `https://github.com/myschetzky/Ha`.
3. Find **Gårdopgaver** i butikken → **Installér**. Home Assistant bygger appen lokalt, og det tager et par minutter på en Raspberry Pi.
4. Slå **Vis i sidepanel** til, og tryk **Start**.
5. Åbn **Gårdopgaver** i sidepanelet. Hver Home Assistant-bruger oprettes automatisk første gang, og Home Assistant-administratorer bliver også administratorer her. Som administrator kan du trykke **Indlæs eksempelopgaver** for at få de tre eksempler med.

Opdateringer kommer automatisk i app-butikken, når versionsnummeret i `gaardopgaver/config.yaml` hæves.

### Som lokal app (uden GitHub)

Installér appen **Samba share** eller **Advanced SSH**, og kopiér mappen `gaardopgaver/` til delingen `local_apps`. Gå derefter til butikken → ⋮ → **Søg efter opdateringer**. Gårdopgaver vises nu under *Lokale apps*.

### Dashboardet

Under appens fane **Dokumentation** ligger et færdigt dashboardkort i YAML (se også [`gaardopgaver/DOCS.md`](gaardopgaver/DOCS.md)). Det viser akutte og åbne opgaver, dagens plan og næste opgave. Der er også vejledning til kalenderkortet og et eksempel på en automatisering, der giver besked ved akutte opgaver.

## Data og backup

Data ligger i appens egen datamappe (SQLite) og kommer automatisk med i Home Assistants almindelige backups. Gendannelse sker også dér. Appen stoppes et øjeblik under backup, så databasen gemmes konsistent.

## Teknologi

**Python + Flask + SQLite**, med server-renderede sider og ét stylesheet. Der er ingen JavaScript-build, ingen ekstern database og kun to afhængigheder: Flask og waitress.

I Home Assistant kører det i en lille container baseret på Home Assistants officielle Python-image. Integrationen ligger samlet i `ha.py`:
- **Ingress:** Home Assistant viser siderne og står for login. Kun forespørgsler fra Home Assistants ingress-proxy får adgang.
- **Sensorer:** de sendes via Home Assistants REST API.

## Kør uden Home Assistant (udvikling eller fritstående)

```bash
cd gaardopgaver/app
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py                       # http://localhost:8000 – første bruger oprettes i browseren
```

I den tilstand bruges almindeligt login med brugernavn og adgangskode. Data gemmes i `gaardopgaver/app/data/gaard.db`. Kommandoerne `flask --app gaardopgaver backup` og `flask --app gaardopgaver nulstil-kode BRUGERNAVN` virker også her.

### Tests

```bash
cd gaardopgaver/app
pip install -r requirements-dev.txt
pytest
```

## Projektstruktur

```
repository.yaml                 gør GitHub-repoet til et Home Assistant app-repository
gaardopgaver/                   Home Assistant-appen
  config.yaml                   app-konfiguration (ingress, sidepanel, sensorer, backup)
  Dockerfile                    container-image
  DOCS.md                       dokumentation inkl. dashboardkort (vises i Home Assistant)
  CHANGELOG.md, icon.png, logo.png, translations/
  app/
    run.py                      start af serveren
    gaardopgaver/
      __init__.py               app-opsætning, login-krav, CSRF-beskyttelse
      ha.py                     Home Assistant: ingress, automatisk login, sensorer
      constants.py              prioriteter, statusser, kategorier, eksempelopgaver
      schema.sql, db.py         database
      auth.py                   login, brugere og profil
      tickets.py                overblik, opgaver, status og noter
      schedule.py               ugekalender, tidsblokke og iCal-feed
      templates/, static/       sider og udseende
    tests/                      automatiske tests
```

## Antagelser (kan let justeres)

| Område | Valg | Hvor det ændres |
|---|---|---|
| Prioriteter | Akut (sikkerhed, dyr eller drift i fare), Høj (få dage), Normal (et par uger), Lav (når der er tid) | `constants.py` |
| Statusser | Ny → Planlagt → I gang → Venter (materialer/håndværker) → Udført / Annulleret. Skifter selv til *Planlagt*, når der lægges tid i kalenderen | `constants.py` |
| Kategorier | El og belysning, Hegn og stolper, Ridebane, Stald og dyr, Bygninger, Vand og VVS, Maskiner og redskaber, Have og arealer, Andet | `constants.py` |
| Brugere | I Home Assistant oprettes brugere automatisk. Home Assistant-administratorer er administratorer, andre kan forfremmes under *Brugere*. Alle ser og kan redigere alle opgaver | `ha.py`, `auth.py` |
| Roller | Administrator administrerer brugere og kan slette opgaver. Bruger kan oprette, redigere, prioritere og planlægge | `auth.py` |
| Kalender | En tidsblok ligger inden for én dag. Visningen går fra kl. 6 til 22 og udvides automatisk, hvis noget ligger udenfor | `schedule.py` |
| Ansvarlig | Når en opgave uden ansvarlig får tid i kalenderen, bliver den udførende ansvarlig | `schedule.py` |
| Dobbeltbooking | Giver en advarsel, men blokerer ikke | `schedule.py` |
| Tid | Lokal tid (Home Assistants tidszone) | – |

Oplagte udvidelser: billeder af skaden, gentagne opgaver (fx årligt eftersyn af hegn), og at Home Assistant-automatiseringer selv kan oprette opgaver.
