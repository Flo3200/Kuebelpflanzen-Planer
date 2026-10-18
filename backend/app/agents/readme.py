"""/agent/README.md: instructions for AI agents, generated from the running API (always current)."""

from __future__ import annotations

from fastapi import FastAPI

from app.core.permissions import AGENT_SCOPES

INTRO = """# Kübelpflanzen-Planer – Anleitung für KI-Agenten

Diese Plattform plant die Abholung von Kübelpflanzen zur Überwinterung. Du kannst über die
REST-API alles tun, was auch die Oberfläche kann – im Rahmen der Rechte deines Tokens.

## 1. Anmelden (Einwahl)

Ein Mensch hat dir einen Einwahl-Link gegeben, z. B. `{base}/agent/enroll/<code>`.
Der Code gilt einmal. Tausche ihn gegen ein Token:

```bash
curl -s -X POST {base}/agent/enroll/<code>
```

Antwort (Beispiel):

```json
{{"token": "kpa_…", "token_type": "bearer", "scopes": ["drafts"], "expires_at": "…", "tenant": {{"id": "…", "name": "…"}}}}
```

Bewahre das Token sicher auf; es wird nur dieses eine Mal angezeigt.

## 2. Aufrufe

Jeder Aufruf trägt das Token im Header:

```bash
curl -s {base}/api/auth/me -H "Authorization: Bearer $TOKEN"
```

Beispiel – eine weitergeleitete Kundennachricht als Entwurf anlegen (Scope `drafts`):

```bash
curl -s -X POST {base}/api/drafts \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "source_kind=agent" \\
  -F "text=Hallo, bitte holen Sie im Oktober meinen Oleander ab (ca. 1,8 m, Topf 50 cm). Erika Muster, Gartenweg 3, 70173 Stuttgart" \\
  -F "files=@oleander.jpg" -F "kinds=plant_front"
```

Fotos sind freiwillig (`files` und `kinds` beliebig oft). Die KI-Auswertung läuft im Hintergrund;
den Stand liest du mit `GET {base}/api/drafts/<id>`.

Ein Entwurf wird erst nach Bestätigung durch einen Menschen zu Kunde, Auftrag und Pflanzen.

## 3. Regeln und Grenzen

- **Rechte (Scopes):** {scopes}
- **Ratenbegrenzung:** Bei zu vielen Aufrufen pro Minute antwortet der Server mit 429. Warte dann
  und versuche es erneut.
- **Bestätigungspflicht:** Löschende oder abrechnungsrelevante Aktionen führt der Server nicht
  sofort aus. Er antwortet mit 202, Fehlercode `errors.needs_confirmation` und
  `error.params.confirmation_id`.
  Ein Mensch bestätigt in der Oberfläche. Danach sendest du **genau dieselbe Anfrage** noch einmal
  mit dem Header `X-KP-Confirmation: <confirmation_id>`. Eine Bestätigung gilt einmal.
- **Protokoll:** Jeder Aufruf wird mit Zeit, Pfad und Ergebnis gespeichert. Änderungen erscheinen
  im Änderungsprotokoll mit der Quelle „Agent“.
- **Admin-Agenten:** Im Testbetrieb dürfen sie alles, was das Admin-Konto darf; mit dem Header
  `X-KP-Tenant: <betriebs-id>` arbeiten sie in einem Betrieb. Im **Produktivbetrieb** sind sie auf
  „Admin-Unterstützung“ beschränkt und dürfen **keine Aufgaben für Betriebe** ausführen – der
  Server lehnt solche Aufrufe ab (403 `errors.production_admin_agent`).
- **Fehler** kommen als JSON: `{{"error": {{"code": "…", "message": "…"}}}}` (Nachricht auf Deutsch).
- Datumsangaben im Format `JJJJ-MM-TT`, Zeiten als ISO 8601, Beträge in Euro, Maße in cm, Gewichte in kg.
- Ob deine Nutzung mit den Bedingungen deines KI-Anbieters vereinbar ist, prüft dein Betreiber.

Die vollständige technische Beschreibung (OpenAPI): `{base}/api/openapi.json`

## 4. Endpunkte

Die Liste wird beim Abruf aus der laufenden API erzeugt.
"""


def scope_text() -> str:
    labels = {
        "read": "lesen",
        "drafts": "Entwürfe anlegen",
        "masterdata": "Stammdaten pflegen",
        "planning": "planen",
        "settings": "Einstellungen ändern",
        "admin_support": "Admin-Unterstützung",
        "admin_full": "alles (nur Testbetrieb)",
    }
    return ", ".join(f"`{k}` ({labels.get(k, k)})" for k in AGENT_SCOPES)


def render(app: FastAPI, base: str) -> str:
    """Endpoint list from the OpenAPI schema of the running app (always matches the API)."""
    spec = app.openapi()
    groups: dict[str, list[str]] = {}
    for path, ops in spec.get("paths", {}).items():
        if not path.startswith("/api/"):
            continue
        for method, op in ops.items():
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            tag = (op.get("tags") or ["allgemein"])[0]
            desc = (op.get("description") or "").strip().splitlines()
            summary = desc[0] if desc else op.get("summary", "")
            groups.setdefault(str(tag), []).append(f"- `{method.upper()} {path}` – {summary}")
    out = [INTRO.format(base=base, scopes=scope_text())]
    for tag in sorted(groups):
        out.append(f"\n### {tag}\n")
        out.extend(sorted(set(groups[tag])))
    return "\n".join(out) + "\n"
