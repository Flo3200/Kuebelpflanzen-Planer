# Kübelpflanzen-Planer – Anleitung für KI-Agenten

Diese Plattform plant die Abholung von Kübelpflanzen zur Überwinterung. Du kannst über die
REST-API alles tun, was auch die Oberfläche kann – im Rahmen der Rechte deines Tokens.

## 1. Anmelden (Einwahl)

Ein Mensch hat dir einen Einwahl-Link gegeben, z. B. `http://localhost:8000/agent/enroll/<code>`.
Der Code gilt einmal. Tausche ihn gegen ein Token:

```bash
curl -s -X POST http://localhost:8000/agent/enroll/<code>
```

Antwort (Beispiel):

```json
{"token": "kpa_…", "token_type": "bearer", "scopes": ["drafts"], "expires_at": "…", "tenant": {"id": "…", "name": "…"}}
```

Bewahre das Token sicher auf; es wird nur dieses eine Mal angezeigt.

## 2. Aufrufe

Jeder Aufruf trägt das Token im Header:

```bash
curl -s http://localhost:8000/api/auth/me -H "Authorization: Bearer $TOKEN"
```

Beispiel – eine weitergeleitete Kundennachricht als Entwurf anlegen (Scope `drafts`):

```bash
curl -s -X POST http://localhost:8000/api/drafts \
  -H "Authorization: Bearer $TOKEN" \
  -F "source_kind=agent" \
  -F "text=Hallo, bitte holen Sie im Oktober meinen Oleander ab (ca. 1,8 m, Topf 50 cm). Erika Muster, Gartenweg 3, 70173 Stuttgart" \
  -F "files=@oleander.jpg" -F "kinds=plant_front"
```

Fotos sind freiwillig (`files` und `kinds` beliebig oft). Die KI-Auswertung läuft im Hintergrund;
den Stand liest du mit `GET http://localhost:8000/api/drafts/<id>`.

Ein Entwurf wird erst nach Bestätigung durch einen Menschen zu Kunde, Auftrag und Pflanzen.

## 3. Regeln und Grenzen

- **Rechte (Scopes):** `read` (lesen), `drafts` (Entwürfe anlegen), `masterdata` (Stammdaten pflegen), `planning` (planen), `settings` (Einstellungen ändern), `admin_support` (Admin-Unterstützung), `admin_full` (alles (nur Testbetrieb))
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
- **Fehler** kommen als JSON: `{"error": {"code": "…", "message": "…"}}` (Nachricht auf Deutsch).
- Datumsangaben im Format `JJJJ-MM-TT`, Zeiten als ISO 8601, Beträge in Euro, Maße in cm, Gewichte in kg.
- Ob deine Nutzung mit den Bedingungen deines KI-Anbieters vereinbar ist, prüft dein Betreiber.

Die vollständige technische Beschreibung (OpenAPI): `http://localhost:8000/api/openapi.json`

## 4. Endpunkte

Die Liste wird beim Abruf aus der laufenden API erzeugt.


### access_path

- `DELETE /api/paths/{path_id}` – Delete Path
- `PATCH /api/paths/{path_id}` – Update Path
- `POST /api/orders/{order_id}/paths` – Add Path
- `PUT /api/paths/{path_id}/segments` – Put Segments

### address

- `DELETE /api/addresses/{row_id}` – Delete Address
- `GET /api/addresses/{row_id}` – Get Address
- `GET /api/addresses` – List Address
- `PATCH /api/addresses/{row_id}` – Update Address
- `POST /api/addresses` – Create Address

### agents

- `GET /api/agents/calls` – Call log of the agents.
- `GET /api/agents/confirmations` – Actions of agents waiting for a human.
- `GET /api/agents/meta` – Scopes that can be given and the platform mode.
- `GET /api/agents/tokens` – List Tokens
- `POST /api/agents/confirmations/{conf_id}/decide` – Decide
- `POST /api/agents/links` – Enrolment link with a one-time code for an agent.
- `POST /api/agents/tokens/{token_id}/revoke` – Revoke

### ai

