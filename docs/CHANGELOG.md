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

## Phase 2 – Stammdaten und Erfassung (abgeschlossen 2026-10-17)

**Umgesetzt**
- Personal (Führerscheinklassen, Qualifikationen; Lohn, Alleintragegewicht, Tragefaktor,
  Geschwindigkeiten als Objekt-Einstellungen), Teams, Fahrzeuge (Laderaum, Türen, Radkästen,
  Achsen, Anhänger-Stützlast, Regale mit eigenem Editor), Hilfsmittel (Tragfähigkeit,
  Zeitfaktor, Alleintragegrenze, Treppe/Untergrund), Lagerbereiche mit Auslastung und Warnung.
- Verfügbarkeit: Muster (Wochentage), Abwesenheiten ganz- und teiltägig, Kalenderansicht.
- Kunden, Adressen (Geokodierung über Schnittstelle, offline oder Nominatim), Aufträge mit
  Nummernkreis, Saison, Richtung (Rücklieferung übernimmt Pflanzen und Wege), Status, Storno.
- Pflanzen mit Kübel-, Kronen- und Umgangsdaten; fehlende Werte aus Pflanzenart und
  Einstellungen ergänzt und als „geschätzt“ markiert; Gewichtsschätzung aus Topfvolumen,
  Material und Pflanzenart mit Unsicherheit und Kalibrierfaktor (gewogene Pflanzen).
- Wege als Abschnittsliste mit Zusammenfassung (Länge, Stufen, Höhe, schmalste Stelle).
- Fotos: EXIF/GPS entfernt, lokale Prüfung (Schärfe, Belichtung, A4-Erkennung mit Maßstab),
  Einwilligung erforderlich und gespeichert, Dateien hinter `StorageBackend`.
- Pflanzenarten-Katalog (27 Arten global, Überschreibung je Betrieb, Objekt-Einstellungen).
- KI-Schicht: Anthropic (offizielles SDK, strukturierte Ausgaben, serverseitiges Ausweichen bei
  Ablehnungen), OpenAI, Test-Anbieter ohne KI (regelbasiert, deutsch). Modell pro Funktion,
  Ersatzmodell, Plattform- oder eigener Schlüssel (verschlüsselt), Ausgabenlimit mit Warnung
  und Sperre, Verbrauch je Aufruf, Prompts versioniert (global und je Betrieb), Validierung
  mit Wiederholung.
- Nachrichtenerfassung → Entwurfs-Posteingang mit Sicherheitswerten, hervorgehobenen Feldern,
  Rückfrage-Vorschlag → Bestätigung legt Kunde (oder findet ihn wieder), Adresse, Auftrag,
  Pflanzen, Weg an und ordnet Fotos zu. Vollständigkeitsprüfung und Foto-Auswertung für Aufträge.
- Bewertungswerkzeug: Testsätze mit gemessenen Maßen, Modellvergleich (mittlerer Fehler,
  Kosten je Auswertung).
- Oberflächen: Posteingang, Entwurfsprüfung, Kunden, Aufträge, Auftragsdetail (Pflanzen,
  Weg-Editor, Fotos), Personal, Teams, Fahrzeuge, Hilfsmittel, Kalender, Pflanzenarten, Lager,
  KI-Administration, KI-Nutzung des Betriebs.
- Demodaten: 2 Betriebe mit je 10 Personen, 4 Fahrzeugen, Hilfsmitteln, Lager, 100 Aufträgen
  (~330 Pflanzen, realistische Wege und Größen, 12 % gewogen) und 3 Nachrichten im Posteingang.

**Tests:** 25 Backend-Tests grün, u. a. Abnahmetest (Nachricht + Fotos → Entwurf mit
Sicherheitswerten → Kunde, Auftrag, Pflanzen), EXIF-Entfernung, Ausgabenlimit, Einwilligung,
Mandantentrennung neuer Tabellen inkl. Fremdschlüssel-Prüfung.

**Abnahme:** erfüllt (`test_message_with_photos_becomes_draft_and_records`).

**Hinweise:** Echte KI-Modelle sind eingerichtet, aber ohne API-Schlüssel nicht getestet;
Standardmodell ist das Testmodell. Geokodierung ist standardmäßig offline (Koordinaten manuell
oder aus Demodaten); `KP_GEOCODER=nominatim` schaltet OpenStreetMap ein.

## Phase 3 – Zeit- und Kostenmodell (abgeschlossen 2026-10-17)

**Umgesetzt**
- Sicherer Ausdrucks-Parser (eigener Tokenizer + Parser, kein eval): Grundrechenarten, Potenz,
  Vergleiche, and/or/not, if(), min/max/log/exp/…, Summen/Maxima über die Pflanzen eines Stopps,
  Fehler mit Position, Grenzen für Länge/Komplexität.
