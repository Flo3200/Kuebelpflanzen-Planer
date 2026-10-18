# Umsetzungsplan – Kübelpflanzen-Planer

Grundlage: Spezifikation „Planungsplattform für die Abholung von Kübelpflanzen“ (Abschnitte 1–22).
Jede Phase endet mit: Tests grün, Abnahmekriterium geprüft, Eintrag in `docs/CHANGELOG.md`.

## Stand (2026-10-18)

| Phase | Stand |
|---|---|
| 1 Grundgerüst | abgeschlossen |
| 2 Stammdaten und Erfassung | abgeschlossen |
| 3 Zeit- und Kostenmodell | abgeschlossen |
| 4 Tourenplanung und Szenarien | abgeschlossen |
| 5 3D-Ladeplanung | abgeschlossen |
| 6 Fahrer-App und Lernen | abgeschlossen |
| 7 Abrechnung, Agenten, Einstellungs-KI | abgeschlossen |
| Datenschutz (Abschnitt 19), Dokumentation (Abschnitt 22) | abgeschlossen |
| 8 Rücklieferung und Kundenzugang | abgeschlossen; offen: Umzug auf einen gehosteten Server |

## Projektstruktur

```
backend/            FastAPI-Anwendung (Python 3.12, uv)
  app/
    core/           config, db (Session + RLS-Kontext), security, i18n-freie Fehlertexte
    models/         SQLAlchemy-2-Modelle (alle mit tenant_id außer globalen Admin-Tabellen)
    settings/       Settings Registry (Definitionen) + Resolver (Admin → Betrieb → Objekt)
    formula/        sicherer Ausdrucks-Parser (eigener Tokenizer + Pratt-Parser, kein eval)
    timemodel/      Zeitmodell, Teamgrößenregeln, Kosten- und Preisberechnung
    routing/        RoutingProvider (Offline, OSRM, ORS, Google) + Cache
    planning/       OR-Tools-Modell, Szenarien, Umplanung
    packing/        3D-Ladeplanung (Extreme Points + Simulated Annealing)
    learning/       Modellanpassung (scipy least_squares, Huber, k-fold CV)
    ai/             AIProvider-Schicht (Anthropic, OpenAI, Fake), Prompts, Verbrauch
    jobs/           Job-Queue (SKIP LOCKED) + Worker
    storage/        StorageBackend (lokal, später S3)
    billing/        Plattform-Abrechnung, Rechnungs-PDF
    pdf/            PDF-Erzeugung mit reportlab (D8): Angebote, Rechnungen, Etiketten
    field/          Ereignisse der Fahrer-App, Messungen
    agents/         Agenten-Tokens, Bestätigungen, Agenten-README
    privacy/        Export, Löschung, Löschfristen
    api/            Router je Bereich
    demo/           Demodaten-Generator
  alembic/          Migrationen (inkl. RLS-Policies)
  tests/
frontend/           React + TypeScript + Vite (Admin, Unternehmer, Fahrer-PWA)
  src/i18n/de.json  alle Oberflächentexte
agent/README.md     Agenten-Anleitung (wird aus der API generiert)
scripts/            backup.sh, restore.sh, dev.sh
docs/               PLAN, DECISIONS, CHANGELOG, APP_GUIDE
docker-compose.yml, Dockerfile, .env.example, Makefile
```

## Phase 1 – Grundgerüst
1. `pyproject.toml`, Konfiguration über `.env` (pydantic-settings), Docker Compose + Dockerfile.
2. Datenbank: SQLAlchemy-Basis mit `tenant_id`, Zeitstempeln, Soft-Delete; Alembic.
3. Row-Level Security: App-Rolle ohne Superuser-Rechte, `FORCE ROW LEVEL SECURITY`, Policy über
   `current_setting('app.tenant_id')`; Admin-Kontext über `app.bypass_rls`.
4. Konten: Argon2, Sitzungs-Cookie (serverseitige Sessions in DB), CSRF (Double-Submit-Token),
   Ratenbegrenzung bei Login, optionales TOTP (Pflicht für Admin einstellbar).
