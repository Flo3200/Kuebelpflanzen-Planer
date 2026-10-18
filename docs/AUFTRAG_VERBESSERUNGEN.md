# Auftrag: Verbesserungsrunde (Stand 2026-10-18)

Grundlage ist `docs/OFFEN.md` (gesammelte offene Punkte). Dieser Auftrag legt fest, **wie** sie umgesetzt werden, und entscheidet die dort offenen Fragen vorläufig. Wo hier etwas anderes steht als in `OFFEN.md`, gilt dieser Auftrag.

## 0. Arbeitsweise

- Lies zuerst `docs/PLAN.md`, `docs/DECISIONS.md`, `docs/APP_GUIDE.md`, `docs/OFFEN.md` und diesen Auftrag.
- Schreibe einen Umsetzungsplan als neuen Abschnitt in `docs/PLAN.md` (Pakete A–H unten, je mit Abnahmekriterium).
- Arbeite Paket für Paket. Nach jedem Paket: `make check`, Eintrag in `docs/CHANGELOG.md`, Entscheidungen in `docs/DECISIONS.md`, Commit, Push zu GitHub.
- **Nichts endgültig löschen, was sich nicht leicht zurückholen lässt.** Funktionen, die wegfallen, werden aus der Oberfläche entfernt und per Einstellung (Modul-Schalter) deaktiviert. Datenbanktabellen bleiben, Migrationen sind umkehrbar. Code, der wirklich tot ist, darf entfernt werden, wenn Tests das absichern.
- Der Produktinhaber kann keinen Code lesen. Berichte am Ende jedes Pakets in zwei, drei Sätzen auf Deutsch, was sich für ihn in der Oberfläche ändert.
- Bei echten Unklarheiten fragst du nach (siehe Paket H), statt zu raten.
- Bestehende Einstellungs-Hierarchie (Admin → Betrieb → Objekt), Änderungsprotokoll und Mandantentrennung gelten für alles Neue.

## Vorläufige Entscheidungen zu offenen Fragen aus OFFEN.md

1. **Fokus nur Logistik (1d):** Lagerverwaltung, Angebote und Rechnungen an Endkunden sowie das Kundenportal werden als Module **ausgeschaltet und aus der Oberfläche entfernt**, nicht gelöscht. Kunden bleiben, aber nur mit den für die Tour nötigen Feldern (Name, Adresse, Zugangshinweise, optional Telefon für den Fahrer). Die Plattform-Abrechnung (Admin → Betrieb) bleibt.
2. **Gemeinkostenzuschlag (3):** Standard auf 0 %, weiterhin einstellbar.
3. **Graphen (4, 6):** keine Lagerbelegung, da das Lager entfällt. Stattdessen Auslastung von Personal und Fahrzeugen, Touren im Zeitverlauf und Abladefenster.
4. **Pflanzenarten (1c):** Die Verwaltung verschwindet für den Unternehmer. Die Tabelle bleibt **intern** als Wissensbasis mit Standardwerten, nur für den Admin sichtbar. Die KI bestimmt Art und Eigenschaften pro Pflanze und speichert sie am Pflanzendatensatz.
5. **KI-Ladeanordnung (5):** Die KI schlägt eine Start-Anordnung vor; der bestehende Packer prüft und verbessert sie. Das regelbasierte Verfahren bleibt Rückfall und Prüfinstanz. Die KI-Variante wird nur Standard, wenn sie in Tests messbar besser ist.

## Paket A – Fokus Logistik und schlanke Eingaben (OFFEN 1b, 1d)

- Modul-Schalter (Einstellungen) für: Lager, Angebote/Rechnungen an Endkunden, Kundenportal, Online-Zahlung. Standard für neue Betriebe: aus. Alles Ausgeschaltete verschwindet aus Menü, Dashboard und Formularen.
- Alle Erfassungsmasken (Betrieb, Personal, Fahrzeug, Kunde, Auftrag, Pflanze) durchgehen. Für jedes Feld in einer Tabelle in `docs/DECISIONS.md` festhalten: Wird es in Formel, Planung, Ladeplan oder Plattform-Rechnung verwendet? Nein → entfernen oder unter „Weitere Angaben“ einklappen.
- Die Frostregel und andere Funktionen dürfen nicht vom Lager abhängen.
- *Abnahme:* Ein neuer Betrieb sieht nur Logistik-Funktionen; jede Maske zeigt nur Pflichtfelder für die Berechnung; Tests für alle Module an und aus.

## Paket B – Pflanzenarten im Hintergrund (OFFEN 1c)

- Unternehmer-Oberfläche für Pflanzenarten entfernen (`/species` nur noch Admin).
- Bei Foto-Auswertung und Nachrichtenerfassung bestimmt die KI Art, Gewicht, Stauchbarkeit, Kippgefahr und Frostempfindlichkeit mit Sicherheitswert und speichert sie an der Pflanze. Fehlende Werte kommen aus der internen Wissensbasis.
- Folgen prüfen und anpassen: Gewichtsschätzung, Packregeln, Frostregel der Rücklieferung, Lernen aus Messungen. Bestehende Daten migrieren (Werte der Art an die Pflanze kopieren).
- *Abnahme:* Pflanzen ohne Artverwaltung erhalten alle nötigen Eigenschaften; alle betroffenen Tests grün.

## Paket C – Fahrzeuge per Foto und Chat, modular (OFFEN 1)

