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

## D14 – Planungsmodell
- Solver-„Fahrzeug“ = Einheit aus Tag × Fahrzeug (+ Anhänger) × Team. Personal ist pro Tag nur
  in einer Einheit; die Teams werden vor dem Lösen gebildet (feste Teams, sonst automatisch).
- Mehrfachfahrten: optionale Abladeknoten am Betrieb pro Einheit (Kapazität setzt sich über Slack
  zurück). Pausen: OR-Tools-Pausenintervall zwischen 3 und 6 Stunden nach Arbeitsbeginn.
- Zulässige Einheiten über `VehicleVar(i).SetValues([-1, …])`, weil `SetAllowedVehiclesForIndex`
  aus Python nicht nutzbar ist.
- Kosten: Strecke über Kantenkosten, Arbeits- und Fahrzeugzeit über Span-Kosten der Zeitdimension,
  Fixkosten je Einheit plus Vorrang früher Tage.
- Pflanzen über der Höchst-Teamgröße werden standardmäßig mit dem größten Team eingeplant und
  markiert (Einstellung `team.plan_over_limit`).
- Große Betriebe: Stopps nach Winkel um den Betrieb in Regionen geteilt, Einheiten anteilig nach
  Arbeitsmenge verteilt, jede Region mit anteiligem Zeitlimit gelöst.

## D15 – Ladeplanungsmodell
- Kübel sind starr (Kreis oder Rechteck, nie überlappend), Kronen weich: sie dürfen sich um einen
  Anteil überlappen, der aus `packing.crown_overlap`, Dichte und Komprimierbarkeit folgt, und über
  fremde Kübel nur oberhalb des Kübelrands ragen. Nichts wird auf Pflanzen gestapelt.
- Zu hohe, kippbare Pflanzen liegen längs (Topf zur Stirnwand) oder quer. Liegende Pflanzen dürfen
  mit der Krone über niedrige Hindernisse (Radkasten) ragen, der Topf nie.
- Ladegasse: Für jede liegende Pflanze, die später eingeladen wird, bleibt ein Streifen entlang der
  linken Wand **über die ganze Länge bis zur Tür** frei, weil sie von der Tür aus hineingeschoben
  wird. Andere Pflanzen nutzen den Streifen nur, wenn sie sonst nirgends Platz finden.
- Kandidatenpunkte: Ecken der Nachbarn (mit Abstand), Berührpunkte der Kronen und als Rückfall ein
  10-cm-Raster. Danach Simulated Annealing über Reihenfolge und Lage innerhalb eines Stopps
  (Lastverteilung, Achs-/Stützlast, Ladereihenfolge, empfindliche Pflanzen).
- Kopplung mit der Tourenplanung: Passt eine Tour nicht, wird die Kapazität der Einheit verringert
  und neu geplant. Ein Stopp, dessen Pflanzen gar nicht in das Fahrzeug passen (Tür, Höhe), kommt
  nie wieder auf diese Einheit; bei Platzmangel nach dem zweiten Fehlschlag und in der letzten Runde
  immer. Gleiche Fahrten werden nicht zweimal gepackt. Bleibt eine Tour danach unpassend, behält sie
  ihren Ladeplan mit deutscher Begründung (welche Pflanze, warum) und wird in der Planung markiert.

## D16 – Fahrer-App und Messungen
- Jede Schaltfläche erzeugt ein Ereignis mit Gerätezeit und `client_id`. Die App speichert Ereignisse,
  Fotos und Meldungen zuerst in IndexedDB und sendet sie, sobald Verbindung besteht (Fotos zuerst).
  Der Server legt pro `client_id` nur einmal an; doppeltes Senden ist harmlos. Ein fehlerhaftes
  Ereignis blockiert die übrigen nicht (Savepoint je Ereignis); dauerhaft abgelehnte bleiben sichtbar.
- „Eingeladen“ verlangt ein Foto (Einstellung `driver.require_pickup_photo`), serverseitig geprüft.
- Messung je Stopp: Ankunft → Tragen beginnt = Fixzeit, Tragen beginnt → Eingeladen = Tragezeit,
  Ankunft → Eingeladen = Dauer vor Ort (das, was die Zeitformel vorhersagt). Pausen in einem
  Intervall werden abgezogen; Fahrzeit = Ankunft minus letzte Abfahrt.
- Der Service Worker (`/sw.js`, Bereich `/fahrer`) hält App-Dateien, Fotos und den Tagesplan vor;
  Schreibvorgänge laufen nie über ihn, sondern über die IndexedDB-Warteschlange.
- QR-Etiketten enthalten `KP1:<Pflanzen-ID>`; Scan per BarcodeDetector, sonst Nummer eintippen.

## D17 – Modellanpassung
- Robuste Fehlerfunktion (Huber) über iterativ neu gewichtete kleinste Quadrate, damit die
  Gewichte nur auf Messungen wirken, nie auf die Regularisierung.
- Regularisierung der Parameter zum bisherigen Wert (λ, Skala je Parameter); Faktoren je Person
  zum Wert 1 mit `learning.staff_factor_prior_n` Schein-Messungen, skaliert mit der typischen
  Wirkung des Faktors auf eine Messung.