5. Rollen + Berechtigungen (Admin, Unternehmer, Disponent, Fahrer, Kunde).
6. Settings Registry mit Typ, Einheit, Grenzen, Beschreibung, Ebenen, Gruppe, „wichtig“-Flag;
   Resolver mit Herkunftsangabe; Zurücksetzen (Wert, Gruppe, Objekt, Betrieb); Änderungsprotokoll
   mit Rückgängig.
7. Frontend: Design-Tokens (hell/dunkel), Schriften, Layout, Anmeldung, Admin (Betriebe, globale
   Einstellungen, Protokoll), Unternehmer (Übersicht, Einstellungen), generisches Einstellungsformular.
8. Demodaten-Generator (Grundstock), Tests (Resolver, Mandantentrennung, Auth).
*Abnahme:* zwei Betriebe, Trennung, Wert auf drei Ebenen überschreiben/zurücksetzen.

## Phase 2 – Stammdaten und Erfassung
Personal, Fahrzeuge (Regale, Radkästen, Türen), Hilfsmittel, Verfügbarkeit (inkl. Muster), Kunden,
Adressen, Aufträge, Pflanzen, Wege, Fotos (EXIF entfernen), Pflanzenarten-Katalog (global +
Überschreibung). KI-Schicht mit Fake-Provider, Verbrauch, Limits, Prompts versioniert. Nachrichten-
erfassung → Entwurfs-Posteingang → Bestätigen. Foto-Vollständigkeitsprüfung, Bewertungswerkzeug.
*Abnahme:* Nachricht mit Fotos → Entwurf mit Sicherheitswerten → Kunde/Auftrag/Pflanzen.

## Phase 3 – Zeit- und Kostenmodell
Ausdrucks-Parser, Formeln/Versionen/Stufen, Startformel, Teamgrößenregeln, Kosten, Preisformel,
Angebots-PDF. *Abnahme:* Dauer, Arbeitszeit, Teamgröße, Preis pro Auftrag; Formeländerung wirkt sofort.

## Phase 4 – Tourenplanung und Szenarien
RoutingProvider + Cache, OR-Tools (Zeit/Gewicht/Fläche/Volumen, erlaubte Fahrzeuge, teamabhängige
Servicezeit, Mehrfachfahrten über Depot-Kopien, Pausen, Zeitfenster, Auslassen, Unverträglichkeiten,
Fixieren, einstellbare Suche, Regionen-Clustering), Karte, Zeitachse, Verschieben, Umplanung,
Szenarien. *Abnahme:* 100 Aufträge, Nebenbedingungen geprüft, Szenario „+1 Person“.

## Phase 5 – 3D-Ladeplanung
Geometrie (Kübel starr, Krone weich, Kippen), Bedingungen, Extreme-Point-Heuristik + SA,
Kopplung mit Tourenplanung, three.js-Ansicht. *Abnahme:* jede Tour mit Ladeplan oder Begründung.

## Phase 6 – Fahrer-App und Lernen
PWA (Service Worker, IndexedDB-Warteschlange), Zeiterfassung, Pflichtfoto, Ladeansicht,
Abweichungen, QR-Modul; Modellanpassung mit Regularisierung, Huber, k-fold CV, Qualitätsansicht,
Quantil-Puffer, Experimentmodus. *Abnahme:* synthetische Messungen → Parameter wiedergefunden.

## Phase 7 – Abrechnung, Agenten, Einstellungs-KI
Abrechnungsbausteine, PDF-Rechnungen mit Nummernkreis, Agenten-Einwahl (Einmalcode → Token mit
Scopes), Test-/Produktivmodus serverseitig, Bestätigungspflicht, Einstellungs-KI mit Tool-Calls.
*Abnahme:* Agent wählt sich per Link ein, legt per curl Entwurf an; im Produktivmodus Ablehnung.

## Phase 8 – später
Kundenzugang, Rücklieferung als Planungsmodus (Datenmodell ist vorbereitet: `direction`), Hosting.

## Verbesserungsrunde (Auftrag `docs/AUFTRAG_VERBESSERUNGEN.md`, Stand 2026-10-18)

