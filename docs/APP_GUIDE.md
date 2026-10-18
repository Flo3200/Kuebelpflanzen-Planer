# Kübelpflanzen-Planer – Funktionsbeschreibung

Diese Beschreibung erklärt, was die App kann und wie die Teile zusammenhängen. Sie richtet sich an
Inhaber, Disposition und Admin – und an die Einstellungs-KI, die damit Fragen beantwortet.

## Überblick

Gärtnereien holen im Herbst Kübelpflanzen (Oleander, Olivenbäume, Palmen, Zitrus …) bei Kunden ab,
überwintern sie und bringen sie im Frühjahr zurück. Die App hilft bei allen Schritten:

1. **Erfassung**: Kunden schicken Nachrichten und Fotos. Die KI macht daraus einen Entwurf mit
   Kunde, Adresse, Pflanzen und Weg; ein Mensch prüft und bestätigt.
2. **Zeit und Preis**: Eine Formel schätzt, wie lange die Abholung dauert, wie viele Personen
   nötig sind und was sie kostet. Daraus entsteht ein Angebot (PDF).
3. **Tourenplanung**: Bestätigte Aufträge werden zu Touren gebündelt – Tag, Fahrzeug, Team,
   Reihenfolge, Pausen.
4. **Ladeplanung**: Für jede Tour wird geprüft, wie die Pflanzen ins Fahrzeug passen (3D).
5. **Fahrer-App**: Das Team sieht seine Touren auf dem Handy, erfasst Zeiten und meldet Abweichungen.
6. **Lernen**: Aus den gemessenen Zeiten wird die Zeitformel verbessert.
7. **Abrechnung**: Die Plattform rechnet monatlich mit den Betrieben ab.

## Module (Fokus Logistik)

Die App ist auf die Logistik ausgerichtet: Abholung, Touren, Beladung, Abladen und Rücklieferung.
Weitere Bereiche sind **Module**, die für einen neuen Betrieb ausgeschaltet sind und unter
„Einstellungen → Module“ eingeschaltet werden (`modules.*`):
- **Lager** (`modules.storage`): Lagerflächen, Lagerbelegung, Lagerplatz je Pflanze.
- **Preise, Angebote und Rechnungen an Kunden** (`modules.customer_billing`): Kundenpreis,
  Angebots-PDF, Kostendeckung, Rechnungen an Endkunden. Ohne das Modul zeigt die App die
  Logistikkosten (Personal, Fahrzeug).
- **Kundenzugang** (`modules.portal`) und **Online-Zahlung** (`modules.payments`, braucht den
  Kundenzugang).
Ein ausgeschaltetes Modul verschwindet aus Menü, Übersicht, Formularen und Einstellungen; die Daten
bleiben erhalten und sind nach dem Einschalten wieder da. Felder, die keine Berechnung braucht,
stehen in den Formularen eingeklappt unter „Weitere Angaben“.

## Rollen

- **Admin** (Plattform): legt Betriebe an, pflegt globale Formeln, Pflanzenarten, KI-Modelle,
  Plattform-Einstellungen und die Abrechnung der Betriebe.
- **Inhaber/in**: alles im eigenen Betrieb, auch Benutzer, Abrechnung und Agenten.
- **Disposition**: Aufträge, Planung, Stammdaten – ohne Benutzer, Abrechnung und Agenten.
- **Fahrer/in**: nur die Fahrer-App mit den eigenen Touren (Anmeldung mit PIN oder Link).
- **Agent**: ein KI-Agent mit Token und begrenzten Rechten (siehe „Agenten“).
- **Kunde**: nur der Kundenzugang mit den eigenen Aufträgen (Anmeldung über einen persönlichen Link).

## Einstellungen und Ebenen

Fast jeder Wert ist eine Einstellung mit Standardwert. Werte gelten in Ebenen:
**Standard → Admin (Plattform) → Betrieb → Objekt** (z. B. eine Person, ein Fahrzeug, eine
Pflanzenart, eine Pflanze). Die genaueste Ebene gewinnt. „Zurücksetzen“ entfernt den Wert einer
Ebene, dann gilt wieder der Wert darüber. Jede Änderung steht im Änderungsprotokoll und lässt sich
mit einem Klick rückgängig machen. Manche Werte darf nur der Admin setzen (z. B. Abrechnung).

Wichtige Gruppen:
- **Team** (`team.*`): Wie viele Personen eine Pflanze tragen (Gewicht, Durchmesser, Höhe,
  Treppen, Steigung, Engstellen), höchste Teamgröße.
- **Personal** (`staff.*`): Lohn, Arbeitgeberanteil, wie viel eine Person allein trägt,
  Geschwindigkeit beim Tragen und Fahren (pro Person einstellbar und lernbar).
