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

## Phase 5 – 3D-Ladeplanung (abgeschlossen 2026-10-18)

**Umgesetzt**
- Geometrie: Laderäume mit Radkästen, Regalen (Tragkraft, lichte Höhe, „sperrt den Boden“),
  Tür, Achsen und Anhängerkupplung; Pflanzen mit starrem Kübel (rund/eckig) und weicher Krone
  (Kugel, Kegel, Säule, Zylinder, frei), Kippen und Liegen nach Einstellung.
- Packer: Extreme-Point-Heuristik mit Kronen-Berührpunkten und Raster-Rückfall, Ladegassen für
  liegende Pflanzen, Ladereihenfolge nach Tour (Abholung: zuerst geladen = ganz hinten,
  Rücklieferung umgekehrt), Simulated Annealing für Schwerpunkt, Achs- und Stützlast,
  empfindliche Pflanzen und Reihenfolge; Ladeanweisungen auf Deutsch (Sprachdatei).
- Kopplung mit der Tourenplanung (D15): Neuplanung mit kleinerer Kapazität bzw. ohne die nicht
  passende Kombination aus Stopp und Fahrzeug; Zwischenspeicher für gleiche Fahrten.
- Begründungen: jede nicht ladbare Pflanze mit Namen und Grund (kein Platz, Nutzlast, Tür zu
  schmal, zu hoch und nicht kippbar), Achs-/Stützlastverletzungen benannt.
- API: Ladeplan einer Tour lesen (mit Stopps und Kunden) und neu berechnen (protokolliert),
  alle Ladepläne eines Plans als Hintergrundjob.
- Oberfläche: Ladeplan-Seite mit Draufsicht (SVG), 3D-Ansicht (three.js, nachgeladen, drehbar,
  Pflanze anklicken) und „Schritt für Schritt“ mit hervorgehobener Pflanze; Kennzahlen
  (Gewicht, Achslasten, Stützlast, Schwerpunkt, genutzte Länge); Link aus Tourenliste und
  Zeitachse. Die Ansicht ist für die Fahrer-App wiederverwendbar (kompakter Modus).

**Tests:** 17 neue Tests (unabhängige Geometrieprüfung: keine Kübelüberlappung, im Laderaum,
unter dem Dach, Nutzlast, kein Kübel auf Radkasten, Regale; Ladereihenfolge ohne Blockade;
freie Gasse für liegende Pflanzen; deutsche Gründe; Anhänger-Stützlast; Determinismus;
Plan-Abnahme mit Ladeplänen über die API; Mandantentrennung).

**Abnahme:** erfüllt – jede Tour hat einen gültigen Ladeplan oder eine Begründung. Demo-Betrieb
„Grünfink“ (10 Tage): 17 von 18 Touren passen, die übrige nennt die Pflanze, die nicht passt.

**Hinweise:** Eine Planung mit Ladeprüfung dauert im Demo-Betrieb etwa zwei Minuten
(Hintergrundjob mit Fortschritt). Die Ladeplanung prüft keine Seitentür; wer über eine Schiebetür
lädt, kann den Plan in der Oberfläche neu berechnen oder Stopps verschieben.

## Phase 6 – Fahrer-App und Lernen (abgeschlossen 2026-10-18)

**Umgesetzt**
- Fahrer-App (PWA unter `/fahrer`): Anmeldung mit Betriebskennung und PIN oder persönlichem
  Link, nur eigene Touren, Tagesansicht (heute und morgen), Tour mit Team, Fahrzeug und Pausen,
  Stopp mit Kundenhinweisen, Navigation (Google Maps, Apple Karten), Anruf, Pflanzen mit Maßen
  und Fotos, Weg mit Abschnitten und Fotos, benötigte Teamgröße und Hilfsmittel.
- Zeiterfassung über große Schaltflächen (Ankunft, Tragen beginnt, optional Pflanze fertig,
  Eingeladen mit Pflichtfoto, Weiterfahren), Pausen, Schichtbeginn/-ende, Abladen.
- Offline: Tagesplan und Ladeplan lokal, Ereignisse/Fotos/Meldungen in einer IndexedDB-
  Warteschlange, Senden bei Verbindung, Anzeige „offen/Fehler“, Service Worker für App und Fotos.