Grundlage: `docs/OFFEN.md`. Reihenfolge A → B → D → E → C → F → G → H. Nach jedem Paket: `make check`,
Eintrag in `CHANGELOG.md`, Entscheidungen in `DECISIONS.md`, Commit und Push. Nichts wird endgültig
gelöscht: wegfallende Funktionen verschwinden aus der Oberfläche und werden per Modul-Schalter
abgeschaltet, Tabellen bleiben, Migrationen sind umkehrbar.

| Paket | Inhalt | Stand |
|---|---|---|
| A | Fokus Logistik, Modul-Schalter, schlanke Eingaben | abgeschlossen |
| B | Pflanzenarten im Hintergrund | abgeschlossen |
| D | Teams durch den Unternehmer | abgeschlossen |
| E | Eigene Kostenpositionen, reine Logistikkosten | offen |
| C | Fahrzeuge per Foto und Chat, Module (Regale, Einbauten, Anhänger) | offen |
| F | Abladezeit per Formel, Graphen, Dashboard | offen |
| G | KI-Ladeanordnung mit Prüfung durch den Packer | offen |
| H | Checkliste für den Produktinhaber, Rückfrage zu OFFEN Punkt 8 | offen |

### Paket A – Fokus Logistik und schlanke Eingaben
- Einstellungsgruppe `modules.*` (Ebenen Admin und Betrieb, Standard aus): `modules.storage` (Lager),
  `modules.customer_billing` (Preise, Angebote und Rechnungen an Endkunden), `modules.portal`
  (Kundenzugang, ersetzt `portal.enabled` per umkehrbarer Migration), `modules.payments`
  (Online-Zahlung, setzt den Kundenzugang voraus).
- Server: Endpunkte eines ausgeschalteten Moduls antworten mit 403 `errors.module_disabled`;
  `/api/auth/me` liefert die Module; Einstellungen eines Moduls (`SettingDef.module`) erscheinen nur,
  wenn es an ist; Datenfelder tragen `info["module"]` und `info["advanced"]`.
- Oberfläche: Menüpunkte, Dashboard-Kacheln, Formularfelder und Schaltflächen eines ausgeschalteten
  Moduls verschwinden; Felder, die keine Berechnung braucht, stehen eingeklappt unter
  „Weitere Angaben“. Feldtabelle in `DECISIONS.md`.
- Frostregel, Rücklieferung und Fahrer-App funktionieren ohne Lager.
- *Abnahme:* Ein neuer Betrieb sieht nur Logistik-Funktionen; jede Maske zeigt nur die Felder für
  die Berechnung; Tests für jedes Modul an und aus.

### Paket B – Pflanzenarten im Hintergrund
- `/species` und die Seite „Pflanzenarten“ nur noch für den Admin (interne Wissensbasis); Betriebe
  lesen die Arten nicht mehr in der Oberfläche.
- Neue Spalten an der Pflanze (`species_name`, `tip_tendency`, `soil_kg_per_l`, …) mit
  Sicherheitswerten; die KI (Foto-Auswertung, Nachrichtenerfassung) setzt Art und Eigenschaften,
  fehlende Werte kommen aus der Wissensbasis. Umkehrbare Datenmigration kopiert die Werte der
  bisherigen Art an jede Pflanze.
- Gewichtsschätzung, Packregeln, Frostregel und Lernen lesen nur noch die Werte der Pflanze.
- *Abnahme:* Pflanzen ohne Artverwaltung haben alle nötigen Eigenschaften; betroffene Tests grün.

### Paket D – Teams durch den Unternehmer
- Team-Oberfläche mit Mitgliedern, Standard-Fahrzeug (mit Modulen aus Paket C, sobald vorhanden),
  gültigen Wochentagen und Zeitraum; Verfügbarkeitskalender zeigt Teams mit Konflikten
  (Mitglied abwesend, Fahrzeug in Wartung, Person in zwei Teams).
- Planung mit `planning.form_teams = fixed`: Fehlende oder zu kleine Teams ergeben Warnungen mit
  Begründung je Stopp und einen Lösungshinweis (welches Team, welche Person), nie einen Fehler.