- Faktoren je Person beziehen sich auf den Durchschnitt (Mittelwert 1). Sonst wären ein
  gemeinsamer Faktor aller Personen und die Formelparameter nicht unterscheidbar.
- Zu wenige Messungen: nur die einflussreichsten Parameter werden angepasst (Anzahl Messungen
  ÷ Mindestanzahl je Parameter), die übrigen bleiben.
- Planungspuffer: Streuung = robuste Standardabweichung von log(gemessen/vorhergesagt) aus der
  Kreuzvalidierung; geplant wird mit exp(z_q · σ).
- Eine bessere Formelstufe wird nur vorgeschlagen; Übernahme erzeugt eine neue Formelversion
  (Quelle „fit“), Personenfaktoren und Puffer als Einstellungen – alles im Protokoll rücknehmbar.

## D18 – Agenten
- Einwahl: Einmal-Code (24 h) → Token `kpa_…` (nur als Hash gespeichert, einmal angezeigt), mit
  Scopes, Ablauf, Widerruf und Ratenbegrenzung (Aufrufe der letzten Minute aus dem Aufrufprotokoll).
- Admin-Agenten im **Produktivbetrieb**: Rolle `agent_admin` ohne RLS-Bypass, Rechte auf
  „Admin-Unterstützung“ beschnitten, Header `X-KP-Tenant` wird abgelehnt. In der **Testphase**:
  Rolle `admin`, alle Rechte, Betrieb über `X-KP-Tenant`. Beides wird beim Prüfen des Tokens
  serverseitig entschieden, nicht im Endpunkt.
- Bestätigungspflicht als allgemeiner Mechanismus: Der Endpunkt ruft `confirm_if_agent(action,
  payload)`. Ohne Freigabe entsteht eine offene Bestätigung (eigene Transaktion) und die Antwort ist
  202. Nach Freigabe wiederholt der Agent die Anfrage mit `X-KP-Confirmation`; die Freigabe passt
  nur zu Token, Aktion und Parametern und gilt einmal. Geheimnisse (API-Schlüssel) stehen nie in
  der Bestätigung.
- `/agent/README.md` wird bei jedem Abruf aus dem OpenAPI-Schema erzeugt (immer aktuell).

## D19 – Abrechnung
- Die Bausteine je Betrieb sind Einstellungen der Ebene Betrieb, die nur der Admin setzen darf
  (`billing.*`). So gelten Protokoll, Rücknahme und Herkunftsanzeige wie überall.
- Rechnungsnummern der Plattform: `KP-<Jahr>-<laufend>` aus einem eigenen Zähler mit Zeilensperre;
  Rechnungen an Kunden eines Betriebs: `R-<Jahr>-<laufend>` aus dem Zähler des Betriebs.
- Rechnungen sind eingefroren (Positionen, Beträge, Aussteller- und Empfängerdaten); Storno als
  eigene Rechnung mit negativen Beträgen. Felder für Online-Zahlung sind vorhanden.
- Abgeholte Pflanzen = Pflanzen der Abholaufträge, deren Stopp im Monat „Eingeladen“ gemeldet hat.
  KI-Verbrauch nur mit Plattform-Schlüssel (BYOK wird nicht berechnet).

## D20 – Einstellungs-KI
- Werkzeuge: Einstellungen auflisten, lesen, ändern, zurücksetzen, erklären, Funktionsbeschreibung
  durchsuchen. Die Änderungen laufen über denselben Dienst wie die Oberfläche (Rechteprüfung,
  Protokoll mit Quelle `settings_ai`), die Antwort enthält die Protokoll-IDs für „Rückgängig“.
- Der Systemtext enthält `docs/APP_GUIDE.md` und alle Einstellungen mit Wert und Herkunft; bei
  Anthropic wird er mit Prompt-Caching übertragen (gleich in jeder Runde).

## D21 – Rücklieferung als Planungsmodus
- Eine Rücklieferung ist ein eigener Auftrag (D13) mit eigenem Plan (`direction = return`). Das
  Modell ist dasselbe; anders sind: Depotzeit **vor** jeder Fahrt (Beladen, `planning.load_min`,
  im Solver als Servicezeit am Start- bzw. Abladeknoten) statt Abladen danach, Ladeplan mit dem
  ersten Stopp an der Tür (Beladereihenfolge rückwärts), eigener Zeitfaktor (`returns.time_factor`,
  auch in der Modellanpassung berücksichtigt) und eigene Preisregel (`returns.price_mode`).
- Frostregel: Frostempfindliche Pflanzen (Pflanze markiert oder Art „empfindlich“) frühestens am
  Stichtag (`returns.frost_safe_date`, Standard 15. Mai); liegt er hinter dem Planungszeitraum,
  erscheint der Auftrag als nicht eingeplant mit Grund „Frost“.
- Fahrer-App: Ereignis `delivered` (Abgestellt, mit Abgabefoto `delivery_proof`) ersetzt `loaded`;
  danach sind Rücklieferung und Abholung „zurückgebracht“. Beim Beladen zeigt die App den Lagerplatz.
- Sammelanlage: Rücklieferungen für alle abgeholten/eingelagerten Aufträge in einem Zeitraum; der
  Wunsch des Kunden aus dem Kundenzugang hat Vorrang.

