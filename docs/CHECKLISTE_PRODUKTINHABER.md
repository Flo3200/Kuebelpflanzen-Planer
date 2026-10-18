# Checkliste für den Produktinhaber (Stand 2026-10-18)

Diese Punkte kann nur der Betreiber erledigen; programmiert ist dafür nichts mehr.

1. **KI-Schlüssel und Ausgabenlimit:** Unter „Admin → KI“ einen API-Schlüssel hinterlegen (bisher ist
   bei keinem Anbieter einer eingetragen, es läuft nur das Testmodell) und die Modelle je Aufgabe
   wählen (`ai.model.*`, neu: Fahrzeug aus Foto, Fahrzeug per Chat, Ladeanordnung). Das Ausgabenlimit
   pro Betrieb prüfen (Standard 50 € im Monat, `ai.monthly_limit_eur`). Danach die Testsätze im
   Bewertungswerkzeug laufen lassen und den Vergleich der KI-Ladeanordnung wiederholen (D31).
2. **Rechnungssteller:** Unter „Admin → Einstellungen → Plattform-Abrechnung“ die Angaben des
   Rechnungsstellers eintragen (Name, Anschrift, USt-IdNr. oder Steuernummer, IBAN, E-Mail) – bisher leer.
3. **Einwilligungstext für Fotos:** `privacy.consent_text` formulieren (am besten juristisch
   geprüft) – bisher leer.
4. **Zwei-Faktor-Pflicht:** entscheiden, ob für Admin und Inhaber Pflicht (`security.admin_require_2fa`,
   `security.owner_require_2fa`); derzeit hat kein Konto die Zwei-Faktor-Anmeldung aktiviert.
5. **Passwörter:** Passwort des Inhaber-Kontos von „Mein Betrieb“ und des Admin-Kontos
   (`admin@example.com`) ändern. Alte Demo-Konten (`inhaberin@gruenfink.example`,
   `inhaber@lindenhof.example`) existieren noch als Benutzer, obwohl die Demo-Betriebe gelöscht sind –
   bitte deaktivieren oder löschen lassen.
6. **Hosting:** Server, Domain mit HTTPS, Datensicherung und Wiederherstellung festlegen
   (Docker Compose liegt bereit); danach `platform.mode` von „Testphase“ auf „Produktivbetrieb“.
7. **Offene Rückfrage:** Punkt 8 der Anforderungsliste in `OFFEN.md` („Und wie macht …“) ist noch
   unbeantwortet.