- *Abnahme:* Mit festen Teams entsteht immer ein Plan; nicht einplanbare Stopps haben einen
  verständlichen Grund.

### Paket E – Kosten
- Tabelle `cost_items`: Name, Betrag, Bezug (pro km, Stunde, Einsatz, Tag, Monat anteilig, Pflanze),
  Bezugsobjekt (Betrieb, Fahrzeug, Person, Modul). Fließen in Schätzung, Tourkosten und Szenarien ein.
- Kostenanzeige „Logistikkosten“ (Personal, Fahrzeug, eigene Positionen) getrennt von Preis und
  Marge; `costs.margin_pct` und `costs.overhead_pct` Standard 0 %.
- *Abnahme:* Eine eigene Kostenposition ändert sichtbar Tour- und Auftragskosten; Aufschlüsselung
  pro Tour nachvollziehbar.

### Paket C – Fahrzeuge per Foto und Chat, modular
- KI-Aufgaben `ai.model.vehicle_photo` (Laderaum-Foto mit A4/Zollstock) und `ai.model.vehicle_chat`
  (Beschreibung in Worten, Rückfragen, spätere Änderungen) mit versionierten Prompts, Kostenerfassung
  und Testsätzen im Bewertungswerkzeug; das Testmodell liefert ohne Schlüssel plausible Entwürfe.
- Ergebnis immer als Fahrzeug-Entwurf mit Sicherheitswerten, Rückfragen bei unsicheren Werten,
  Bestätigung durch den Unternehmer, Protokoll.
- Wiederverwendbare Module (`vehicle_modules`: Regal, Einbau, Anhänger) mit Zuordnung zu mehreren
  Fahrzeugen; Anhänger + Zugfahrzeug als Kombination. Die Ladeplanung liest Regale aus Modulen.
- *Abnahme:* Fahrzeug vollständig per Chat und per Foto als Entwurf anlegen und bestätigen; Module
  mehreren Fahrzeugen zuordnen; Ladeplanung nutzt das Ergebnis.

### Paket F – Abladezeit, Graphen, Dashboard
- Formel `unload` im Formeleditor (Fixzeit + Anteil je Pflanze und je kg), lernbar aus den neuen
  Fahrer-Ereignissen „Abladen beginnt“/„Abladen fertig“ am Betrieb.
- Planung zeigt je Tour Ankunft am Betrieb und Abladefenster.
- Graphen: Auslastung Personal/Fahrzeuge je Tag, Touren im Zeitverlauf, Abladefenster am Betrieb,
  Kosten je Tag und je Pflanze, Genauigkeit der Zeitschätzung. Dashboard neu: heute/morgen, offene
  Entwürfe, nicht einplanbare Aufträge mit Grund, Kosten der Woche, Graphen.
- *Abnahme:* Abladezeit kommt aus der Formel und ändert sich mit der Pflanzenmenge; Graphen
  funktionieren mit leeren und mit Demodaten.

### Paket G – KI-Ladeanordnung
- KI-Aufgabe `ai.model.load_layout`: strukturiertes JSON mit Positionen aus Fahrzeuggeometrie,
  Pflanzenliste und Tourreihenfolge. Der Packer übernimmt sie als Startlösung, prüft alle Regeln und
  verbessert sie. Einstellung `packing.mode`: `rules` (Standard), `ai_start`, `compare`.
- Vergleichstest mit Demodaten (Punktzahl, Verstöße, Rechenzeit, KI-Kosten).
- *Abnahme:* KI-Vorschläge werden nie ungeprüft übernommen; Vergleichsbericht in `DECISIONS.md`.

### Paket H – Konfiguration und Rückfragen
- Keine Programmierung: Checkliste für den Produktinhaber (API-Schlüssel und Ausgabenlimit,
  Rechnungssteller, Einwilligungstext, Zwei-Faktor-Pflicht, Inhaber-Passwort, Hosting) und die
  Rückfrage zu Punkt 8 aus `OFFEN.md` (vor Paket A gestellt).
