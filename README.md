# Kübelpflanzen-Planer

Planungsplattform für Gärtnereien, die Kübelpflanzen zur Überwinterung abholen: Erfassung mit KI,
Zeit- und Preismodell, Tourenplanung (OR-Tools), 3D-Ladeplanung, Fahrer-App (offline), Lernen aus
Messungen, Rücklieferung im Frühjahr, Kundenzugang mit Online-Zahlung, Abrechnung der Plattform,
Agenten-API und Einstellungs-KI. Mehrere Betriebe (Mandanten)
mit strikter Datentrennung (PostgreSQL Row-Level Security).

- Funktionsbeschreibung: [docs/APP_GUIDE.md](docs/APP_GUIDE.md)
- Plan und Phasen: [docs/PLAN.md](docs/PLAN.md), Änderungen: [docs/CHANGELOG.md](docs/CHANGELOG.md)
- Entscheidungen: [docs/DECISIONS.md](docs/DECISIONS.md)
- Anleitung für KI-Agenten: [agent/README.md](agent/README.md) (live unter `/agent/README.md`)
- API: `/api/docs` (OpenAPI unter `/api/openapi.json`)

## Aufbau

| Teil | Technik |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL 16/17 |
| Planung | OR-Tools (Touren), eigener Packer (Ladeplan), SciPy (Modellanpassung) |
| Frontend | React, TypeScript, Vite; three.js (3D), Leaflet (Karte), Recharts |
| Fahrer-App | dieselbe App unter `/fahrer`, PWA mit Service Worker und IndexedDB |
| Kundenzugang | dieselbe App unter `/kunde`, Anmeldung über persönlichen Link |
| Hintergrundaufträge | Warteschlange in PostgreSQL, Worker-Prozess (oder eingebettet) |
| PDF | reportlab (Angebote, Rechnungen, Etiketten) |

Verzeichnisse: `backend/app` (API, Modelle, Planung, Packer, Lernen, KI, Abrechnung),
`backend/tests`, `frontend/src`, `docs`, `agent`, `scripts`, `docker`.

## Installation

### Mit Docker (empfohlen für einen Server)

```bash
cp .env.example .env
```

In `.env` mindestens setzen: `KP_SECRET_KEY` (lange Zufallszeichenkette), `KP_ENCRYPTION_KEY`
(Fernet-Schlüssel, Befehl steht in der Datei), `KP_INITIAL_ADMIN_EMAIL`,
`KP_INITIAL_ADMIN_PASSWORD` und die drei Datenbank-Passwörter. Dann:

```bash
docker compose up -d --build
```

Die App läuft unter http://localhost:8000. Beim ersten Start werden die Datenbank migriert und das
Admin-Konto angelegt.

### Lokal (Entwicklung)

Voraussetzungen: Python 3.12 mit [uv](https://docs.astral.sh/uv/), Node.js 22 oder neuer,
PostgreSQL 16 oder 17. `scripts/dev-env.sh` setzt die Pfade, falls Node und PostgreSQL unter
`~/.local/opt` liegen.

```bash
cp .env.example .env
```

```bash
make db
```

```bash
cd backend && uv sync && cd ../frontend && npm install && cd ..
```

```bash
make build
```

```bash
make dev
```

`make db` legt beim ersten Mal einen eigenen PostgreSQL-Cluster in `data/postgres` (Port 5433) mit
den Rollen `kp_owner` (Migrationen) und `kp_app` (Laufzeit, ohne BYPASSRLS) an. `make dev` migriert,
startet API und Worker und liefert das gebaute Frontend aus. Für die Frontend-Entwicklung mit
Hot-Reload zusätzlich `cd frontend && npm run dev` (Port 5173, leitet `/api` an 8000 weiter).

## Demodaten

```bash
make demo
```

Erzeugt zwei Demo-Betriebe mit Personal, Fahrzeugen (mit Regalen), Hilfsmitteln, Verfügbarkeiten,
Kunden, Aufträgen, Pflanzen, Wegen und synthetischen Messungen. Nur Demodaten – keine echten
Kundendaten. Anmeldungen (Passwort jeweils `demo-passwort-2026`):

| Betrieb | Inhaber/in | Disposition |
|---|---|---|
| Gärtnerei Grünfink (`gruenfink`) | inhaberin@gruenfink.example | dispo@gruenfink.example |
| Baumschule Lindenhof (`lindenhof`) | inhaber@lindenhof.example | dispo@lindenhof.example |

Fahrer-App: http://localhost:8000/fahrer, Betriebskennung z. B. `gruenfink`, PIN `1000`, `2111`
oder `3222` (die ersten drei Personen). Kundenzugang: auf der Seite eines Kunden „Kundenzugang“
klicken und den Link öffnen. Ein Teil der Abholungen ist schon eingelagert; für sie gibt es
Rücklieferungen im April und Mai (Plan mit Richtung „Rücklieferung“ anlegen). Admin: die
Zugangsdaten aus `.env`.

## KI

Ohne Schlüssel arbeitet ein **Testmodell** mit einfachen Regeln (Nachrichtenerfassung,
Fotoprüfung, Einstellungs-KI). Für echte Modelle den Plattform-Schlüssel in `.env`
(`KP_ANTHROPIC_API_KEY`, `KP_OPENAI_API_KEY`) oder unter Admin → KI eintragen und dort Modelle
aktivieren; Modellnamen sind Daten, nicht Code. Betriebe können eigene Schlüssel hinterlegen (BYOK).

## Online-Zahlung

Pro Betrieb unter Einstellungen → Kundenzugang: „Testzahlung“ (kein Geld, zum Ausprobieren) oder
„Stripe“. Für Stripe in `.env` den Plattform-Schlüssel `KP_STRIPE_SECRET_KEY` und das
Webhook-Geheimnis `KP_STRIPE_WEBHOOK_SECRET` setzen, beim Betrieb die Kennung des verbundenen
Kontos (`acct_…`) eintragen und in Stripe den Webhook auf `/api/payments/stripe/webhook` richten
(Ereignis `checkout.session.completed`).

## Tests und Qualität

```bash
make check
```

Führt Linter (ruff, ESLint), Typprüfung und alle Tests aus (Backend: pytest gegen eine eigene
Testdatenbank, Frontend: Vitest). Der Leistungstest (500 Stopps, 10 Teams) dauert gut eine Minute;
überspringen mit `KP_SKIP_SLOW=1 make test-backend`. Nur formatieren: `make format`.

## Sicherung

```bash
make backup
```

Sichert Datenbank (`pg_dump`, Format custom) und Dateien (`data/files`) nach `./backups` und
behält 14 Tage. Für den täglichen Lauf per cron/launchd siehe Kopf von `scripts/backup.sh`.
Wiederherstellen: `scripts/restore.sh <db_….dump> <files_….tar.gz>`.

## Betrieb

- Hintergrundaufträge (Planung, Ladepläne, Modellanpassung, Monatsrechnungen, tägliche
  Löschfristen) laufen im Worker: `cd backend && uv run python -m app.jobs.worker` (in Docker
  eigener Dienst; lokal mit `KP_EMBEDDED_WORKER=true` im API-Prozess).
- Testphase/Produktivbetrieb für Agenten: Admin → Agenten. Ob die Nutzung von Agenten mit den
  Bedingungen des jeweiligen KI-Anbieters vereinbar ist, prüft der Betreiber.
- Datenschutz: Löschfristen unter Einstellungen → Datenschutz; Export und Löschung eines Kunden auf
  dessen Seite. Geheimnisse liegen verschlüsselt in der Datenbank, der Schlüssel in `.env`.
