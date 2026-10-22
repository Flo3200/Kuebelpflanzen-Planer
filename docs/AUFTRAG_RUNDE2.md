# Auftrag: Verbesserungsrunde 2 (Stand 2026-10-22)

Wunschliste des Produktinhabers (wörtlich zusammengefasst) und wie sie umgesetzt wird. Rückfragen
waren ausdrücklich nicht gewünscht („einfach machen“); wo die Liste offen ist, steht hier die
gewählte Auslegung. Was schon gut funktioniert, bleibt unverändert.

| # | Wunsch | Auslegung / Umsetzung | Paket |
|---|---|---|---|
| 1 | Fotos mit dem Text hineinkopieren, nichts angeben; fehlen Bilder, kommt eine Benachrichtigung mit einer von der KI formulierten Nachricht | Posteingang: Text und Bilder in ein Feld einfügen (Strg+V, Ziehen, Auswahl). Die KI ordnet jedes Foto selbst zu (Art des Fotos, welche Pflanze). Fehlen Fotos oder Angaben, entsteht eine **Benachrichtigung** (Glocke oben) mit fertiger Nachricht an den Kunden zum Kopieren | I |
| 2 | Kontaktdaten des Kunden nur, wenn der Unternehmer das möchte | Einstellung `privacy.store_contact` (Standard **aus**). Im Entwurf ein Schalter „Kontaktdaten übernehmen“ | J |
| 3 | Speicherung von Kundendaten prüfen | Datenbestand und Fristen in `DECISIONS.md` (D33); Original-Nachrichten der Entwürfe werden nach einer Frist geleert; Seite „Datenschutz“ mit Übersicht, was gespeichert ist und wann es gelöscht wird | J |
| 4 | Inaktive Felder nur ganz unten (z. B. Kundenliste) | Menü: täglich gebrauchte Bereiche oben, selten gebrauchte (Kunden, Module, Hilfsmittel, Szenarien, Formeln …) in „Weitere Bereiche“ ganz unten, eingeklappt. Übersicht: leere Kacheln rutschen nach unten | K |
| 5 | Sprachsteuerung, Knopf drücken, sprechen, ChatGPT bedient die App | Mikrofon-Knopf oben in jeder Seite. Sprache → Text (OpenAI-Transkription, sonst Spracherkennung des Browsers) → KI mit Werkzeugen (öffnen, suchen, Nachricht anlegen, Tagesteam anlegen, Planung starten, Einstellungen) → App führt aus. OpenAI (ChatGPT) und Claude werden beide unterstützt | L |
| 6 | Teams spontan einrichten, am besten per Nachricht | „Spontan-Team“: ein Satz wie „Morgen fahren Lea und Tom mit dem Sprinter“ (getippt oder gesprochen) legt ein Tagesteam an; dazu ein Schnellformular | M |
| 7 | Was gut geht, bleibt | keine Umbauten an Planung, Ladeplanung, Fahrer-Abläufen | – |
| 8 | Mit ChatGPT und Claude diskutieren, welche Formeln man nimmt | Formeleditor: „KI-Diskussion“ – zwei Modelle (z. B. ChatGPT und Claude) diskutieren in Runden über die Formel mit den echten Messwerten; der Vorschlag wird gegen die Messungen geprüft und kann als neue Formelversion übernommen werden. Startbeitrag von Claude in `docs/FORMEL_DISKUSSION.md` | N |
| 9, 10 | Unternehmer und Abholer sehen die Pflanze als Bild | Pflanzenbild in Pflanzenliste, Tabellen und Fahrer-App: echtes Foto, sonst ein **KI-Bild** (Bildgenerierung, deutlich als „KI-Bild“ markiert) | O |
| 11 | Intensiver Einsatz von LLMs, Bildgenerierung, Bilder auslesen → Datensätze | Neue KI-Aufgaben: Fotos zuordnen, Nachfrage formulieren, Pflanzenbild erzeugen, Sprachbefehl, Spontan-Team, Formel-Diskussion. Fotos mit mehreren Pflanzen werden den Pflanzen zugeordnet | I, L, M, N, O |
| 12 | Excel-ähnliche Tabellen, modulare Übersichten zum Anklicken | Seite „Tabellen“: Datenquelle wählen (Pflanzen, Aufträge, Kunden/Adressen, Stopps), Spalten per Häkchen (Adresse, Pflanzenbild, Pflanzenname, Maße …), sortieren, filtern, gruppieren, direkt bearbeiten, als Excel/CSV exportieren, Ansichten merken | P |
| 13 | Expansion B2C: Standort und Bilder teilen | Modul „Kunden-Link“ (Standard aus): persönlicher Link ohne Konto, über den der Kunde Fotos hochlädt und seinen Standort teilt; landet direkt im Entwurf, die KI wertet neu aus | Q |
| 14 | ggf. Lagersoftware | Lager ist als Modul vorhanden (aus); keine Änderung | – |
| 15 | Zusätzlich zum Puffer ggf. Abbruchmöglichkeiten, aktivierbar | Einstellung `planning.abort_enabled` (Standard aus): Fahrer können eine Tour vorzeitig beenden; offene Stopps gehen zurück in die Planung, das Büro bekommt Meldung und Benachrichtigung. Die Planung zeigt, welche Stopps verschiebbar wären | R |
| 16 | Am Freitag alle Funktionen mit KI testen | „KI-Funktionstest“ im Admin-Bereich (ein Knopf, testet jede KI-Aufgabe mit dem eingestellten Modell) und Checkliste `docs/KI_TEST_FREITAG.md` | S |

## Grundsätze
- Datenschutz bleibt Vorgabe (D30): An KI-Dienste gehen nur die Daten, die die Aufgabe braucht;
  Bildgenerierung bekommt nur Pflanzendaten, Sprachbefehle keine Kundenlisten.
- Jede KI-Funktion hat ein Testmodell, das ohne Schlüssel plausibel arbeitet.
- Alles Neue mit Tests, Einträgen in `CHANGELOG.md`, `DECISIONS.md` und `APP_GUIDE.md`.