- `DELETE /api/admin/ai/models/{model_id}` – Delete Model
- `DELETE /api/ai/keys/{provider_id}` – Delete Key
- `DELETE /api/ai/prompts/{prompt_id}` – Deactivating a tenant override returns the tenant to the global prompt.
- `GET /api/admin/ai/eval-sets` – Eval Sets
- `GET /api/admin/ai/models` – Admin Models
- `GET /api/admin/ai/providers` – List Providers
- `GET /api/ai/keys` – List Keys
- `GET /api/ai/models` – Available Models
- `GET /api/ai/prompts` – Prompt versions: global (admin) and, for tenants, their own overrides.
- `GET /api/ai/usage` – My Usage
- `PATCH /api/admin/ai/models/{model_id}` – Update Model
- `PATCH /api/admin/ai/providers/{provider_id}` – Update Provider
- `POST /api/admin/ai/eval-sets/{set_id}/items` – Add Eval Item
- `POST /api/admin/ai/eval-sets/{set_id}/run` – Compare several models on a test set (mean error per quantity, cost per evaluation).
- `POST /api/admin/ai/eval-sets` – Create Eval Set
- `POST /api/admin/ai/models` – Create Model
- `POST /api/admin/ai/providers` – Create Provider
- `POST /api/ai/prompts/{prompt_id}/activate` – Activate Prompt
- `POST /api/ai/prompts` – Creates a new active version (admin: global; tenant: override for the tenant).
- `POST /api/orders/{order_id}/photo-analysis` – Order Photo Analysis
- `POST /api/orders/{order_id}/photo-check` – Order Photo Check
- `PUT /api/ai/keys` – Store the tenant's own API key (encrypted). The key is never returned, only its last characters.

### assistant

- `POST /api/assistant/chat` – One answer of the settings AI; changes are made through tools and listed for undo.

### audit

- `GET /api/audit` – List Entries
- `POST /api/audit/batch/{batch_id}/undo` – Undo Batch
- `POST /api/audit/{entry_id}/undo` – Undo

### auth

- `GET /api/auth/me` – Me
- `POST /api/auth/2fa/disable` – Totp Disable
- `POST /api/auth/2fa/enable` – Totp Enable
- `POST /api/auth/2fa/setup` – Totp Setup
- `POST /api/auth/act-as` – Platform admin switches into a tenant (or back to platform view).
- `POST /api/auth/driver/pin` – Driver Pin Login
- `POST /api/auth/link/{code}` – Personal driver link: /fahrer/login/<code> posts here.
- `POST /api/auth/login` – Login
- `POST /api/auth/logout` – Logout
- `POST /api/auth/password` – Change Password

### availability

- `DELETE /api/availability/{row_id}` – Delete Availability
- `GET /api/availability-calendar` – Resolved availability per resource and day (for the calendar view and the planner).
- `GET /api/availability/{row_id}` – Get Availability
- `GET /api/availability` – List Availability
- `PATCH /api/availability/{row_id}` – Update Availability
- `POST /api/availability` – Create Availability

### billing

- `GET /api/billing/invoices/{invoice_id}/pdf` – Invoice Pdf
- `GET /api/billing/invoices` – List Invoices
- `GET /api/billing/usage` – Usage overview of one month (AI, plants) with the invoice preview.
- `POST /api/billing/invoices/{invoice_id}/cancel` – Cancel
- `POST /api/billing/invoices/{invoice_id}/paid` – Mark Paid
- `POST /api/billing/invoices` – Admin: platform invoice for one tenant and month (normally done by the monthly job).
- `POST /api/billing/orders/{order_id}/invoice` – Tenant: invoice to its own customer for an order (optional module of the tenant).
- `POST /api/billing/run-monthly` – Admin: start the monthly invoice run now (for the month before the given one).

### customer

- `DELETE /api/customers/{row_id}` – Delete Customer
- `GET /api/customers/{customer_id}/full` – Customer Full
- `GET /api/customers/{row_id}` – Get Customer
- `GET /api/customers` – List Customer
- `PATCH /api/customers/{row_id}` – Update Customer
- `POST /api/customers` – Create Customer

### dashboard

- `GET /api/dashboard` – Dashboard

### drafts

- `GET /api/drafts/{draft_id}` – Get Draft
- `GET /api/drafts` – List Drafts
- `PATCH /api/drafts/{draft_id}` – Patch Draft
- `POST /api/drafts/{draft_id}/confirm` – Turn the (corrected) draft into customer, address, order, plants and path.
- `POST /api/drafts/{draft_id}/reject` – Reject
- `POST /api/drafts/{draft_id}/reprocess` – Reprocess
- `POST /api/drafts` – Paste or forward a message (text, e-mail content, voice message as text) with photos.

### driver