## D22 – Kundenzugang und Online-Zahlung
- Anmeldung nur über einen persönlichen Link (Einmal-Code, mehrfach nutzbar, Gültigkeit
  `portal.link_days`); kein Passwort. Rolle `customer` mit `customer_id` am Benutzer.
- Ein Kunden-Login erreicht serverseitig nur `/api/portal/*`, `/api/auth/*` und eigene Dateien
  (Fotos eigener Aufträge, eigene Angebote und Rechnungen) – auch Endpunkte, die sonst nur den
  Betrieb prüfen, bleiben zu.
- Fotos nur nach Einwilligung (Text aus `privacy.consent_text`, wird mit Zeitpunkt gespeichert);
  danach läuft die Vollständigkeitsprüfung im Hintergrund.
- Angebot annehmen bestätigt einen Auftrag im Entwurf (abschaltbar).
- Zahlung über eine Anbieter-Schicht: `test` (simulierter Checkout ohne Geld, zum Ausprobieren) und
  `stripe` (Stripe Checkout auf dem verbundenen Konto des Betriebs, Stripe Connect; Plattform-
  Schlüssel und Webhook-Geheimnis in `.env`). Der Webhook wird mit dem Stripe-Signaturverfahren
  geprüft (HMAC-SHA256, Zeitfenster 5 Minuten); bezahlt wird erst durch das Ereignis, nie durch die
  Rückkehr des Browsers.

## D23 – Fokus Logistik: Module statt Löschen
- Lager, Preise/Angebote/Rechnungen an Endkunden, Kundenzugang und Online-Zahlung sind Module
  (`modules.storage`, `modules.customer_billing`, `modules.portal`, `modules.payments`; Ebenen Admin
  und Betrieb, Standard aus). Online-Zahlung setzt den Kundenzugang voraus (`app/core/modules.py`).
- Ein ausgeschaltetes Modul verschwindet aus Menü, Dashboard, Formularen und Einstellungen; seine
  Endpunkte antworten 409 `errors.module_off`. Tabellen und Daten bleiben unverändert, Einschalten
  stellt alles wieder her. Die Plattform-Abrechnung (Admin → Betrieb) ist kein Modul.
- `portal.enabled` heißt jetzt `modules.portal` (umkehrbare Migration `a1f0c3d9e201`, Werte behalten
  ihre Ebene).
- Einstellungen tragen `SettingDef.module`, Datenfelder `info["module"]`; die Oberfläche zeigt beide
  nur, solange das Modul an ist. Die Einstellungs-API liefert die Werte weiter (Agenten, Einstellungs-
  KI), markiert sie aber mit `module_active = false`. Die Lagerplatz-Anzeige der Fahrer-App gehört
  zum Lager-Modul.
- `pricing.typical_tour_stops` und `pricing.local_detour_km` bestimmen den Fahranteil der
  **Kostenschätzung** vor der Planung; sie stehen daher in der Gruppe „Kosten“ und gehören zu keinem
  Modul (Schlüssel unverändert, damit gespeicherte Werte gelten).
- Frostregel, Rücklieferung und Planung lesen keine Lagerdaten; der Status „eingelagert“ bleibt als
  Wert erhalten, wird ohne Lager-Modul aber nicht als Filter angeboten.

## D24 – Felder der Erfassungsmasken
Felder, die keine Formel, Planung, Ladeplanung oder Plattform-Rechnung braucht, stehen unter
„Weitere Angaben“ (`info["advanced"]`, eingeklappt, Pflichtfelder nie). Felder eines Moduls
erscheinen nur mit dem Modul. Nichts wurde gelöscht.

