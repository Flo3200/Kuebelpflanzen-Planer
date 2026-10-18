# Offene Punkte / noch zu programmieren

Stand 2026-10-18. Gesammelt aus dem Gespräch mit der Produktinhaberin bzw. dem Produktinhaber.

## Bereits per Einstellung erledigt (Plattformebene)
- `planning.form_teams = fixed`: Teams legt der Unternehmer fest.
- `portal.enabled = false`: Kein Endkunden-Zugang.
- `costs.margin_pct = 0`: Kosten enthalten keine Marge.
- Testdaten (Demo-Betriebe Lindenhof, Grünfink) gelöscht; neuer Betrieb „Mein Betrieb“.

## Zu programmieren

### 1. Fahrzeug aus Laderaum-Foto (Punkt 2)
- Der Unternehmer fotografiert den Laderaum eines Fahrzeugs; die App leitet daraus Maße und Aufteilung des Laderaums ab (KI-Bildauswertung, Rückfrage bei Unsicherheit, manuelle Korrektur).
- Fahrzeuge werden **modular** zugeordnet bzw. zusammengesetzt (Regale/Module pro Fahrzeug, bisher nur `PUT /vehicles/{id}/shelves` und Regal-Editor von Hand).
- Neuer KI-Aufgabentyp (`ai.model.*`), Prompt, Kostenerfassung, Eval-Set.
- **Fahrzeug per Chat anlegen:** Statt Formular schreibt der Unternehmer dem Chat Infos zum Fahrzeug (Text, optional Foto); die KI erstellt daraus das Fahrzeugmodell (Laderaum, Regale, Tragfähigkeit, Kosten) und fragt bei Lücken nach. Änderungen später ebenfalls per Chat.

### 1b. Eingaben auf das Notwendige reduzieren
- Alle Erfassungsmasken (Fahrzeug, Personal, Betrieb, Kunde, Auftrag) durchgehen und auf das beschränken, was die Berechnung wirklich braucht (z. B. Tragfähigkeit, Laderaum, Kosten) – keine Felder wie E-Mail, Telefon, Steuernummer usw., sofern nicht für Planung/Rechnung zwingend.
- Pro Feld festhalten: wird es in einer Formel/Planung verwendet? Wenn nein, entfernen oder optional ausblenden.

### 1c. Pflanzenarten entfernen
- Die Verwaltung der Pflanzenarten (`/species`, UI, Überschreibungen pro Betrieb) fällt aus der Oberfläche weg.
- Die KI bestimmt Art und die daraus nötigen Eigenschaften (Gewicht, Stauchbarkeit, Kippgefahr, Frostempfindlichkeit) im Hintergrund aus den Fotos/Angaben; Ergebnis wird am Pflanzendatensatz gespeichert.
- Folgen prüfen: Gewichtsschätzung, Packregeln pro Art, Frostregel der Rücklieferung, Lernen aus Messungen, Migration der Daten.

### 1d. Ausschließlich Logistik (kein Lager)
- Das Programm konzentriert sich nur auf Logistik: Abholung, Touren, Beladung, Abladen, Rücklieferung.
- Lagerverwaltung entfällt: Lagerflächen (`/storage-areas`), Lagerbelegung (`/storage/occupancy`), Annahmeprüfung nach Lagerplatz, Einstellungen `general.storage_*` und zugehörige Dashboard-Anzeigen.
- Folgen prüfen: Abladezeitpunkt (Punkt 4) ohne Lagerbezug; Datenmigration; ob Rechnungen, Angebote und Kundenverwaltung ebenfalls außerhalb des Logistik-Fokus liegen (nachfragen).

### 2. Teambildung durch den Unternehmer
- UI und Regeln für feste Teams: Teams anlegen, Mitglieder und Fahrzeug zuordnen (Endpunkte `/teams` existieren; prüfen, ob die Oberfläche das mit `form_teams = fixed` vollständig abdeckt).
- Planung muss mit fehlenden/zu kleinen Teams sauber umgehen (Warnung statt Fehler).
- Zusammenspiel mit modularer Fahrzeugzuordnung (Team ↔ Fahrzeug ↔ Module).

### 3. Kosten
- Unternehmer kann **eigene Kostenpositionen** für Fahrzeuge u. Ä. hinzufügen (heute nur feste Felder: pro km, pro Stunde, Kraftstoff, Verbrauch, Hilfsmittel pro Einsatz).
- Kostenanzeige = reine **Logistikkosten**, ohne Marge; klar von Preis/Marge trennen. Prüfen, ob Gemeinkostenzuschlag (15 %) dazugehört oder ebenfalls auf 0 soll.

### 4. Abladezeitpunkt und Graphen
- Die App berechnet, **wann** abgeladen wird (heute nur feste Abladezeit `planning.unload_min`), und der Unternehmer kann das einstellen.
- Graphen zur Auslastung/Zeitverlauf im Betrieb anzeigen (Lagerbelegung, Abladefenster, Touren).

### 5. Ladeanordnung per KI
- Ladeplanung heute regelbasiert (`packing.*`, OR-Verfahren). Neu: KI schlägt die Anordnung vor oder optimiert; Regeln bleiben als Prüfung (Kippgefahr, Schwerpunkt, schwere Pflanzen).

### 6. Dashboard für den Unternehmer
- Endpunkt `/dashboard` existiert; Inhalt und Oberfläche mit dem Unternehmer abstimmen (Aufträge, Touren, Kosten, Lager, Graphen aus Punkt 4).

### 7. Offen aus der Konfiguration
- KI-Modelle (`ai.model.*`) und API-Schlüssel eintragen; Ausgabenlimit prüfen.
- Rechnungssteller (Plattform), Einwilligungstext für Fotos, Zwei-Faktor-Pflicht entscheiden.
- Passwort des Inhaber-Kontos ändern; Hosting auf Server.

### 8. Noch unklar
- Punkt 8 der Anforderungsliste war leer; Satz „Und wie macht …“ abgebrochen. Nachfragen.
