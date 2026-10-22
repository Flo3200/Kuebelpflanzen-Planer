# Formel-Diskussion: Startbeitrag von Claude

Wunsch des Produktinhabers: „Mal mit ChatGPT und Claude diskutieren, welche Formeln man nimmt.“
Die eigentliche Diskussion läuft in der App (Formeleditor → „KI-Diskussion“): ChatGPT und Claude
sprechen abwechselnd über die Formel, mit den echten Messwerten des Betriebs; der Vorschlag wird
geprüft, an den Messungen bewertet und nur auf Knopfdruck als neue Formelversion übernommen.
Dieser Text ist Claudes Eröffnung, damit die Runde nicht bei null anfängt.

## Die heutige Formel (Stufe 1)

    Arbeit je Pflanze = (a0 + a1 · Gewicht) · (Weglänge / Gehtempo + k_height · Höhenmeter)
                        · Engstellen-Faktor · Hilfsmittel-Faktor
    Dauer je Stopp    = t_fixed + max(Summe Arbeit / Team, größte Einzelarbeit / Trageteam) / Tempo

Stärken: wenige Parameter (4), jeder mit klarer Bedeutung, gut lernbar, Teamgröße wirkt richtig
(Arbeit wird geteilt, die schwerste Pflanze begrenzt).

## Schwächen, die ich sehe

1. **Keine Zeit für das Hantieren.** Steht eine Pflanze direkt am Fahrzeug (Weg ≈ 0), ist die Arbeit
   fast 0. In Wirklichkeit kostet Anheben, Sichern, Abstellen jede Pflanze 1–3 Minuten.
   → feste Zeit je Pflanze `h0 + h1 · Gewicht` (Stufe 2 hat das schon).
2. **Treppen mit schweren Töpfen.** Höhenmeter wirken heute linear und unabhängig vom Gewicht. Ein
   80-kg-Kübel auf 20 Stufen ist aber viel mehr als doppelt so langsam wie ein 40-kg-Kübel.
   → Wechselwirkung: `k_height · Höhenmeter · (1 + k_heavy · max(0, Gewicht − 40) / 40)`.
3. **Teams arbeiten nicht perfekt parallel.** `Summe Arbeit / Team` unterstellt, dass vier Personen
   genau viermal so schnell sind. Abstimmung, Warten an Engstellen und Wege kosten.
   → `Summe Arbeit / Team^beta` mit lernbarem `beta` (Start 0,85; 1 = perfekt parallel).
4. **Kleine Pflanzen werden gemeinsam getragen.** Fünf Töpfe à 5 kg trägt eine Person nicht fünfmal.
   → später: Gewicht unter einer Schwelle zählt anteilig (erst bei genug Messungen sinnvoll).
5. **Fehler wachsen mit der Dauer.** Ein Stopp von 90 Minuten streut stärker als einer von 15.
   Fürs Lernen ist ein relativer Fehler (oder Anpassen auf der Log-Skala) passender als Minuten.
   Die App nutzt Huber-Verlust und Kreuzvalidierung – das bleibt richtig.

## Vorschlag zum Diskutieren (Kandidat „Stufe 3“)

    work     (Pflanze) = h0 + h1 * weight
                         + (a0 + a1 * weight)
                           * (path_length / walk_speed
                              + k_height * height_meters * (1 + k_heavy * max(0, weight - 40) / 40))
                           * narrow_factor * equipment_factor
    duration (Stopp)   = t_fixed + t_plant * n_plants
                         + max(sum_plants(work) / team ^ beta, max_plants(work / crew)) / speed

Parameter (Startwerte): a0 = 5, a1 = 0,07, k_height = 0,45, k_heavy = 0,3, h0 = 1, h1 = 0,02,
t_fixed = 8, t_plant = 0,5, beta = 0,85 – neun Parameter.

## Meine Empfehlung

- **Jetzt:** Stufe 1 lassen, bis mindestens 60 gemessene Stopps vorliegen. Mit wenigen Messungen
  passt jede zusätzliche Größe nur das Rauschen an.
- **Ab ~60 Messungen:** Stufe 2 per Kreuzvalidierung gegen Stufe 1 prüfen (macht die App schon in
  „Modellqualität“).
- **Ab ~150 Messungen, mit Treppen und großen Teams:** den Kandidaten oben in der KI-Diskussion von
  ChatGPT prüfen lassen und nur übernehmen, wenn der Fehler „Vorschlag, Werte angepasst“ in der
  Bewertungstabelle klar (mindestens 5 %) unter dem der aktuellen Formel liegt.
- Der Experimentmodus (bewusst größere Teams bei einem kleinen Teil der Stopps) ist die
  Voraussetzung, damit `beta` überhaupt lernbar ist.

## Fragen an die Runde (zum Einfügen in „Frage an die Runde“)

- „Brauchen wir eine eigene Zeit je Treppenstufe, oder reichen Höhenmeter?“
- „Arbeiten große Teams wirklich parallel? Lohnt sich ein Exponent für die Teamgröße?“
- „Ist die Abladeformel (Fixzeit + je Pflanze + je kg, geteilt durchs Team) gut genug?“
