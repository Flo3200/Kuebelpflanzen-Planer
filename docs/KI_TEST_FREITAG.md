# Checkliste: KI-Funktionen testen (Freitag, 2026-10-23)

Ohne Schlüssel arbeitet überall das kostenlose Testmodell mit einfachen Regeln. Für den echten Test:

## 1. Schlüssel und Modelle (Admin)
1. **Admin → KI → Modelle**: beim Anbieter **Anthropic** den API-Schlüssel eintragen.
2. Beim Anbieter **OpenAI** den API-Schlüssel eintragen und den Anbieter **einschalten**. Vorbereitet
   sind „ChatGPT (GPT-5)“, „OpenAI Bildgenerierung (gpt-image-1)“ und „OpenAI Spracherkennung
   (gpt-4o-transcribe)“ – die Modellnamen bei OpenAI kurz prüfen und bei Bedarf anpassen.
3. **Admin → Einstellungen → Künstliche Intelligenz**: Modell je Funktion zuordnen, Vorschlag:

   | Funktion | Modell |
   |---|---|
   | Nachrichtenerfassung, Fotos zuordnen, Foto-Prüfung, Foto-Auswertung | Claude Sonnet 5.5 |
   | Nachfrage formulieren, Spontan-Team aus Nachricht | Claude Haiku 5.5 |
   | Sprachsteuerung | ChatGPT (GPT-5) – oder Claude Sonnet 5.5 zum Vergleich |
   | Spracherkennung | OpenAI Spracherkennung |
   | Pflanzenbild erzeugen | OpenAI Bildgenerierung |
   | Formel-Diskussion | Teilnehmer wählt man beim Start (ChatGPT und Claude Opus 5.5) |
   | Einstellungs-KI, Fahrzeug per Chat/Foto, Ladeanordnung | Claude Sonnet 5.5 |

4. Ausgabenlimit je Betrieb prüfen (Admin → Betriebe → Einstellungen → KI).

## 2. Ein Knopf für alles
**Admin → KI → Funktionstest → „Alle KI-Funktionen testen“.** Jede Funktion läuft einmal mit
einem erfundenen Beispiel (keine Kundendaten). Alles sollte „OK“ sein; die Spracherkennung zeigt nur,
ob ein OpenAI-Modell eingestellt ist (echte Aufnahme siehe unten).

## 3. Von Hand ausprobieren (als Betrieb)
- [ ] **Posteingang**: einen WhatsApp-Chat mit Fotos markieren, kopieren, einfügen (Strg+V) – ohne
      etwas anzugeben. Prüfen: Fotos richtig den Pflanzen zugeordnet? Benachrichtigung (Glocke) mit
      Nachricht an den Kunden, wenn Fotos fehlen?
- [ ] **Kunden-Link**: Einstellungen → Module → „Kunden-Link für Fotos und Standort“ einschalten; im
      Entwurf „Kunden-Link kopieren“, auf dem Handy öffnen, Fotos schicken, Standort teilen. Kommt
      die Benachrichtigung, wird der Entwurf neu ausgewertet?
- [ ] **Kontaktdaten**: Entwurf ohne Haken „Kontaktdaten übernehmen“ bestätigen → beim Kunden keine
      Telefonnummer. Seite „Datenschutz“ ansehen.
- [ ] **Pflanzenbilder**: Auftrag ohne Fotos → „Bilder erzeugen“. Sieht das KI-Bild plausibel aus?
      In der Fahrer-App erscheint es mit „KI-Bild“.
- [ ] **Sprachsteuerung** (Mikrofon oben rechts): „Öffne die Planung“, „Morgen fahren Lea und Tom mit
      dem Sprinter“, „Neue Nachricht: …“, „Welche Touren sind morgen?“, „Suche Sommer“.
- [ ] **Spontan-Team** auf der Seite Teams per Satz.
- [ ] **Tabellen**: Spalten anklicken, Pflanzenbilder, Excel-Export.
- [ ] **Formel-Diskussion**: Formeln → KI-Diskussion, ChatGPT gegen Claude, Frage aus
      `docs/FORMEL_DISKUSSION.md`. Bewertungstabelle ansehen, nur bei klarer Verbesserung übernehmen.
- [ ] **Tour vorzeitig beenden**: Einstellung „Touren vorzeitig beenden erlauben“ an, in der Fahrer-App
      testen; Meldung im Büro?
- [ ] **Kosten**: Admin → KI → Verbrauch – was haben die Tests gekostet?

Auffälligkeiten bitte notieren (Funktion, was eingegeben wurde, was herauskam).
