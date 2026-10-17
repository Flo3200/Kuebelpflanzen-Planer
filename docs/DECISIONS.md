# Technische Entscheidungen

Kleine technische Entscheidungen, die die Spezifikation offen lässt. Neueste unten.

## D1 – Lokale Laufzeitumgebung ohne Homebrew-Builds
Der Entwicklungsrechner ist ein Intel-Mac mit macOS 15; Homebrew bietet dort keine fertigen Pakete
mehr und würde LLVM/Rust aus dem Quellcode bauen. Daher:
- Node.js 24 LTS als offizielles Binärpaket von nodejs.org unter `~/.local/opt/node`
- PostgreSQL 17 als EDB-Binärpaket unter `~/.local/opt/pgsql-17`, Cluster unter `data/postgres`,
  Port **5433** (kollidiert nicht mit einer späteren Standardinstallation)
- Python 3.12 über `uv`
`scripts/dev-env.sh` setzt die Pfade. Docker Compose bleibt der vorgesehene Weg für andere Rechner
und den späteren Server (`postgres:17`).

## D2 – Drei Datenbankrollen
- `kp_super`: nur für die Ersteinrichtung (Rollen, Datenbanken).
- `kp_owner`: besitzt Schema und Tabellen, führt Alembic-Migrationen und Sicherungen aus
  (BYPASSRLS, damit `pg_dump` und Datenmigrationen alle Zeilen sehen; wird zur Laufzeit nie benutzt).
- `kp_app`: Laufzeitrolle des Servers, **kein** Superuser, **kein** BYPASSRLS, nur DML-Rechte.
Damit greift Row-Level Security für alle Abfragen des Servers. Zusätzlich `FORCE ROW LEVEL SECURITY`.

## D3 – Row-Level Security
- Der Mandant wird pro Transaktion über `set_config('app.tenant_id', …, true)` gesetzt
  (SQLAlchemy-Ereignis `after_begin`), daher auch nach Zwischen-Commits korrekt.
- Zwei Policy-Arten:
  - **strict**: Zeile sichtbar/änderbar nur bei `tenant_id = app.tenant_id`.
  - **shared** (Pflanzenarten, Formeln, Prompts, Einstellungswerte): globale Zeilen
    (`tenant_id IS NULL`) sind für Betriebe nur lesbar; schreiben nur auf eigene Zeilen.
- Admin-Kontext und Systemprozesse (Worker, Anmeldung) setzen `app.bypass_rls = on`.
- RLS schützt vor vergessenen Filtern im Anwendungscode; zusätzlich filtert der Code selbst nach
  `tenant_id`. Tests prüfen beides.

## D4 – IDs
UUIDs als Primärschlüssel (mandantenübergreifend eindeutig, für API und Agenten unkritisch).

## D5 – Sitzungen, CSRF
Serverseitige Sitzungen in der Datenbank (Token nur gehasht gespeichert), HttpOnly-Cookie.
CSRF per Double-Submit (`kp_csrf`-Cookie + Header `X-CSRF-Token`). Bearer-Tokens (Agenten,
Fahrer-Geräte) brauchen kein CSRF-Token. Ratenbegrenzung der Anmeldung über eine Tabelle
(funktioniert auch mit mehreren Server-Prozessen).

## D6 – Übersetzungen
Backend und Frontend nutzen dieselbe Struktur `i18n/de.json`. Beschriftungen und Erklärungen der
Einstellungen und Datenfelder liegen dort, nicht im Code; das Einstellungsverzeichnis enthält nur
Schlüssel, Typ, Einheit, Standard, Grenzen, Ebenen und Gruppe. Eigene schlanke `t()`-Funktion statt
i18next.

## D7 – Generische Stammdaten-API
Für einfache Stammdaten (Personal, Fahrzeuge, Hilfsmittel, Kunden …) erzeugt eine Fabrik
(`crud_router`) Endpunkte und Pydantic-Schemas aus den SQLAlchemy-Spalten. Spalten tragen
Metadaten (`info={"unit": "cm", "group": …}`); daraus erzeugt das Frontend Formulare und Tabellen.
Spezielle Oberflächen (Regale, Wegabschnitte, Fotos) bauen darauf auf.

## D8 – PDF mit reportlab
WeasyPrint braucht Pango/Cairo als Systembibliotheken (auf diesem Rechner nur per Quellcode-Build).
reportlab ist reines Python mit fertigen Paketen und läuft überall. Die PDF-Erzeugung liegt hinter
einer kleinen Schnittstelle, damit WeasyPrint/Typst später ergänzt werden können.

## D9 – Schriften lokal
Fraunces und Inter werden über `@fontsource` mit ausgeliefert – keine Anfragen an Google Fonts
(Datenschutz, Offline-Fähigkeit der Fahrer-App).

## D10 – Kennzahlen von Objekten sind Einstellungen
Lohn, Arbeitgeberanteil, Alleintragegewicht, Tragefaktor, Geschwindigkeitsfaktoren, Fahrzeugkosten,
Verbrauch, Hilfsmittelkosten usw. sind keine Tabellenspalten, sondern Einstellungen mit
Objekt-Ebene. So gilt für alle dieselbe Hierarchie Admin → Betrieb → Objekt mit Herkunftsanzeige,
Zurücksetzen und Protokoll. Stammdatenformulare zeigen sie im Reiter „Einstellungen“.

## D11 – KI ohne Schlüssel nutzbar
Ein Test-Anbieter („Testmodell“) ist Standard. Er wertet deutsche Nachrichten regelbasiert aus
und liefert ehrliche Sicherheitswerte. So funktionieren Erfassung, Tests und Demo ohne Kosten.
Echte Modelle (Anthropic, OpenAI) werden in der Oberfläche aktiviert; Modellnamen sind Daten.
Für Anthropic: offizielles SDK, JSON-Schema über `output_config.format`, kein erzwungener
Tool-Aufruf (auf neuen Modellen nicht erlaubt), optional serverseitiges Ausweichen bei Ablehnung.

## D12 – Werte mit Sicherheit
KI-Ergebnisse speichern jeden Wert als `{value, confidence}`. Unter `photos.min_confidence`
wird ein Feld zur Prüfung markiert. Vom Menschen geänderte Werte erhalten Sicherheit 1.

## D13 – Rücklieferung
Eine Rücklieferung ist ein eigener Auftrag (`direction = return`, `return_of_id`), der Pflanzen
und Wege der Abholung verwendet. Die Tourenplanung behandelt sie später als eigenen Modus.
