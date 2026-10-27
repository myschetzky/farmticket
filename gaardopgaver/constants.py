"""Faste valgmuligheder. Ret her, hvis listerne skal tilpasses."""

# Lavere tal = vigtigere. Bruges også til sortering.
PRIORITIES = {
    1: "Akut",
    2: "Høj",
    3: "Normal",
    4: "Lav",
}
PRIORITY_HELP = {
    1: "Sikkerhed, dyr eller drift er i fare – løses straks",
    2: "Bør løses inden for få dage",
    3: "Løses inden for et par uger",
    4: "Når der er tid",
}
DEFAULT_PRIORITY = 3

STATUSES = [
    ("ny", "Ny"),
    ("planlagt", "Planlagt"),
    ("i_gang", "I gang"),
    ("venter", "Venter (materialer/håndværker)"),
    ("udfoert", "Udført"),
    ("annulleret", "Annulleret"),
]
STATUS_LABELS = dict(STATUSES)
OPEN_STATUSES = ("ny", "planlagt", "i_gang", "venter")
CLOSED_STATUSES = ("udfoert", "annulleret")

CATEGORIES = [
    "El og belysning",
    "Hegn og stolper",
    "Ridebane",
    "Stald og dyr",
    "Bygninger",
    "Vand og VVS",
    "Maskiner og redskaber",
    "Have og arealer",
    "Andet",
]

# Eksempelopgaver, som kan indlæses ved første opsætning.
EXAMPLE_TICKETS = [
    {
        "title": "Fejlfinde ridebanelys, der springer sikring",
        "description": "Lyset på ridebanen slår HPFI/sikringen fra, typisk efter regnvejr. "
        "Tjek armaturer, samledåser og kabel for fugt. Overvej elektriker, hvis fejlen ikke findes.",
        "category": "El og belysning",
        "location": "Ridebane",
        "priority": 2,
        "estimate_hours": 3,
    },
    {
        "title": "Skifte knækkede stolper på ridebane",
        "description": "Et par stolper i hegnet omkring ridebanen er knækket. "
        "Tæl antal, køb nye stolper og skift dem.",
        "category": "Hegn og stolper",
        "location": "Ridebane",
        "priority": 2,
        "estimate_hours": 4,
    },
    {
        "title": "Etablere udtag til julelys ved carport og overdækket terrasse",
        "description": "Udendørs stikkontakter (IP44) ved carport og overdækket terrasse, "
        "gerne med timer/skumringsrelæ. Skal være klar inden 1. advent.",
        "category": "El og belysning",
        "location": "Carport / terrasse",
        "priority": 3,
        "estimate_hours": 5,
        "due_date_month_day": (11, 28),
    },
]
