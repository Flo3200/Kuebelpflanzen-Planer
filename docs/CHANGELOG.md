# Änderungsprotokoll der Umsetzung

## Phase 1 – Grundgerüst (abgeschlossen 2026-10-17)

**Umgesetzt**
- FastAPI-Server mit Konfiguration nur über `.env`/Umgebungsvariablen, Alembic-Migrationen,
  Docker Compose (`db`, `app`, `worker`) und Start ohne Docker (`scripts/dev.sh`).
- PostgreSQL 17 lokal (Port 5433), drei Rollen (D2), Row-Level Security mit `FORCE` für alle
  Mandantentabellen, Policy-Generator `app/core/rls.py` (strict/shared/self).
- Konten: Argon2, serverseitige Sitzungen, CSRF (Double-Submit), Ratenbegrenzung der Anmeldung
  (pro E-Mail und pro IP), Zwei-Faktor-Anmeldung (TOTP), Pflicht für Admin/Unternehmer einstellbar,
  Fahrer-Anmeldung per PIN und persönlichem Link, Admin kann „als Betrieb“ arbeiten.
- Rollen + Einzelrechte (Admin, Unternehmer, Disponent, Fahrer, Kunde; Rechte entziehbar/ergänzbar).
- Einstellungsverzeichnis mit 120 Einstellungen in 18 Gruppen (Typ, Einheit, Standard, Grenzen,
  Ebenen, Gruppe, „wichtig“, „nur Admin“), deutsche Texte in `app/i18n/de.json`.
  Auflösung Admin → Betrieb → Objekt(-kette) mit Herkunftsangabe; Zurücksetzen von Wert, Gruppe,
  Objekt/Ebene und ganzem Betrieb; Änderungsprotokoll mit Rückgängig (einzeln und als Stapel,
  mit Konfliktprüfung).
- Hintergrundjobs in PostgreSQL (`FOR UPDATE SKIP LOCKED`), Worker-Prozess oder eingebetteter
  Worker, Fortschritt, Abbruch, Wiederholungen, periodische Jobs.
- Generische Stammdaten-API (`crud_router`) und Feld-Metadaten für automatisch erzeugte Formulare.
- Frontend: Design-Tokens (hell/dunkel), Fraunces + Inter lokal, botanische Strichzeichnungen
  (eigene SVGs), Anmeldung, Konto/2FA, Admin (Übersicht, Betriebe, globale Einstellungen,
  Protokoll, Systemzustand, Admin-Konten), Unternehmer (Übersicht, Einstellungen, Benutzer,
  Protokoll, Hintergrundaufträge). Einstellungs-Editor mit einfacher und Experten-Ansicht.
- Sicherung: `scripts/backup.sh` (pg_dump + Archiv von `data/files`), `scripts/restore.sh`.
- Demodaten-Generator (`python -m app.demo --reset`), in späteren Phasen erweitert.

**Tests:** 15 Backend-Tests grün (Hierarchie, Zurücksetzen, Rückgängig, Validierung,
Mandantentrennung über API und direkt über RLS, Anmeldung, CSRF, 2FA, Disponentenrechte, Fahrer-PIN,
Jobs). Frontend: TypeScript und ESLint ohne Fehler.

**Abnahme:** erfüllt – `test_two_tenants_see_only_own_data`, `test_row_level_security_without_application_filter`,
`test_three_levels_and_reset` prüfen genau das Abnahmekriterium; zusätzlich im Browser geprüft.

**Offen/Hinweise:** Docker Compose ist geschrieben, auf diesem Rechner aber nicht getestet
(kein Docker installiert).
