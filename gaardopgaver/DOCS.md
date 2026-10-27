# Gårdopgaver

Opgaver (tickets) til landejendommen: opret ting, der skal udbedres, prioritér dem og læg tid i kalenderen. Alt sker direkte i Home Assistant.

## Sådan virker det i Home Assistant

- **Sidepanel:** "Gårdopgaver" står i sidepanelet for alle brugere. Hele systemet åbner inde i Home Assistant og fungerer også i mobil-appen og på en vægtablet.
- **Login:** Der er ingen ekstra adgangskoder. Den, der er logget ind i Home Assistant, er automatisk logget ind i Gårdopgaver. Administratorer i Home Assistant er også administratorer her. Andre brugere oprettes automatisk som almindelige brugere, første gang de åbner panelet.
- **Sensorer til dashboardet:** Appen opretter tre sensorer, som opdateres med det samme, når noget ændres, og ellers hvert 5. minut:

| Sensor | Tilstand | Attributter |
|---|---|---|
| `sensor.gaardopgaver_aabne_opgaver` | Antal åbne opgaver | `akut`, `hoej`, `normal`, `lav`, `venter`, `over_deadline`, `uden_tid`, `i_dag` (dagens plan), `kommende_7_dage` |
| `sensor.gaardopgaver_akutte_opgaver` | Antal akutte opgaver | `opgaver` (titler) |
| `sensor.gaardopgaver_naeste_opgave` | Titel på næste planlagte opgave | `start`, `slut`, `person`, `sted`, `prioritet` |

- **Google Kalender eller anden kalender:** Planlagte tider kan lægges direkte ind i jeres egen kalender, se nedenfor.
- **Data og backup:** Alt gemmes i appens egen datamappe og kommer automatisk med i Home Assistants backups. Appen stoppes et øjeblik under backup, så databasen altid gemmes i en hel og konsistent tilstand.

## Google Kalender (eller en anden kalender)

Gårdopgaver kan lægge alle planlagte tider ind i en kalender, som Home Assistant kender. Det kan fx være jeres fælles Google Kalender. Flyttes eller slettes en tid i Gårdopgaver, følger kalenderen med inden for få sekunder.