| Maske | Feld | Verwendet in | Entscheidung |
|---|---|---|---|
| Betrieb | Name, Kurzname (Anmeldung Fahrer-App) | Anmeldung, Rechnung | sichtbar |
| Betrieb | Straße, PLZ, Ort | Plattform-Rechnung (Empfänger) | sichtbar |
| Betrieb | Standort Betrieb (Breite/Länge) | Fahrzeiten, Tourenplanung | sichtbar |
| Betrieb | Firmierung, Land, E-Mail, Telefon, aktuelle Saison | nur Anzeige | Weitere Angaben |
| Betrieb | USt-IdNr., Steuernummer, IBAN | Rechnungen an Kunden | Modul Preise/Rechnungen |
| Personal | Name, aktiv | Planung | sichtbar |
| Personal | Führerscheinklassen | Planung (erlaubte Fahrzeuge) | sichtbar |
| Personal | Kürzel, Telefon, E-Mail, Qualifikationen, Farbe, Notizen | nur Anzeige | Weitere Angaben |
| Personal | Lohn, Tragen, Tempo (Reiter Einstellungen) | Kosten, Zeitformel, Teamgröße | sichtbar |
| Fahrzeug | Name, Art, Führerschein, Sitzplätze, aktiv | Planung | sichtbar |
| Fahrzeug | Laderaum L/B/H, Nutzlast, Tür B/H | Planung (Kapazität), Ladeplanung | sichtbar |
| Fahrzeug | Radkästen, Achsen, Stützlast, Kupplung, Anhänger | Ladeplanung, Planung | sichtbar |
| Fahrzeug | Kennzeichen, Türlage, Ladekante, Rampe, Hebebühne, max. Anhängelast, Notizen | nur Anzeige | Weitere Angaben |
| Kunde | Name, Telefon (für den Fahrer) | Fahrer-App | sichtbar |
| Kunde | Firma, E-Mail, Kontaktweg, Einwilligung Fotos, Notizen | Datenschutz, Anzeige | Weitere Angaben |
| Adresse | Straße, PLZ, Ort, Koordinaten | Fahrzeiten, Planung, Fahrer-App | sichtbar |
| Adresse | Parken, Klingel, Zugang | Fahrer-App | sichtbar |
| Adresse | Bezeichnung, Land | nur Anzeige | Weitere Angaben |
| Auftrag | Status, Zeitraum, fester Tag, Zeitfenster, Priorität | Planung | sichtbar |
| Auftrag | Endpreis | Kundenrechnung | Modul Preise/Rechnungen |
| Auftrag | Notizen | Anzeige | Weitere Angaben |
| Pflanze | Bezeichnung, Weg, Topf, Krone, Höhe, Gewicht, gewogen | Zeitformel, Teamgröße, Ladeplanung | sichtbar |
| Pflanze | kippbar, sichern, empfindlich, frostempfindlich | Ladeplanung, Frostregel | sichtbar |
| Pflanze | Unsicherheit Gewicht, nicht stapelbar (immer so), feste Teamgröße, Hilfsmittel, Notizen | selten/nie | Weitere Angaben |
| Pflanze | Lagerplatz | Lager | Modul Lager |

## D25 – Pflanzenarten als interne Wissensbasis
- Die Art steht als Text an der Pflanze (`species_name`, Quelle `species_source`: KI, Wissensbasis,
  von Hand, migriert). `species_id` verweist nur noch intern auf den passenden Eintrag der
  Wissensbasis (Name, botanischer Name oder Alias) und ist nicht mehr schreibbar.
- Eigenschaften an der Pflanze: Frost, kippbar, empfindlich, Stauchbarkeit, Kronendichte, Kippgefahr
  (`tip_tendency`, neu) und die Gewichtsbeiwerte Erde/Krone/Stamm (neu). Die KI liefert Art und die
  Eigenschaften je Pflanze mit Sicherheit (Prompts `message_intake` und `photo_analysis` Version 2).
  Werte unter der halben Prüfschwelle (`photos.min_confidence`) werden verworfen, Werte unter der
  Schwelle bleiben „geschätzt“; fehlende Werte kopiert `complete_plant` einmal aus der Wissensbasis
  (`app/timemodel/knowledge.py`), sonst aus festen Standardwerten. Eigenschaften sind keine
  Prüffelder des Posteingangs (Hintergrundwerte), Frost und „kippbar“ sind dort aber sichtbar.
- Rechnungen lesen nur die Pflanze: Gewichtsschätzung und Kalibrierung, Kippgefahr im Packer,
  Frostregel der Rücklieferung (`frost_sensitive`; „halbhart“ gilt wie bisher nicht als empfindlich).
- `/api/species` und Einstellungen der Ebene „Pflanzenart“ nur noch für den Admin
  (`platform.species`). Frühere Überschreibungen von Betrieben bleiben für deren Wissensbasis gültig.
- Neue Default-Prompts werden als neue globale Version angelegt, wenn die neueste vorhandene globale
  Version älter ist; eigene neuere Versionen des Admins bleiben vorrangig.
- Migration `b7c41e2f9a10` kopiert Name, Gewichtsbeiwerte und Kippgefahr der Art an jede Pflanze und
  füllt nur neue Spalten, Downgrade entfernt sie wieder (geprüft mit 674 Demo-Pflanzen hin und zurück).

## D26 – Feste Teams: Warnungen statt Fehler
- Teams haben Einsatztage (`weekdays`, leer = an allen Tagen, an denen die Mitglieder normal
  arbeiten) und einen optionalen Zeitraum (`valid_from`, `valid_to`).
- Bei `planning.form_teams = fixed` bildet die Planung je Tag nur Einheiten aus gültigen Teams.
  Ein Team, das nicht fahren kann, wird mit Grund gesammelt (`team_issues`: Mitglied abwesend, schon
  in einem anderen Team, Fahrzeug nicht verfügbar oder vergeben, kein Fahrer mit Führerschein,
  gemeinsame Arbeitszeit unter einer Stunde, keine Mitglieder) und im Plan als Warnung gezeigt.
- Nicht eingeplante Stopps bekommen `need` (Personen) und `hints` (`{code, params}`, Übersetzung in
  der Oberfläche): Team um n Personen ergänzen (mit freien Personen), passendes Team kann an den Tagen
  nicht fahren (mit dessen Problemen), passendes Fahrzeug nennen, kein Team angelegt. Die benötigte
  Personenzahl wird mit den tatsächlichen Teammitgliedern berechnet (schwächere Träger → mehr Personen).
- Das Standard-Fahrzeug eines Teams ist eine Vorgabe: Ist es nicht frei, fährt das Team mit einem
  anderen freien Fahrzeug, das jemand im Team fahren darf (Hinweis „vehicle_replaced“, kein Ausfall).