- Formeln mit Versionen und Stufen (Startformel Stufe 1, erweiterte Stufe 2, Kundenpreis),
  global und je Betrieb überschreibbar (mit Zurücksetzen), Parameter fest/lernbar mit Grenzen,
  Prüfung unbekannter Namen, Testlauf an einem echten Auftrag, Variablenverzeichnis mit Erklärungen.
- Teamgrößenregeln (Gewicht mit Tragefaktor, Greifbarkeit, Treppe, Steigung, Engstelle,
  Hilfsmittel, Höchstgröße, manuelle Überschreibung).
- Schätzung je Auftrag: Dauer und Arbeitszeit getrennt, Dauer je Teamgröße, Planungspuffer
  (Quantil), Kosten (Arbeit, Fahrtanteil, Fahrzeug, Hilfsmittel, Gemeinkosten, Marge), Preis nach
  Formel mit Entfernungszuschlag (aus/Entfernung/Zonen/Umweg), Rundung, MwSt., Kostendeckung.
- RoutingProvider (offline, OSRM, OpenRouteService, Google) mit Zwischenspeicher.
- Angebots-PDF (reportlab) mit Nummernkreis; Gewichtskalibrierung aus gewogenen Pflanzen.
- Formel- oder Einstellungsänderungen wirken sofort (Detailansicht rechnet live, Listen per Job).
- Oberflächen: Formeleditor (Admin und Betrieb), Preise & Angebote, Schätzungsdetails im Auftrag.

**Tests:** 47 Backend-Tests grün. **Abnahme:** erfüllt (`test_changed_formula_takes_effect_immediately`,
`test_start_formula_numbers`, `test_price_rules`).

## Phase 4 – Tourenplanung und Szenarien (abgeschlossen 2026-10-17)

**Umgesetzt**
- Einsatz-Einheiten je Tag aus Fahrzeug (+ Anhänger) und Team: feste Teams, automatische
  Teambildung (großes Team für schwere Stopps, Sitzplätze, Fahrer mit passender Führerscheinklasse
  inkl. BE/C1E bei Anhängern), Verfügbarkeitsfenster von Personal und Fahrzeugen.
- OR-Tools-Modell: Zeitdimension mit teamabhängiger Servicezeit (Zeitmodell, Planungspuffer,
  Parken), Fahrzeug-/Fahrer-/Anhängerfaktoren, Kapazitäten Gewicht/Grundfläche/Volumen,
  Mehrfachfahrten über Abladeknoten, Pausen nach Arbeitszeitgesetz als Pausen-Intervalle,
  Höchstarbeitszeit, Überstunden mit Strafkosten, Kundenzeitfenster hart oder weich,
  zulässige Teams pro Stopp (Teamgröße, Tragfähigkeit, Hilfsmittel, Geometrie, Datum),
  Auslassen mit Strafe (bzw. Erlös beim Gewinnziel), Unverträglichkeiten mit Neulösen,
  Fixieren von Touren und Stopps, Vorrang früher Tage, Regionen-Gruppen bei großen Betrieben,
  einstellbare Suchverfahren und Zeitlimit; Matrizen über RegisterTransitMatrix (C++).
- Kopplung mit der Ladeplanung vorbereitet (Kapazität einer Einheit wird verringert und neu
  geplant, wenn eine Tour nicht passt).
- Ergebnis: Touren, Stopps, Pausen, Kosten je Tour und je Stopp, Kennzahlen (Tage bis fertig,
  Kosten, Kosten pro Pflanze, Auslastung, Überstunden), nicht eingeplante Stopps mit Grund,
  Kostendeckung je Auftrag nach Planung, aktiver Plan setzt Auftragsstatus.
- Manuelles Verschieben mit sofortiger Neuberechnung und Warnungen, Stornierung entfernt den
  Stopp und markiert die Tour, Hinweis „Neu planen“ bei neuen/geänderten Aufträgen und Ausfällen,
  Neuplanung ab Datum unter Erhalt fixierter und vergangener Teile.
- Szenarien (±Person, ±Fahrzeug, ±Tag, Teamgröße, frei kombinierbar) als Hintergrundjobs,
  Vergleich mit Differenzen und Grenzkosten.
- Oberflächen: Tourenplanung (Zeitachse mit Ziehen-und-Ablegen, Karte mit OpenStreetMap,
  Tourenliste mit Fixieren, nicht eingeplante Stopps), Szenarien mit Tabelle und Diagramm.

**Tests:** 54 Backend-Tests, u. a. unabhängige Prüfung aller Nebenbedingungen für 100 Demo-
Aufträge, Szenario „+1 Person“, Verschieben, Fixieren/Stornieren/Neuplanen, Unverträglichkeit,
harte Zeitfenster, Leistungstest 500 Stopps/10 Teams (60 s Zeitlimit, gesamt 76 s inkl. Datenaufbau).

**Abnahme:** erfüllt.

**Hinweise:** Die Python-Bindung von `SetAllowedVehiclesForIndex` ist in OR-Tools 9.15 defekt;
zulässige Fahrzeuge werden über den Wertebereich der Fahrzeugvariable gesetzt (D14).