- **Zeitmodell** (`time.*`): Gehgeschwindigkeit, Engstellen-Faktor, Planungsquantil (Puffer),
  Streuung der Vorhersage, Formelstufe.
- **Kosten** (`costs.*`): Fahrzeugkosten pro km und Stunde, Kraftstoff, Gemeinkosten, Marge,
  Mehrwertsteuer, Kleinunternehmerregelung für eigene Rechnungen.
- **Preise** (`pricing.*`): Grundpreis, Preis pro Arbeitsminute, pro Pflanze, Mindestpreis,
  Rundung, Entfernungszuschlag (aus, Entfernung, Zonen, Umweg), Preise brutto oder netto.
- **Planung** (`planning.*`): Arbeitszeiten, Pausen, Überstunden, Zeitlimit des Solvers,
  Gewichtung von Kosten und frühen Tagen, Zeitfenster hart oder weich, Ladeprüfung.
- **Fahren** (`drive.*`): Routenanbieter (offline oder Dienst), Umwegfaktor, Durchschnittstempo,
  Parkzeit, Anhängerfaktor.
- **Ladeplanung** (`packing.*`): Abstand zwischen Töpfen, erlaubte Überlappung der Kronen,
  Kippwinkel, schwere Pflanzen, Schwerpunkt-Toleranz, Rechenzeit.
- **Lernen** (`learning.*`): Fehlerfunktion (Huber), Regularisierung, Kreuzvalidierung,
  Mindestanzahl Messungen, Zeitplan, Experimentmodus.
- **Fahrer-App** (`driver.*`): Pflichtfoto beim Einladen, „Pflanze fertig“ einzeln, QR-Modul.
- **KI** (`ai.*`): Modell je Funktion, Ersatzmodell, eigener Schlüssel (BYOK), Ausgabenlimit.
- **Abrechnung** (`billing.*`, Admin): Bausteine je Betrieb, Mehrwertsteuer, Rechnungssteller.
- **Agenten** (`agents.*`): Gültigkeit der Tokens, Aufrufe pro Minute.
- **Rücklieferung** (`returns.*`): Frostregel und Stichtag, Zeitfaktor, Preisregel, Zeitraum.
- **Module** (`modules.*`): Lager, Preise/Angebote/Rechnungen an Kunden, Kundenzugang, Online-Zahlung.
- **Kundenzugang** (`portal.*`, `payments.*`): Gültigkeit des Links, Anbieter der Online-Zahlung.

## Erfassung: Kunden, Aufträge, Pflanzen

- **Kunden** mit Adressen (Hinweise zu Klingel, Parken, Zugang) und Einwilligung für Fotos.
- **Aufträge**: Abholung (Herbst) oder Rücklieferung (Frühjahr), Zeitfenster, frühestes und
  spätestes Datum, Mindestteam, Status (Entwurf, bestätigt, geplant, abgeholt, eingelagert,
  zurückgebracht, storniert).
- **Pflanzen**: Art, Topfform und -maße, Kronenform und -maße, Höhe, Gewicht (geschätzt oder
  gewogen), kippbar, empfindlich, sichern, Unverträglichkeiten, benötigte Hilfsmittel.
- **Wege**: Abschnitte (eben, Treppe, Rampe, Tür, Aufzug, Engstelle) mit Länge, Stufen,
  Breite, Belag und Steigung – sie bestimmen Tragezeit und Teamgröße.
- **Posteingang**: Nachricht einfügen oder weiterleiten, Fotos dazu. Die KI erstellt einen
  Entwurf; jeder Wert hat eine Sicherheit. Unsichere Werte sind markiert. Erst nach Bestätigung
  entstehen echte Daten.
- **Foto-Set**: Pro Pflanze frontal und seitlich mit A4-Blatt als Maßstab, schräg von oben, Topf;
  für den Weg eine lückenlose Bildfolge. Die KI prüft Vollständigkeit und schätzt Maße.

## Zeitmodell und Formeln

Die Dauer einer Abholung kommt aus einer Formel, die Admin und Betrieb im Formeleditor ändern
können (sichere Formelsprache, keine Programmierung). Startformel (Stufe 1):

- Arbeit je Pflanze = (a0 + a1 · Gewicht) · (Weglänge / Gehgeschwindigkeit + k_height ·
  Höhenmeter) · Engstellen-Faktor · Hilfsmittel-Faktor
- Dauer je Stopp = t_fixed + max(Summe Arbeit / Team, größte Einzelarbeit / Trageteam) / Tempo

**Dauer** (Minuten vor Ort) ist für die Planung wichtig, **Arbeitszeit** (Dauer × Personen) für
die Kosten. Stufe 2 ergänzt Zeiten je Pflanze. Geplant wird mit einem Puffer: dem gewählten
Quantil (Standard 80 %) der Vorhersage. Änderungen an Formeln wirken sofort auf alle Schätzungen.