- Ladeansicht in der App (Schritt für Schritt, 3D, Draufsicht); optionales QR-Modul mit
  Etiketten-PDF und Scan, der den Platz bestätigt.
- Abweichungen melden (schwerer, größer, Weg anders, Kunde nicht da, Schaden mit Foto);
  im Büro übernehmen (Pflanzen-/Wegdaten, Schätzung neu, Hinweis „neu planen“) oder verwerfen.
- Messungen je Stopp aus den Ereignissen; Ausreißer markieren und ausschließen.
- Modellanpassung als Hintergrundjob (auch wöchentlich/monatlich): nichtlineare kleinste
  Quadrate mit Huber, Regularisierung, Faktoren je Person, k-fache Kreuzvalidierung je
  Formelstufe, Auswahl der Parameter nach Datenmenge, Standardfehler, Planungspuffer aus der
  Streuung, Vorschlag einer besseren Stufe; Übernahme als neue Formelversion.
- Qualitätsansicht: vorhergesagt gegen gemessen, Fehlerverteilung, Fehler nach Merkmal,
  Kreuzvalidierung, Parameter, Faktoren je Person, Puffer, auffällige Messungen.
- Experimentmodus geprüft (größeres Team nur oberhalb der benötigten Größe, markiert).
- Demodaten: synthetische Messungen aus bekannten wahren Werten.
- Hintergrundjobs speichern erklärte Fehler (z. B. „Zu wenige Messungen“) als deutschen Text.

**Tests:** 15 neue Tests (85 gesamt). **Abnahme:** erfüllt – aus 220 synthetischen Messungen mit
12 % Streuung und 3 % Ausreißern werden die wahren Parameter auf ±15 % wiedergefunden
(z. B. a0 8,0 → 8,2; a1 0,11 → 0,105; t_fixed 14 → 13,7; k_height 0,8 → 0,83).

**Hinweise:** Faktoren je Person lassen sich nur mit genauen Messungen gut bestimmen, weil eine
Person die Teamgeschwindigkeit nur anteilig ändert; bis genug Daten vorliegen, bleiben sie nah
an 1,0 (so gewollt). Die Registrierung des Service Workers ließ sich im eingebauten Browser der
Entwicklungsumgebung nicht prüfen (er lässt keine Service Worker zu); die Warteschlange für den
Offline-Betrieb funktioniert unabhängig davon.

## Phase 7 – Abrechnung, Agenten, Einstellungs-KI (abgeschlossen 2026-10-18)

**Umgesetzt**
- Agenten: Einwahl-Link mit Einmal-Code, Token mit Rechten (lesen, Entwürfe, Stammdaten, planen,
  Einstellungen; Admin: Admin-Unterstützung, alles), Ablauf, Widerruf, Ratenbegrenzung,
  Protokoll aller Aufrufe, Bestätigungspflicht für löschende und abrechnungsrelevante Aktionen
  (Freigabe in der Oberfläche, dann Wiederholung mit `X-KP-Confirmation`).
- Schalter Testphase/Produktivbetrieb (Admin), serverseitig durchgesetzt.
- `/agent/README.md`: Anleitung in einfacher Sprache mit curl-Beispielen und der aktuellen
  Endpunktliste aus der API.
- Abrechnung: Bausteine je Betrieb (Abo monatlich/jährlich, pro abgeholter Pflanze, KI-Verbrauch
  mit Aufschlag, BYOK ausgenommen), Monatsrechnung als Hintergrundjob, PDF mit Pflichtangaben
  (§ 14 UStG), Mehrwertsteuer oder Kleinunternehmerregelung, fortlaufende Nummern, Storno,
  „bezahlt“, Verbrauchsübersicht für Betrieb und Admin; Rechnungen der Betriebe an ihre Kunden.
- Einstellungs-KI: Chat mit Werkzeugen (lesen, ändern, zurücksetzen, erklären, Anleitung
  durchsuchen), Rechte des Benutzers, Protokoll mit Quelle „Einstellungs-KI“, Rückgängig-Knopf.
- `docs/APP_GUIDE.md` (Funktionsbeschreibung für Menschen und die Einstellungs-KI).
- Oberflächen: Agenten (Betrieb und Admin), Abrechnung (Betrieb und Admin), Einstellungs-KI,
  Kundenrechnung im Auftrag.

