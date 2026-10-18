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