- Der Verfügbarkeitskalender bewertet Teams je Tag mit denselben Regeln (ohne Solver).
- Beobachtung: Ein einzelner Testlauf brach mit einem Segmentation fault in OR-Tools
  (`SolveWithParameters`) ab. Ursache gefunden und behoben, siehe D32.

## D27 – Eigene Kostenpositionen
- Tabelle `cost_items` (Name, Betrag, Bezug, optional Fahrzeug **oder** Person; ohne = ganzer
  Betrieb; aktiv). Module (Paket C) werden als weiterer Bezug ergänzt.
- Tour: Positionen des Betriebs, des Fahrzeugs/Anhängers der Tour und jeder Person im Team. Pro km ×
  gefahrene km, pro Stunde × Tourdauer (je Person), pro Einsatz je Fahrt, pro Tag einmal je Einheit und
  Tag (erste Fahrt; Betriebspositionen auf die Einheiten des Tages verteilt), pro Monat ÷
  `costs.workdays_per_month` wie pro Tag, pro Pflanze × transportierte Pflanzen. Aufteilung auf Stopps:
  Pflanzenpositionen nach Pflanzen, der Rest nach dem Anteil an den direkten Kosten.
- Auftrag vor der Planung: wie die übrigen Kosten mit dem Fahranteil (`pricing.typical_tour_stops`,
  `pricing.local_detour_km`), einem Durchschnittsfahrzeug (Fahrzeugpositionen ÷ Zahl der Fahrzeuge) und
  einer Durchschnittsperson (× Teamgröße ÷ Zahl der Personen).
- Die Positionen werden nach dem Lösen angerechnet; der Solver optimiert weiter mit den Grundsätzen
  (Lohn, Fahrzeug pro km/Stunde). Szenarien vergleichen die Gesamtkosten einschließlich der Positionen.
- `costs.overhead_pct` und `costs.margin_pct` Standard 0 % (reine Logistikkosten); die Marge gehört
  zum Preis-Modul.

## D28 – Fahrzeuge per Foto und Chat, Module
- Neue KI-Aufgaben `vehicle_photo` und `vehicle_chat` (`ai.model.*`, Prompts Version 1, gemeinsames
  JSON-Schema: Fahrzeugwerte, Kosten, Regale je mit Sicherheit, Maßstab, Rückfragen, Antwort).
  Verbrauch und Kosten laufen über die bestehende KI-Schicht.
- Ergebnis ist immer ein `vehicle_draft` (Status offen/bestätigt/verworfen). Der Chat schickt den
  bisherigen Entwurf und den Verlauf mit; die KI gibt den vollständigen, aktualisierten Entwurf zurück.
  Von Hand korrigierte Werte (Sicherheit 1) überschreibt die KI nie. Rückfragen und Prüffelder: Werte
  unter `photos.min_confidence` und fehlende Pflichtwerte (Laderaum, Nutzlast, Türmaße); ohne sie lässt
  sich nicht bestätigen.
- Bestätigen schreibt Spalten des Fahrzeugs, Kosten als Objekt-Einstellungen (Hierarchie und
  Protokoll wie überall) und Regale als Module; ein Eintrag im Änderungsprotokoll mit Quelle
  `vehicle_draft:chat|photo`. Bei Änderungen eines Fahrzeugs werden nur Module geändert oder
  gelöscht, die kein anderes Fahrzeug nutzt (gemeinsame werden nur abgehängt).
- Module (`vehicle_modules`, Zuordnung `vehicle_module_links`): Regal oder Einbau mit Lage, Maßen,
  Eigengewicht. `app/fleet/layout.py` liefert eigene Regale (bisheriger Regal-Editor bleibt) plus
  Module für Packer (Regale als Ebenen, Einbauten als Hindernisse, Nutzlast minus Eigengewicht) und
  Tourenplanung (Fläche).
- Zugfahrzeug + Anhänger: Kombination über das Standard-Anhängerfeld des Zugfahrzeugs; ein Anhänger
  kann mehreren Zugfahrzeugen zugeordnet sein, die Planung nutzt ihn je Tag einmal.
- Das Testmodell erkennt bekannte Modelle (Werte mit Sicherheit 0,5), genannte Maße/Nutzlast/
  Kennzeichen/Kosten/Regale (0,9) und nutzt beim Foto den lokalen A4-Maßstab (Breite/Höhe 0,45,
  Länge von der Tür aus nur geschätzt 0,2).
- Bewertungswerkzeug: Testsätze haben eine KI-Funktion (`photo_analysis`, `vehicle_photo`,
  `vehicle_chat`) und Einträge optional mit Text; ein Testsatz „Fahrzeug per Chat – Beispiele“ wird
  angelegt (Foto-Testsätze brauchen echte Fotos und legt der Admin an).

## D29 – Abladezeit per Formel, Graphen und Dashboard
- Neue Formel `unload` (Stufe 1, „Abladen am Betrieb“): `u_fixed + (u_plant · n_plants + u_kg ·
  total_weight) / team`, Variablen je Fahrt (Pflanzen, Gewicht, schwerste Pflanze, Team, Stopps).
  `planning.unload_mode` (`formula` Standard, `fixed`) – fest oder bei Rechenfehler gilt
  `planning.unload_min`.