**Tests:** 11 neue Tests (96 gesamt). **Abnahme:** erfüllt – ein Agent wählt sich per Link ein und
legt mit einem Bearer-Token einen Entwurf an (`test_agent_enrols_via_link_and_creates_draft`);
im Produktivbetrieb wird derselbe Aufruf mit einem Admin-Agent-Token für einen Betrieb mit 403
abgelehnt (`test_production_mode_refuses_admin_agent_for_tenant`).

**Hinweise:** Neuere Chromium-Versionen geben bei `scrollIntoView` ein Promise zurück; Effekte in
React haben deshalb immer einen Block-Körper (sonst Absturz beim Aufräumen). Ob eine Nutzung von
Agenten mit den Bedingungen des jeweiligen KI-Anbieters vereinbar ist, prüft der Betreiber.

## Datenschutz und Dokumentation (abgeschlossen 2026-10-18)

- Export aller Daten eines Kunden als ZIP (Daten, Fotos, Angebote, Rechnungen) und Löschung auf
  Anfrage: Name, Kontakt, Straße, Koordinaten, Notizen, Nachrichten, Fotos und Angebote werden
  entfernt; Pflanzen, Messungen und Touren bleiben (nicht personenbezogen), Rechnungen bleiben bis
  zum Ende der Aufbewahrungsfrist; personenbezogene Werte im Änderungsprotokoll werden geleert.
- Tägliche Löschfristen je Betrieb (Fotos, Kunden ohne Aktivität, Kundenrechnungen nach Ablauf
  der Aufbewahrung), manuell auslösbar.
- `README.md` (Installation, Start, Demodaten, Tests, Sicherung), `docs/APP_GUIDE.md`,
  `agent/README.md` (`make agent-readme`), Frontend-Unit-Tests (Vitest) für `make check`.

**Tests:** 2 neue Backend-Tests (98 gesamt) und 9 Frontend-Tests.

## Phase 8 – Rücklieferung und Kundenzugang (abgeschlossen 2026-10-18)

**Rücklieferung im Frühjahr als eigener Planungsmodus**
- Pläne für Rücklieferungen mit Beladen im Betrieb vor jeder Fahrt, Frostregel mit Stichtag
  (Eisheilige), eigenem Zeitfaktor und eigener Preisregel (eigener Preis, im Abholpreis enthalten
  oder Faktor).
- Rücklieferungen gesammelt anlegen (Zeitraum, Wunsch des Kunden hat Vorrang); Zeitfenster der
  Abholung werden übernommen.
- Ladeplan rückwärts (zuletzt ausgeliefert = zuerst eingeladen), Fahrer-App mit Schritt
  „Abgestellt“ und Abgabefoto, Lagerplatz je Pflanze beim Beladen; danach ist auch die Abholung
  „zurückgebracht“.
- Demodaten: ein Teil der Abholungen ist eingelagert (mit Lagerbereich), Rücklieferungen für April
  und Mai liegen vor.
- Modellanpassung: robuster Start (eingebaute Huber-Verlustfunktion vor der Neugewichtung), damit
  einzelne Ausreißer keine Person in ein falsches Optimum ziehen; Personenfaktoren 0,5–2,0.

**Kundenzugang**
- Persönlicher Link (Kundenseite „Kundenzugang“), Übersicht der eigenen Aufträge mit Fortschritt
  und Termin (Zeitfenster), Angebot ansehen und annehmen (bestätigt den Auftrag), geführte
  Foto-Aufnahme je Pflanze und für den Weg mit Einwilligung und Rückmeldung der Prüfung,
  Standort auf der Karte mit Hinweisen zu Parken, Klingel und Zugang, Wunsch für die
  Rücklieferung, Rechnungen.
- Online-Zahlung: Testzahlung und Stripe Checkout (Stripe Connect) mit geprüftem Webhook;
  Zahlungen erscheinen beim Betrieb, Rechnungen werden als bezahlt markiert.
- Serverseitige Sperre: Kunden erreichen nur den Kundenzugang und eigene Dateien.

**Tests:** 13 neue Backend-Tests (112 gesamt, dazu 9 Frontend-Tests). Offen aus Phase 8: Umzug auf einen gehosteten Server.