1. **Forbind Google Kalender med Home Assistant**, hvis det ikke allerede er gjort: **Indstillinger → Enheder og tjenester → Tilføj integration → Google Calendar**. Home Assistant guider dig gennem det. Første gang skal der oprettes en Google Cloud-nøgle, og [Home Assistants vejledning](https://www.home-assistant.io/integrations/google/) viser trinene. Hver Google-kalender bliver en entitet, fx `calendar.familie`.
2. Åbn **Gårdopgaver → Indstillinger** (kun administratorer), vælg kalenderen, og tryk **Gem**.

Begivenhederne får opgavens titel og navnet på den, der udfører den, fx *Skifte knækkede stolper på ridebane (Niklas)*. Beskrivelsen viser prioritet og note, og opgavens sted bliver sted.

Godt at vide:
- **Hvilke kalendere kan vælges:** Alle kalendere i Home Assistant, som kan både oprette og slette begivenheder: Google Calendar og Local Calendar. CalDAV-kalendere (fx iCloud) kan kun oprette og vises derfor som "kan ikke bruges".
- **Google skal have skriveadgang:** Er Google-integrationen sat op med kun læseadgang, kan kalenderen ikke vælges. Det ændres under integrationens **Konfigurér** → *Read/Write access*.
- **Ændringer laves i Gårdopgaver:** En begivenhed, der ændres eller slettes direkte i Google, bliver ikke ført tilbage til Gårdopgaver.
- **Kalenderen styres af Gårdopgaver:** Slås synkroniseringen fra, eller vælges en anden kalender, fjernes Gårdopgavers begivenheder fra den gamle kalender. Andre begivenheder røres aldrig.
- **Gamle tider:** Tider, der sluttede for mere end 30 dage siden, lægges ikke ind.

## Kort til dashboardet

Rediger dashboardet → **Tilføj kort** → **Manuel**, og indsæt koden nedenfor.

Udskift `/local_gaardopgaver` med panelets adresse. Du finder den i adresselinjen, når Gårdopgaver er åbent i sidepanelet. Er appen installeret fra GitHub i stedet for som lokal app, ligner den fx `/a1b2c3d4_gaardopgaver`.

```yaml
type: vertical-stack
cards:
  - type: horizontal-stack
    cards:
      - type: tile
        entity: sensor.gaardopgaver_akutte_opgaver
        name: Akutte
        color: red
        tap_action:
          action: navigate
          navigation_path: /local_gaardopgaver
      - type: tile
        entity: sensor.gaardopgaver_aabne_opgaver
        name: Åbne opgaver
        color: green
        tap_action:
          action: navigate
          navigation_path: /local_gaardopgaver
  - type: markdown
    title: Gårdopgaver i dag
    content: |
      {% set plan = state_attr('sensor.gaardopgaver_aabne_opgaver', 'i_dag') or [] %}
      {% for p in plan %}
      - **{{ p.tid }}** {{ p.opgave }}{% if p.person %} · {{ p.person }}{% endif %}
      {% else %}
      Intet planlagt i dag.
      {% endfor %}

      Næste: **{{ states('sensor.gaardopgaver_naeste_opgave') }}**
      {%- set start = state_attr('sensor.gaardopgaver_naeste_opgave', 'start') %}
      {%- if start %} ({{ as_datetime(start).strftime('%d/%m kl. %H:%M') }}){% endif %}
  - type: button
    name: Åbn Gårdopgaver
    icon: mdi:barn
    tap_action:
      action: navigate
      navigation_path: /local_gaardopgaver
```

### Kalenderkort (valgfrit)

Bruger I synkronisering til Google Kalender (se ovenfor), kan kalenderkortet bare vise den kalender, fx `calendar.familie`. Ellers kan planen hentes direkte fra Gårdopgaver:

1. Åbn Gårdopgaver → dit navn øverst til højre. Kopiér adressen under **Alle opgaver**. Den ligner `http://local-gaardopgaver:8099/kalender/feed/….ics`.
2. Gå til **Indstillinger → Enheder og tjenester → Tilføj integration → Remote Calendar**. Kald kalenderen **Gårdopgaver**, og indsæt adressen.
3. Tilføj et kalenderkort på dashboardet:

```yaml
type: calendar
initial_view: listWeek
entities:
  - calendar.gardopgaver
```

Remote Calendar henter normalt kun nye data én gang i døgnet. Appen beder derfor kalenderen om at opdatere med det samme, hver gang noget ændres. Det kræver, at indstillingen **Kalender-entitet** under appens **Konfiguration** passer med kalenderens entitets-id. Standardværdien er `calendar.gardopgaver`.

### Notifikation ved akutte opgaver (eksempel)

```yaml
alias: Besked ved akut gårdopgave
triggers:
  - trigger: numeric_state
    entity_id: sensor.gaardopgaver_akutte_opgaver
    above: 0
actions:
  - action: notify.notify
    data:
      title: Akut gårdopgave
      message: >-
        {{ state_attr('sensor.gaardopgaver_akutte_opgaver', 'opgaver') | join(', ') }}
```

## Konfiguration

| Indstilling | Betydning |
|---|---|
| `kalender_entitet` | Valgfri. Entiteten fra Remote Calendar, der skal opdateres ved ændringer. Lad den stå tom, hvis du ikke bruger kalenderkortet. |

**Netværk (valgfrit):** Porten `8099/tcp` er lukket som standard. Åbn den kun, hvis I vil abonnere på kalenderen fra telefonernes egen kalender-app. Uden for Home Assistant kan der kun hentes kalender-feeds via porten. Feedet er beskyttet af et personligt link, og selve systemet kan ikke åbnes den vej.

## Prioriteter og statusser

- **Prioritet:** Akut (sikkerhed, dyr eller drift er i fare), Høj (få dage), Normal (et par uger), Lav (når der er tid).
- **Status:** Ny → Planlagt → I gang → Venter (materialer/håndværker) → Udført / Annulleret. En opgave skifter selv til *Planlagt*, når den får tid i kalenderen.