- Der Solver arbeitet mit einer Schätzung je Einheit für eine typische volle Fahrt
  (durchschnittliche Pflanzen je Stopp × `pricing.typical_tour_stops`, Teamgröße der Einheit). Nach
  dem Lösen erhält jede Fahrt ihr genaues Abladefenster (`tours.depot_start_min/-end_min/unload_min`);
  bei Rücklieferungen ist es das Beladen vor der Fahrt. Die letzte Fahrt des Tages war bisher ohne
  Abladezeit; das Fenster wird jetzt angezeigt, die Arbeitszeitprüfung bleibt unverändert.
- Fahrer-App: „Abladen beginnt“/„Abladen fertig“ (Tour-Ereignisse `unload_start`/`unload_done`) →
  `unload_measurements` (eine je Tour). Anpassung wie bei der Zeitformel (Huber, Regularisierung zum
  bisherigen Wert, nur so viele Parameter wie Messungen tragen, ab 5 Messungen), Übernahme als neue
  Formelversion (Quelle `fit`).
- Graphen mit recharts bzw. HTML-Zeitachse; Farben als Tokens `--chart-1…4` (feste Reihenfolge,
  hell/dunkel geprüft: Farbsehschwäche-Abstand ≥ 8, im hellen Modus zwei Farben < 3:1 Kontrast →
  jeder Graph hat eine Tabellenansicht und Tooltips). Eine Achse je Graph; Kosten pro Tag und pro
  Pflanze sind getrennte Graphen.
- Genauigkeit: mittlere absolute prozentuale Abweichung je Kalenderwoche der letzten 12 Monate; ohne
  gespeicherte Schätzung (Import, synthetisch) wird mit der aktuellen Formel geschätzt.

## D30 – Mehrstufige Tourenoptimierung, keine LLM-Experimente
- Wunsch des Produktinhabers: erst die schnellste Route, dann Teameinteilung und gezielte
  Experimente. Umgesetzt in `app/planning/staged.py`: Vor dem gewohnten Lauf (der sein volles
  Zeitbudget `planning.time_limit_s` behält) laufen Stufen mit etwa dem halben Budget: schnellste
  Route ≈ 10 % (Kostenfunktion nur Fahrzeit, keine Lohn-, Fix- oder Tageskosten), Teamvarianten
  ≈ 30 %, Suchverfahren ≈ 10 % (nur bis `planning.cluster_max_stops`). Ein Plan rechnet damit etwa
  1,5-mal so lange.
- Die Teameinteilung ist der variabelste Hebel: Sie wird vor dem Solver festgelegt und der Solver
  kann sie nicht ändern. Varianten: bisherige Faustregel, „nach der schnellsten Route“ (je Tag die
  Personenzahl, die die Fahrten der schnellsten Route brauchen), einheitlich 2 und 3 Personen. Bei
  großen Plänen nur die ersten beiden. Bewertung mit der Zielfunktion der Planung (Kosten mit
  Gewichten, Fix- und Tageskosten, Strafe für nicht eingeplante Aufträge). Eine andere Variante als
  die Faustregel wird nur genommen, wenn sie mindestens 3 % besser ist, ein anderes Suchverfahren
  ab 2 %: Kurze Probeläufe streuen (schon ein einzelner 20-s-Lauf schwankt um etwa 2,5 %).
- Varianten „2 Personen“/„3 Personen“ und „nach der schnellsten Route“ nutzen genau die genannte
  Größe (übrige Personen bleiben im Betrieb); die Faustregel verteilt alle verfügbaren Personen.
- Messung (Demo-Betriebe, 20 s Budget, Kosten des fertigen Plans, nach der Korrektur D32):

  | Betrieb | ein Lauf | in Stufen | gewählt | eingeplant |
  |---|---|---|---|---|
  | Grünfink, 100 Aufträge | 2.959,67 € | 2.959,67 € | Faustregel | 44 / 44 |
  | Lindenhof, 80 Aufträge | 2.278,12 € | 2.278,12 € | Faustregel | 40 / 40 |
  | Grünfink, 120 Aufträge | 3.870,56 € | 3.870,56 € | Faustregel | 53 / 53 |

  Weniger Personen je Team ließen 25–40 % mehr Aufträge liegen, „nach der schnellsten Route“ lag
  0,1–0,3 % über der Faustregel. Frühere Läufe schwankten um etwa 2,5 % – zum Teil wegen D32 (der
  Solver las zufällige Speicherwerte); seitdem rechnet er reproduzierbar. Eine erste Fassung mit
  geteiltem Budget war in 2 von 3 Fällen teurer und wurde auf „Stufen zusätzlich“ umgestellt.
  Ergebnis: Auf diesen Daten bringen die Stufen keinen Gewinn, schaden aber nie und legen offen, wie
  optimiert wurde; sie kosten etwa 50 % mehr Rechenzeit (500-Stopp-Test 102 s bei 60 s Budget).
  Standard bleibt `staged` (Wunsch des Produktinhabers), `single` spart Rechenzeit. Die Teameinteilung
  ist ein starker Hebel, die bisherige Faustregel ist auf den Demodaten aber schon die beste Wahl.