## Verbesserungsrunde – Paket A: Fokus Logistik und schlanke Eingaben (2026-10-18)

**Umgesetzt**
- Modul-Schalter unter „Einstellungen → Module“: Lager, Preise/Angebote/Rechnungen an Kunden,
  Kundenzugang, Online-Zahlung (braucht den Kundenzugang). Für neue Betriebe aus.
- Ausgeschaltete Module verschwinden aus Menü (Lager, Preise), Übersicht (Lagerauslastung,
  Angebotssumme), Formularen (Lagerplatz, Endpreis, Steuer-/Bankdaten des Betriebs), Auftrags- und
  Kundenseiten (Kundenzugang-Link, Angebote, Kundenrechnungen, Preis-Spalten) und Einstellungen;
  Endpunkte antworten 409. Ohne Preis-Modul zeigen Aufträge die Logistikkosten statt des Preises.
- `portal.enabled` wird zu `modules.portal` (umkehrbare Migration).
- Erfassungsmasken: Felder ohne Berechnungsbezug stehen eingeklappt unter „Weitere Angaben“
  (Feldtabelle in `DECISIONS.md`, D24). Kundenliste zeigt Name und Telefon.
- Fahrer-App zeigt den Lagerplatz nur mit Lager-Modul; Frostregel und Rücklieferung hängen nicht
  vom Lager ab.

**Tests:** 8 neue Tests (`test_modules.py`: jedes Modul aus und an, Abhängigkeit Zahlung → Zugang,
eingeklappte Felder); bestehende Tests schalten die Module ein, die sie brauchen. `make check` grün
(120 Backend-Tests, 9 Frontend-Tests). **Abnahme:** erfüllt – ein neuer Betrieb sieht nur
Logistik-Funktionen (`test_new_tenant_has_only_logistics`), Masken zeigen nur Felder mit
Berechnungsbezug, jedes Modul ist an und aus getestet.

## Verbesserungsrunde – Paket B: Pflanzenarten im Hintergrund (2026-10-18)

**Umgesetzt**
- Die Seite „Pflanzenarten“ ist für Betriebe entfernt; der Admin pflegt sie als „Wissensbasis
  Pflanzenarten“. Die API und Einstellungen der Ebene Pflanzenart sind nur noch für den Admin.
- Pflanzen haben eine Art als Text, Kippgefahr und Gewichtsbeiwerte; die KI bestimmt Art und
  Eigenschaften (Frost, kippbar, empfindlich, Stauchbarkeit, Kippgefahr) mit Sicherheitswert,
  fehlende Werte kommen aus der Wissensbasis. Prompts für Nachrichtenerfassung und Foto-Auswertung
  in Version 2; das Testmodell nutzt die Wissensbasis und erkennt „frostempfindlich“ im Text.
- Gewichtsschätzung, Kalibrierung, Ladeplanung, Frostregel, Etiketten, Fahrer-App und Kundenzugang
  lesen die Art und die Eigenschaften der Pflanze.
- Posteingang zeigt je Pflanze zusätzlich „Frostempfindlich“ und „Darf gekippt werden“.
- Migration kopiert die Werte der bisherigen Art an jede Pflanze (umkehrbar).
- Formulare: fehlende Gruppenüberschriften (Topf, Krone, Gewicht, Umgang …) ergänzt.

**Tests:** 4 neue Tests (`test_species_background.py`: Wissensbasis nur Admin, Eigenschaften aus der
Wissensbasis, Gewicht und Frostregel aus der Pflanze, KI-Erfassung mit Art und Sicherheit);
`make check` grün (124 Backend-, 9 Frontend-Tests). **Abnahme:** erfüllt – Pflanzen erhalten ohne
Artverwaltung alle nötigen Eigenschaften, alle betroffenen Tests grün.

## Verbesserungsrunde – Paket D: Teams durch den Unternehmer (2026-10-18)

**Umgesetzt**
- Teams mit Mitgliedern, Standard-Fahrzeug, Einsatztagen und Zeitraum; Teamliste zeigt Fahrzeug,
  Tage und Zeitraum.