## Teamgröße

Pro Pflanze wird bestimmt, wie viele Personen sie tragen: aus Gewicht (was eine Person allein
trägt, Faktor für Teams), Topfdurchmesser und Höhe (Griff), Treppen, Steigung, Engstellen und
Hilfsmitteln (Sackkarre, Kübelroller, Hubwagen). Pro Stopp braucht das Team mindestens so viele
Personen wie die schwerste Pflanze. Mehr als die höchste Teamgröße wird markiert.

## Kosten und Preise

Der Kundenpreis, Angebote und Rechnungen an Kunden gehören zum Modul „Preise, Angebote und
Rechnungen an Kunden“. Selbstkosten = Arbeitszeit · Stundenkosten (Lohn + Arbeitgeberanteil) + Fahrzeugkosten +
Hilfsmittel + Gemeinkosten. Der Kundenpreis kommt aus der Preisformel: Grundpreis + Preis pro
Arbeitsminute + Preis pro Pflanze + Entfernungszuschlag, mindestens der Mindestpreis. Angebote
werden als PDF erzeugt. Nach der Planung zeigt jeder Auftrag, ob der Preis die Kosten deckt.

## Tourenplanung

Die Planung bündelt bestätigte Aufträge über mehrere Tage. Jede Einheit ist Tag × Fahrzeug
(mit Anhänger) × Team. Beachtet werden: Verfügbarkeit von Personal und Fahrzeugen,
Führerscheinklassen, Arbeitszeit und Pausen nach Arbeitszeitgesetz, Überstunden, Kundenzeitfenster
(hart oder weich), Kapazität nach Gewicht, Grundfläche und Volumen, Mehrfachfahrten, Teamgröße,
Hilfsmittel, unverträgliche Pflanzen, fixierte Touren. Stopps, die nicht passen, erscheinen mit
Grund. Touren lassen sich verschieben (Zeitachse) und fixieren; bei Stornierung oder Ausfall
zeigt die App „Neu planen“. **Szenarien** vergleichen z. B. „+1 Person“ oder „+1 Fahrzeug“.

## Ladeplanung (3D)

Für jede Tour wird ein Ladeplan berechnet: Töpfe sind starr, Kronen dürfen sich etwas
überlappen. Zu hohe Pflanzen werden gekippt oder gelegt (wenn erlaubt). Radkästen, Regale,
Achslasten und Stützlast werden beachtet. Die Ladereihenfolge folgt der Tour: bei der Abholung
steht, was zuerst eingeladen wird, ganz hinten. Passt eine Tour nicht, plant die Tourenplanung
neu oder nennt Pflanze und Grund. Ansicht: Draufsicht, 3D und Schritt für Schritt.

## Rücklieferung im Frühjahr

Für abgeholte und eingelagerte Aufträge legt die Disposition unter „Aufträge → Rücklieferungen
anlegen“ die Rücklieferungen in einem Zeitraum an (z. B. April bis Mai). Pflanzen, Wege und
Zeitfenster kommen aus der Abholung; einen Terminwunsch des Kunden aus dem Kundenzugang übernimmt
die App. Geplant wird als eigener Plan mit Richtung „Rücklieferung“: Vor jeder Fahrt wird im
Betrieb beladen (`planning.load_min`), frostempfindliche Pflanzen kommen erst ab dem frostsicheren
Stichtag zurück (`returns.frost_rule`, `returns.frost_safe_date`), die Dauer vor Ort kann einen
eigenen Faktor haben (`returns.time_factor`) und der Preis eigene Regeln (`returns.price_mode`).
Im Ladeplan steht der erste Stopp an der Tür; die Fahrer-App zeigt beim Beladen den Lagerplatz und
beim Kunden den Schritt „Abgestellt“ mit Foto.

## Kundenzugang und Online-Zahlung (Module)

Nur mit eingeschaltetem Modul „Kundenzugang“. Auf der Seite eines Kunden erzeugt „Kundenzugang“ einen persönlichen Link (Gültigkeit
`portal.link_days`), den der Betrieb dem Kunden schickt. Der Kunde sieht dort nur seine eigenen
Aufträge mit Fortschritt und Termin, kann Fotos nach Anleitung hochladen (nach Einwilligung), den
Standort auf der Karte setzen, Angebote ansehen und annehmen (das bestätigt den Auftrag), einen
Wunsch für die Rücklieferung angeben und Rechnungen ansehen. Ist die Online-Zahlung eingeschaltet
(`payments.provider`: Testzahlung oder Stripe mit dem Stripe-Konto des Betriebs), kann er offene
Rechnungen online bezahlen; die Rechnung steht danach auf „bezahlt“.

## Fahrer-App