- **Laderaum-Foto:** Der Unternehmer lädt ein oder mehrere Fotos des Laderaums hoch (mit A4-Blatt oder Zollstock als Maßstab). Die KI leitet Maße, Radkästen, Regale und Türmaße ab, mit Sicherheitswerten. Unsichere Werte werden nachgefragt; alles bleibt manuell korrigierbar. Ergebnis ist ein **Entwurf**, den der Unternehmer bestätigt.
- **Fahrzeug per Chat:** Der Unternehmer beschreibt das Fahrzeug in Worten (optional mit Foto, Fahrzeugschein-Angaben). Die KI erstellt Laderaum, Regale, Nutzlast, Achs- und Stützlast und Kosten, fragt bei Lücken nach und kann später Änderungen per Chat vornehmen. Immer mit Entwurf und Bestätigung, Änderungen im Protokoll.
- **Module:** Regale, Einbauten und Anhänger als wiederverwendbare Module, die Fahrzeugen zugeordnet werden (statt nur Regal-Editor pro Fahrzeug). Anhänger + Zugfahrzeug als Kombination.
- Neue KI-Aufgaben unter `ai.model.*` mit Prompt (versioniert), Kostenerfassung und Testsatz im Bewertungswerkzeug. Das Testmodell muss ohne API-Schlüssel plausible Entwürfe liefern.
- *Abnahme:* Ein Fahrzeug lässt sich vollständig per Chat und per Foto als Entwurf anlegen und bestätigen; Module lassen sich mehreren Fahrzeugen zuordnen; Ladeplanung nutzt das Ergebnis.

## Paket D – Teams durch den Unternehmer (OFFEN 2)

- Oberfläche zum Anlegen fester Teams: Mitglieder, Standard-Fahrzeug (inkl. Module), gültige Tage. Verfügbarkeitskalender zeigt Konflikte.
- Planung mit `planning.form_teams = fixed`: Fehlende oder zu kleine Teams führen zu **Warnungen mit Begründung** pro Stopp, nicht zu Fehlern. Hinweis, welches Team oder welche Person das Problem lösen würde.
- *Abnahme:* Mit festen Teams entsteht immer ein Plan; nicht einplanbare Stopps sind mit verständlichem Grund aufgeführt.

## Paket E – Kosten (OFFEN 3)

- Eigene Kostenpositionen pro Fahrzeug, Person, Modul und Betrieb: Name, Betrag, Bezug (pro km, pro Stunde, pro Einsatz, pro Tag, pro Monat anteilig, pro Pflanze). Sie fließen in Kosten und Szenarien ein.
- Kostenanzeige zeigt **reine Logistikkosten** (Personal, Fahrzeug, eigene Positionen), getrennt von Preis und Marge. Marge und Gemeinkostenzuschlag standardmäßig 0 %.
- *Abnahme:* Eine eigene Kostenposition ändert sichtbar Tour- und Auftragskosten; Kostenaufschlüsselung pro Tour nachvollziehbar.

## Paket F – Abladezeit, Graphen und Dashboard (OFFEN 4, 6)

- **Abladezeit berechnen** statt fester Minuten: neue Formel `unload` im Formeleditor (Startformel aus Fixzeit + Anteil pro Pflanze und Gewicht), lernbar wie die Tragezeit. Dafür in der Fahrer-App zwei Ereignisse am Betrieb: „Abladen beginnt“, „Abladen fertig“. Der Unternehmer kann Formel und Werte einstellen.
- Die Planung zeigt pro Tour Ankunft am Betrieb und Abladefenster.
- **Graphen:** Auslastung von Personal und Fahrzeugen pro Tag, Touren im Zeitverlauf (Zeitachse), Abladefenster am Betrieb, Kosten pro Tag und pro Pflanze, Genauigkeit der Zeitschätzung.
- **Dashboard** neu zusammenstellen: heutige und morgige Touren, offene Entwürfe, nicht einplanbare Aufträge mit Grund, Kosten der Woche, die Graphen oben. Nichts zu Lager, Angeboten oder Rechnungen, solange diese Module aus sind.
- *Abnahme:* Abladezeit kommt aus der Formel und ändert sich mit Pflanzenmenge; Graphen funktionieren mit leeren und mit Demodaten.

## Paket G – KI-Ladeanordnung (OFFEN 5)

- Neue KI-Aufgabe: Aus Fahrzeuggeometrie, Pflanzenliste und Tourreihenfolge schlägt die KI eine Anordnung vor (strukturiertes JSON mit Positionen). Der Packer übernimmt sie als Startlösung, prüft alle Regeln (Kippgefahr, Schwerpunkt, Achs-/Stützlast, schwere Pflanzen, Ladereihenfolge) und verbessert sie.
- Einstellung `packing.mode`: `rules` (Standard), `ai_start`, `compare` (beide rechnen, bessere Lösung gewinnt, Ergebnis wird protokolliert).
- Vergleichstest mit Demodaten: Punktzahl, Verstöße, Rechenzeit, KI-Kosten.
- *Abnahme:* KI-Vorschläge werden nie ungeprüft übernommen; Vergleichsbericht in `docs/DECISIONS.md`.

## Paket H – Konfiguration und Rückfragen (OFFEN 7, 8)

- Nicht programmieren, sondern am Ende eine kurze Checkliste für den Produktinhaber ausgeben: API-Schlüssel und Ausgabenlimit eintragen, Rechnungssteller, Einwilligungstext, Zwei-Faktor-Pflicht, Passwort des Inhaber-Kontos ändern, Hosting.
- Punkt 8 aus `OFFEN.md` ist unklar (abgebrochener Satz). Frage den Produktinhaber danach, bevor du mit Paket A beginnst, und arbeite ohne Antwort mit A–G weiter.

## Reihenfolge

A → B → D → E → C → F → G → H. (A und B vereinfachen alles Weitere; C und G brauchen echte KI-Schlüssel für einen sinnvollen Test und laufen bis dahin mit dem Testmodell.)
