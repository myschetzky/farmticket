# Ændringslog

## 1.1.1
- Rettet: siden viste "404: Not Found" i Home Assistant. Appen startede uden sine
  miljøvariabler (s6-overlay nulstiller dem) og troede derfor, at den kørte uden for Home Assistant.
  Data gemmes nu også altid i appens datamappe.

## 1.1.0
- Kører som Home Assistant-app med sidepanel (Ingress) for alle brugere
- Automatisk login med Home Assistant-brugeren; Home Assistant-administratorer er administratorer
- Sensorer til dashboardet: åbne og akutte opgaver, dagens plan og næste opgave
- Kalender-feed kan bruges med integrationen Remote Calendar og opdateres straks ved ændringer
- Knap til at indlæse eksempelopgaverne, når systemet er tomt

## 1.0.0
- Første version: opgaver med prioritet, status, kategori og deadline, ugekalender, noter og historik