- `GET /api/driver/day` – Own tours of the active plan for one or more days (everything the app needs offline).
- `GET /api/driver/me` – Me
- `POST /api/driver/deviations` – Report Deviation
- `POST /api/driver/events` – Post Events
- `POST /api/driver/photos` – Photo from the app (pickup proof, damage, path). Sent again after a lost answer: same photo.

### equipment

- `DELETE /api/equipment/{row_id}` – Delete Equipment
- `GET /api/equipment/{row_id}` – Get Equipment
- `GET /api/equipment` – List Equipment
- `PATCH /api/equipment/{row_id}` – Update Equipment
- `POST /api/equipment` – Create Equipment

### estimates

- `GET /api/orders/{order_id}/estimate` – Recompute and return duration, labour time, team size, costs and price of an order.
- `GET /api/orders/{order_id}/quotes` – List Quotes
- `GET /api/pricing/overview` – Price, self cost and cost coverage per order (before planning: estimated drive share).
- `GET /api/weights/calibration` – Proposed calibration factor from plants with a real weighing (least squares through origin).
- `POST /api/estimates/refresh` – Refresh
- `POST /api/orders/{order_id}/quote` – Create a quote with the current estimate and store it as PDF.
- `POST /api/weights/calibration/apply` – Apply Weight Calibration

### field

- `GET /api/deviations` – List Deviations
- `GET /api/measurements` – List Measurements
- `GET /api/orders/{order_id}/labels.pdf` – Order Labels
- `GET /api/tours/{tour_id}/labels.pdf` – Tour Labels
- `PATCH /api/measurements/{measurement_id}` – Patch Measurement
- `POST /api/deviations/{deviation_id}/decide` – Apply: reported values go into plant/path data (estimate recomputed, replanning hint); dismiss: nothing changes.

### files

- `DELETE /api/photos/{photo_id}` – Delete Photo
- `GET /api/files/{file_id}` – Get File
- `GET /api/photos` – List Photos
- `PATCH /api/photos/{photo_id}` – Update Photo
- `POST /api/photos` – Upload Photo

### formulas

- `DELETE /api/formulas/{formula_id}` – Remove a tenant's override: the global formula applies again.
- `GET /api/formulas` – List Formulas
- `POST /api/formulas/test` – Check a formula and evaluate it for one order (or a sample stop) without saving.
- `POST /api/formulas/{formula_id}/activate/{version_id}` – Activate
- `POST /api/formulas/{formula_id}/versions` – New Version

### jobs

- `GET /api/jobs/{job_id}` – Get Job
- `GET /api/jobs` – List Jobs
- `POST /api/jobs/{job_id}/cancel` – Cancel Job

### learning

- `GET /api/learning/fits/{fit_id}` – Fit Detail
- `GET /api/learning/fits` – List Fits
- `POST /api/learning/fits/{fit_id}/adopt` – Adopt Fit
- `POST /api/learning/fits/{fit_id}/discard` – Discard Fit
- `POST /api/learning/fits` – Start Fit
- `POST /api/learning/synthetic` – Synthetic measurements - only for demo tenants (never mixed into real data).

### loading

- `GET /api/tours/{tour_id}/load-plan` – Get Load Plan
- `POST /api/plans/{plan_id}/load-plans` – Pack All
- `POST /api/tours/{tour_id}/load-plan` – Recompute Load Plan

### meta

- `GET /api/health` – Health
- `GET /api/meta/entities/{name}` – Entity Fields
- `GET /api/meta/entities` – Entities

### order

- `DELETE /api/orders/{order_id}` – Delete Order
- `GET /api/orders/{order_id}` – Get Order Detail
- `GET /api/orders` – List Orders
- `PATCH /api/orders/{order_id}` – Update Order
- `POST /api/orders/{order_id}/return` – Spring return: a new order in direction 'return' that reuses plants and paths of the pickup.
- `POST /api/orders` – Create Order

### planning

- `DELETE /api/plans/{plan_id}` – Delete Plan
- `GET /api/plans/{plan_id}/scenarios` – Compare Scenarios
- `GET /api/plans/{plan_id}` – Get Plan
- `GET /api/plans` – List Plans
- `PATCH /api/tour-stops/{stop_id}` – Fix Stop
- `PATCH /api/tours/{tour_id}` – Fix Tour
- `POST /api/plans/{plan_id}/activate` – Activate
- `POST /api/plans/{plan_id}/replan` – Plan again from a date on; earlier days, started tours and fixed parts stay.
- `POST /api/plans/{plan_id}/scenarios` – Run variants of a plan (±person, ±vehicle, ±day, other team size, free combinations).
- `POST /api/plans` – Create Plan
- `POST /api/tour-stops/{stop_id}/move` – Move a stop to another tour/position; times, loads, costs and warnings are recomputed at once.
- `POST /api/tour-stops/{stop_id}/unassign` – Unassign