Unter `/fahrer` (auf dem Handy als App speicherbar). Anmeldung mit Betriebskennung und PIN oder
persönlichem Link. Zeigt die eigenen Touren von heute und morgen, Stopps mit Navigation, Hinweisen,
Pflanzen und Wegfotos. Große Schaltflächen: Ankunft – Tragen beginnt – (Pflanze fertig) –
Eingeladen (mit Pflichtfoto) – Weiterfahren, dazu Pausen. Funktioniert ohne Netz: Eingaben werden
gespeichert und später gesendet. Abweichungen (schwerer, größer, Weg anders, Kunde nicht da,
Schaden) werden gemeldet und im Büro unter „Meldungen“ übernommen oder verworfen.
Optional: QR-Etiketten für Pflanzen; der Scan beim Einladen bestätigt den Platz.

## Lernen aus Messungen (Modellqualität)

Aus den Zeiten der Fahrer-App entstehen Messungen je Stopp. Die Modellanpassung schätzt die
Parameter der Zeitformel und die Geschwindigkeit je Person neu (robust gegen Ausreißer,
regularisiert zum bisherigen Wert, mit Kreuzvalidierung). Das Ergebnis ist ein **Vorschlag**:
Fehler vorher und nachher, Diagramm „vorhergesagt gegen gemessen“, Fehler nach Merkmal,
Planungspuffer. Übernommen wird erst nach Entscheidung (neue Formelversion, rücknehmbar).
**Experimentmodus**: Ein einstellbarer Anteil der Stopps bekommt bewusst ein größeres Team, damit
der Effekt der Teamgröße gelernt werden kann – nie kleiner als nötig.

## KI-Funktionen

Nachrichtenerfassung, Foto-Vollständigkeitsprüfung, Foto-Auswertung, Einstellungs-KI und
Unterstützung. Für jede Funktion ist das Modell einstellbar, dazu ein Ersatzmodell. Ein Betrieb
nutzt den Plattform-Schlüssel (Abrechnung über den Admin) oder einen eigenen (BYOK). Jeder Aufruf
wird mit Tokens und Kosten erfasst; ein Ausgabenlimit warnt und sperrt. Ohne Schlüssel arbeitet
ein Testmodell mit einfachen Regeln.

## Einstellungs-KI

Der Assistent kennt diese Beschreibung und alle Einstellungen mit Wert und Herkunft. Er erklärt
Funktionen und ändert Einstellungen auf Wunsch – nur im Rahmen der eigenen Rechte. Jede Änderung
steht im Änderungsprotokoll mit der Quelle „Einstellungs-KI“ und hat einen Rückgängig-Knopf.

## Agenten

KI-Agenten arbeiten über die REST-API. Inhaber (für den Betrieb) oder Admin (für die Plattform)
erzeugen unter „Agenten“ einen Einwahl-Link mit einmaligem Code und wählen die Rechte (lesen,
Entwürfe, Stammdaten, planen, Einstellungen; Admin: Admin-Unterstützung oder alles). Der Agent
tauscht den Code gegen ein Token. Tokens laufen ab, lassen sich widerrufen und sind in der Zahl
der Aufrufe pro Minute begrenzt; jeder Aufruf wird protokolliert. Löschende oder
abrechnungsrelevante Aktionen muss ein Mensch unter „Agenten → Bestätigungen“ freigeben.
**Testphase/Produktivbetrieb** (Admin-Einstellung `platform.mode`): Im Produktivbetrieb dürfen
Admin-Agenten nur noch Admin-Unterstützung leisten und keine Aufgaben für Betriebe ausführen.
Die Anleitung für Agenten steht unter `/agent/README.md`.

## Abrechnung

Der Admin legt je Betrieb fest, welche Bausteine gelten: Abo (monatlich oder jährlich),
Preis pro abgeholter Pflanze, KI-Verbrauch nach Modellpreis mit optionalem Aufschlag (entfällt
bei eigenem Schlüssel). Am Monatsanfang entstehen automatisch Rechnungen (PDF, fortlaufende
Nummer, Pflichtangaben, Mehrwertsteuer oder Kleinunternehmerregelung). Betriebe sehen Verbrauch
und Rechnungen unter „Abrechnung“. Optional erstellen Betriebe Rechnungen an ihre Kunden.

## Datenschutz

Fotos von Gärten und Wohnungen sind personenbezogen: Einwilligung wird gespeichert, Standortdaten
werden aus Fotos entfernt, Fotos und Kundendaten werden nach einer einstellbaren Frist gelöscht
(Rechnungsdaten bleiben wegen der Aufbewahrungspflicht). Auf Anfrage werden alle Daten eines
Kunden exportiert oder gelöscht. Jeder Betrieb sieht nur seine eigenen Daten.
