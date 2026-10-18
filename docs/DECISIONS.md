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