### plant

- `DELETE /api/plants/{plant_id}` – Delete Plant
- `GET /api/plants/{plant_id}` – Get Plant
- `GET /api/plants` – List Plants
- `PATCH /api/plants/{plant_id}` – Update Plant
- `POST /api/orders/{order_id}/plants` – Add Plant

### privacy

- `GET /api/customers/{customer_id}/export` – All data of a customer as ZIP (data.json, photos, offers, invoices).
- `POST /api/customers/{customer_id}/erase` – Erase the personal data of a customer (invoices stay because of the retention obligation).
- `POST /api/privacy/retention` – Run the automatic deletion of the tenant now (normally daily).

### settings

- `GET /api/settings/registry` – Alle Einstellungen mit Typ, Einheit, Standard, Grenzen, Ebenen und Erklärung.
- `GET /api/settings` – Aufgelöste Werte einer Ebene mit Herkunft („geerbt vom Admin“ usw.).
- `POST /api/settings/reset` – Zurücksetzen: einzelner Wert (key), Gruppe (group), ganzes Objekt/Ebene, ganzer Betrieb (all_scopes).
- `PUT /api/settings` – Put Value

### shelf

- `DELETE /api/shelves/{row_id}` – Delete Shelf
- `GET /api/shelves/{row_id}` – Get Shelf
- `GET /api/shelves` – List Shelf
- `PATCH /api/shelves/{row_id}` – Update Shelf
- `POST /api/shelves` – Create Shelf

### species

- `DELETE /api/species/{species_id}` – Deletes an own species; for an override this resets to the global species.
- `GET /api/species/{species_id}` – Get Species
- `GET /api/species` – List Species
- `PATCH /api/species/{species_id}` – A tenant changing a global species gets its own override row; the global row stays as is.
- `POST /api/species` – Create Species

### staff

- `DELETE /api/staff/{row_id}` – Delete Staff
- `GET /api/staff/{row_id}` – Get Staff
- `GET /api/staff` – List Staff
- `PATCH /api/staff/{row_id}` – Update Staff
- `POST /api/staff` – Create Staff

### storage

- `GET /api/storage/occupancy` – Current occupancy; with order_id the plants of a not yet confirmed order are added (acceptance check).

### storage_area

- `DELETE /api/storage-areas/{row_id}` – Delete Storage Area
- `GET /api/storage-areas/{row_id}` – Get Storage Area
- `GET /api/storage-areas` – List Storage Area
- `PATCH /api/storage-areas/{row_id}` – Update Storage Area
- `POST /api/storage-areas` – Create Storage Area

### team

- `DELETE /api/teams/{row_id}` – Delete Team
- `GET /api/teams/{row_id}` – Get Team
- `GET /api/teams` – List Team
- `PATCH /api/teams/{row_id}` – Update Team
- `POST /api/teams` – Create Team

### tenants

- `DELETE /api/admin/tenants/{tenant_id}` – Admin Delete Tenant
- `DELETE /api/users/{user_id}` – Delete User
- `GET /api/admin/tenants/{tenant_id}/stats` – Admin Tenant Stats
- `GET /api/admin/tenants` – Admin List Tenants
- `GET /api/meta/permissions` – Permissions Meta
- `GET /api/tenant` – Get Own Tenant
- `GET /api/users` – List Users
- `PATCH /api/admin/tenants/{tenant_id}` – Admin Update Tenant
- `PATCH /api/tenant` – Update Own Tenant
- `PATCH /api/users/{user_id}` – Patch User
- `POST /api/admin/tenants` – Admin Create Tenant
- `POST /api/users/{user_id}/driver-link` – Creates a personal login link for the driver app (valid 30 days, usable on several devices).
- `POST /api/users/{user_id}/pin` – Set Pin
- `POST /api/users` – Add User

### vehicle

- `DELETE /api/vehicles/{row_id}` – Delete Vehicle
- `GET /api/vehicles/{row_id}` – Get Vehicle
- `GET /api/vehicles` – List Vehicle
- `PATCH /api/vehicles/{row_id}` – Update Vehicle
- `POST /api/vehicles` – Create Vehicle
- `PUT /api/vehicles/{vehicle_id}/shelves` – Replace all shelves of a vehicle (used by the shelf editor).