- Verfügbarkeitskalender mit Zeile je Team: kann fahren, Konflikt (mit Grund im Tooltip) oder kein
  Einsatztag.
- Planung mit festen Teams: Teams, die an einem Tag nicht fahren können, erscheinen als Warnung mit
  Grund und Tagen; nicht einplanbare Stopps zeigen Grund, benötigte Personen und einen Lösungshinweis
  (Team ergänzen, anderes Team, passendes Fahrzeug). Es entsteht immer ein Plan.
- Das Standard-Fahrzeug ist eine Vorgabe: Ist es nicht frei, fährt das Team mit einem anderen.

**Tests:** 4 neue Tests (`test_teams.py`: feste Teams ohne Teams, zu kleines Team mit Hinweis,
Abwesenheit und Wochentage als Warnung, Konflikte im Kalender); `make check` grün (128 Backend-,
9 Frontend-Tests). **Abnahme:** erfüllt – mit festen Teams entsteht immer ein Plan, nicht
einplanbare Stopps haben einen verständlichen Grund und einen Lösungshinweis.

## Verbesserungsrunde – Paket E: Kosten (2026-10-18)

**Umgesetzt**
- Neue Seite „Kosten“ für eigene Kostenpositionen (Betrieb, Fahrzeug oder Person; pro km, Stunde,
  Einsatz, Einsatztag, Monat anteilig, Pflanze) und Reiter „Eigene Kosten“ bei Fahrzeugen und Personal.
- Positionen fließen in Auftragsschätzung, Tourkosten, Stoppkosten, Kosten nach der Planung und
  Szenarien ein; Tour und Auftrag zeigen die Aufschlüsselung.
- Kostenanzeige „Logistikkosten“ getrennt von Preis und Marge; Gemeinkostenzuschlag und Marge
  standardmäßig 0 %.

**Tests:** 3 neue Tests (`test_costs.py`: Standard 0 %, Position ändert die Auftragskosten, Positionen
für Fahrzeug, Person und Betrieb in den Tourkosten mit Aufteilung auf Stopps); `make check` grün
(131 Backend-, 9 Frontend-Tests). **Abnahme:** erfüllt – eine eigene Kostenposition ändert sichtbar
Tour- und Auftragskosten, die Aufschlüsselung je Tour ist nachvollziehbar.

## Verbesserungsrunde – Paket C: Fahrzeuge per Foto und Chat, modular (2026-10-18)

**Umgesetzt**
- „Fahrzeuge → Per Chat anlegen“ und „Per Foto anlegen“: KI-Entwurf mit Sicherheitswert je Wert,
  Rückfragen, Antworten im Chat, Korrektur von Hand, Bestätigen oder Verwerfen; offene Entwürfe
  bleiben auf der Fahrzeugseite sichtbar. Reiter „Per Chat ändern“ für bestehende Fahrzeuge.
- Neue Seite „Module“: Regale und Einbauten, mehreren Fahrzeugen zuordenbar (Reiter „Module“ am
  Fahrzeug), mit Eigengewicht; Kombinationen Zugfahrzeug + Anhänger.
- Lade- und Tourenplanung rechnen mit den Modulen; Kostenpositionen können zu einem Modul gehören.
- KI-Aufgaben `vehicle_photo`/`vehicle_chat` mit versionierten Prompts, Testmodell ohne Schlüssel,
  Testsätze im Bewertungswerkzeug (Funktion wählbar, Beispielsatz für den Chat).

**Tests:** 7 neue Tests (`test_fleet.py`: Chat-Entwurf und Bestätigung, Rückfragen und Antwort,
Änderung per Chat mit Protokoll, Laderaum-Foto mit A4-Maßstab und Korrektur, Module an mehreren
Fahrzeugen in Lade- und Tourenplanung, Anhänger-Kombination, Modulkosten, Testsatz im
Bewertungswerkzeug); `make check` grün (138 Backend-, 9 Frontend-Tests). **Abnahme:** erfüllt – ein
Fahrzeug lässt sich per Chat und per Foto als Entwurf anlegen und bestätigen, Module lassen sich
mehreren Fahrzeugen zuordnen, die Ladeplanung nutzt das Ergebnis. Mit echten KI-Modellen ist es noch
nicht erprobt (kein API-Schlüssel hinterlegt).