- Stopps werden nur einmal aufbereitet (`build_input(reuse=…)`), Teamvarianten bilden nur die
  Einheiten neu. Ist ein Stufenergebnis besser als der letzte Lauf (gleiche Einheiten), wird es
  genommen. Szenarien und Neuplanungen von Szenarien rechnen in einem Lauf.
- **Nicht umgesetzt: Experimente über Sprachmodelle (z. B. kostenlos über OpenRouter).** Gründe:
  (1) Datenschutz – Kundenadressen und Auftragsdaten gingen an kostenlose Modelle, deren Anbieter
  Eingaben oft speichern oder zum Training nutzen; ohne Auftragsverarbeitungsvertrag nicht zulässig.
  (2) Qualität – Sprachmodelle lösen diese Kombinatorik deutlich schlechter als OR-Tools; sinnvolle
  Experimente sind solche, die der Optimierer selbst rechnet. (3) Verfügbarkeit – Gratis-Modelle
  sind stark gedrosselt und wechseln häufig. Ein OpenRouter-Anschluss für die KI-Schicht wäre als
  eigener Anbieter möglich, ist aber nicht Teil dieser Runde.

## D31 – KI-Ladeanordnung: Vergleichsbericht
- Neue KI-Aufgabe `load_layout` (Prompt Version 1): Ladereihenfolge, Ausrichtung und Position je
  Pflanze als JSON. `app/packing/ai_layout.py` macht daraus eine Startlösung (`StartLayout`): Die
  Reihenfolge der Stopps bleibt Regel, jede vorgeschlagene Position wird mit allen Prüfungen des
  Packers (`_valid`) getestet und nur dann übernommen; danach sucht das Simulated Annealing frei weiter
  und behält den Start nur, solange nichts Besseres gefunden wird. KI-Vorschläge werden nie
  ungeprüft übernommen.
- `packing.mode`: `rules` (Standard), `ai_start`, `compare` (beide rechnen, gültig vor mehr
  platzierten Pflanzen vor niedrigerer Punktzahl; beide Ergebnisse im Ladeplan). Die Prüfungen
  während der Tourenplanung bleiben immer regelbasiert (schnell, keine KI-Kosten je Fahrt). Ist die
  KI nicht erreichbar, entscheiden die Regeln (`ai_error` im Ladeplan).
- Vergleich auf 10 Touren zweier Demo-Betriebe (2 s je Tour, Testmodell ohne Schlüssel):

  | | Regeln | KI als Start (Testmodell) |
  |---|---|---|
  | gültige Ladepläne | 10 / 10 | 10 / 10 |
  | nicht platziert | 0 | 0 |
  | Hinweise (weiche Verstöße) | 14 | 14 |
  | mittlere Punktzahl (weniger ist besser) | 203,1 | 188,2 |
  | mittlere Rechenzeit | 0,55 s | 0,52 s |
  | KI-Kosten | – | 0 € |
  | besser auf Touren | 1 | 3 (6 gleich) |

  Der Vorteil entsteht bei großen Touren (über 20 Pflanzen), wo der Packer in 2 s nur 2–3
  Verbesserungsschritte schafft; dort zählt der Start. Er stammt hier vom Testmodell (Reihen nach
  Ladereihenfolge, schwere zuerst, Platz für die Krone), nicht von einer echten KI; von seinen
  Positionen hielten je Tour 1–23 alle Regeln ein und wurden übernommen. Entscheidung: Standard bleibt
  `rules`. Mit API-Schlüssel denselben Vergleich mit einem echten Modell wiederholen; nur wenn er
  messbar besser ist (gleich viele gültige Pläne, niedrigere Punktzahl, vertretbare Kosten und
  Zeit), auf `ai_start` umstellen. Unabhängig davon könnte die Reihenfolge „schwere zuerst je Stopp“
  als zusätzlicher Start der Regeln getestet werden.

## D32 – Fehlerbehebung: Pausen im Solver (Absturz)
- Seltene Abstürze (Segmentation fault) bei der Tourenplanung kamen aus der Pausenlogik von
  OR-Tools (`FillPrePostVisitValues`, laut macOS-Absturzbericht). `SetBreakIntervalsOfVehicle(breaks,
  vehicle, node_visit_transits)` liest die Liste nach dem **internen Index** (`pre_travel(i, j) =
  node_visit_transit[i]`), einschließlich der Start- und Endindizes aller Fahrzeuge. Übergeben wurde
  eine Liste nach Knoten: Sie war zu kurz (Lesen über das Ende hinaus – falsche Werte, gelegentlich
  Absturz) und um einen Platz verschoben (Pausen orientierten sich an der Servicezeit des falschen
  Stopps). Jetzt wird die Liste über alle Indizes mit `IndexToNode` gebaut. Der Fehler bestand seit
  Phase 4; die mehrstufige Optimierung machte ihn durch mehr Solver-Läufe sichtbarer.

## D33 – Runde 2: Kontaktdaten und Datenbestand
- Kontaktdaten (Telefon, E-Mail) sind für Planung und Touren nicht nötig; der Betrieb antwortet auf
  dem Weg, auf dem die Nachricht kam. Deshalb Standard **nicht speichern** (`privacy.store_contact`),
  pro Entwurf zuschaltbar; von Hand eingetragene Daten bleiben. Die KI fragt Kontaktdaten nicht mehr
  als „fehlend“ nach (Prompt Version 3).
- Wiedererkennen ohne Kontaktdaten: gleicher Name an gleicher Straße und PLZ.
- Datenbestand: Name/Adresse (Planung) bis `privacy.customer_retention_days` nach letzter Aktivität,
  Fotos `privacy.photo_retention_days` nach Abschluss, Original-Nachrichten `privacy.draft_text_days`
  (neu, 60 Tage), Kunden-Links 30 Tage nach Ablauf, erledigte Benachrichtigungen nach 90 Tagen,
  Rechnungen gesetzliche Frist. Übersicht auf der Seite „Datenschutz“.

## D34 – Fotos ohne Angaben, Benachrichtigungen
- Eingefügte Fotos ohne Art werden von der KI zugeordnet (`photo_sort`), mit Art **und Pflanzennummer**;
  die Foto-Auswertung läuft danach je Pflanze statt einmal für alle. Von Hand angegebene Arten bleiben
  wie bisher (alter Ablauf).
- Benachrichtigungen sind eine eigene Tabelle (`notifications`), je Entwurf und Art höchstens eine
  offene (erneutes Auswerten aktualisiert sie). Die Nachricht an den Kunden formuliert eine eigene
  KI-Aufgabe (`follow_up`), damit fehlende Fotos je Pflanze konkret benannt werden.

## D35 – Pflanzenbilder
- Echte Fotos haben immer Vorrang. KI-Bilder sind als Fotoart `generated` gespeichert, überall als
  „KI-Bild“ markiert und werden nie als Beleg verwendet (nicht in der Fahrer-Fotoliste, nicht im Export).
- Das Bildmodell bekommt nur Art und Maße (Datenschutz). Ohne Bildmodell zeichnet die App selbst
  (maßstäblich, Farbe nach Art), damit Büro und Fahrer immer ein Bild sehen.

## D36 – Sprachsteuerung
- Werkzeuge statt freier Aktionen: Seite öffnen, suchen, Entwurf, Tagesteam, Touren, Planung,
  Einstellung. Nichts Löschendes und nichts Abrechnungsrelevantes; jede Änderung im Protokoll
  (Quelle „voice“). Das Modell bekommt nur den Befehl und die Ergebnisse, die es abfragt.
- Spracherkennung: mit OpenAI-Modell auf dem Server (Aufnahme wird nicht gespeichert), sonst im
  Browser. Hinweis: Chrome schickt die Aufnahme dafür an Google – wer das nicht möchte, stellt
  `voice.transcription = ai` ein.
- ChatGPT (Wunsch des Produktinhabers) und Claude sind gleichwertig einstellbar.

## D37 – Spontan-Teams
- Ein Tagesteam ist ein normales festes Team mit Gültigkeit genau eines Tages und Kennzeichen
  `ad_hoc`. So nutzt die Planung es ohne Sonderlogik – im Modus „fest“ und im Modus „automatisch“
  (feste Teams zuerst). Unbekannte Namen werden gemeldet, nicht angelegt.

## D38 – Tabellen
- Eine Zeile je Pflanze/Auftrag/Kunde/Stopp mit allen Spalten vom Server; Auswahl, Sortieren, Filtern,
  Gruppieren im Browser (gemerkt pro Gerät). Bearbeiten läuft über die normalen Endpunkte (Prüfung,
  Protokoll, Neuschätzung wie im Formular). Bilder werden nicht exportiert.

## D39 – Touren vorzeitig beenden
- Standard aus (Wunsch: „sollte man aktivieren“). Nur Stopps, die noch nicht begonnen haben, gehen
  zurück; begonnene beendet das Team normal. Verschiebbar ist ein Stopp ohne festen Termin, dessen
  spätestes Datum nach dem Tourtag liegt. Online-Funktion (das Büro muss es sofort wissen).

## D40 – Formel-Diskussion
- Zwei Modelle abwechselnd, höchstens 4 Runden; nur Formel, Variablen und Fehlerkennzahlen gehen an
  die Modelle. Der Vorschlag wird vom Formel-Parser geprüft und an den Messungen bewertet (Startwerte
  und angepasste Werte, im Vergleich zur angepassten aktuellen Formel). **Nie automatisch übernehmen.**
- D30 („keine LLM-Experimente“) betraf das Optimieren der Touren über externe Dienste; der neue Wunsch
  nach „sehr intensivem Einsatz von LLMs“ wird mit Datensparsamkeit je Aufgabe umgesetzt.

## D41 – Kunden-Link
- Modul (Standard aus, wie der Kundenzugang). Kein Konto, ein Link pro Entwurf oder Auftrag, nur der
  Hash des Tokens in `share_links`; die vollständige Adresse steht in der Benachrichtigung des Betriebs,
  damit dieselbe Adresse wiederverwendet wird. Hochladen erst nach Einwilligung, höchstens 60 Fotos.
