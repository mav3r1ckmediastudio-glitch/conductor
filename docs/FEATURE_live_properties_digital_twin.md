# Feature Spec — Live Properties Layer & Digital Twin

*Status: draft / backlog · Conductor FTTP plugin · captured 14 Jun 2026*

## Goal

Turn the design GeoPackage into a **living as-built record (digital twin)**: a
`live_properties` layer that tracks every premises through its lifecycle
(designed → built → ready-for-service → live) and, once construction is
complete, becomes the authoritative spatial record of the network — queryable by
address, UPRN, ONT, or serving infrastructure.

The trace engine that already exists (`validate_routes.trace_premises`) is
effectively the digital-twin query engine. What's missing is a **persisted
status layer** and a way to **keep it current** from build data.

## The `live_properties` layer

A point layer (one feature per premises, keyed on UPRN), styled RAG by status.

### Attribute schema (proposed)

**Identity & location**
- `property_id` — internal Conductor/operator ID number
- `uprn` — UPRN (join key to everything)
- `address` / `postcode`

**Network / as-built**
- `status` — `DESIGNED | BUILT | RFS | LIVE` (RAG-styled)
- `serving_cabinet` / `serving_splitter` / `serving_joint` — derived from trace
- `tube` / `fibre` — fibre position (IEC 60794, from `fibre_assignments`)
- `drop_id` / `bundle_id` — physical drop reference
- `as_built_date` — when the drop/connection was physically completed
- `rfs_date` — ready-for-service date

**Equipment (from cloud platform)**
- `router_id`
- `ont_id`

**Customer (PII — see Data Protection below)**
- `customer_name`
- `customer_phone`
- `customer_email`
- `connection_date`

## Data sources & ingestion

Three sources feed the layer:

1. **Derived internally** — `status`, serving cabinet/splitter/joint, tube/fibre,
   drop/bundle references. Computed by the existing trace engine; no external
   data needed.
2. **Spreadsheet import** — operator exports a CSV/XLSX from the cloud platform
   (router ID, ONT ID, customer details, connection dates). A new importer maps
   spreadsheet columns → attributes, joined on UPRN. This is the first/MVP path
   and reuses the pattern already in `import_premises.py`.
3. **API integration (future)** — pull the same data live from the cloud
   platform instead of a manual export. *Open question: which platform, and does
   it expose a (free) REST API?* See open questions.

### "Refresh Live Status" tool
A single button that:
1. Re-runs the trace across all premises → updates `status` + serving infra.
2. Merges the latest spreadsheet/API data by UPRN → updates equipment + customer
   fields + dates.
3. Writes results back to `live_properties` and refreshes the RAG styling.

So the layer is a living record that you re-run as the build progresses, not a
one-off snapshot.

## Data protection (important)

`customer_name / phone / email` are **personal data under UK GDPR**. They should
**not** live in the shared design GeoPackage or anything committed to the git
repo. Recommended pattern:

- Keep PII in a **separate, access-controlled table/layer** (e.g. its own
  GeoPackage or a restricted DB), keyed on UPRN.
- The `live_properties` design layer holds only non-PII operational fields
  (status, ONT, router, dates); customer contact is **joined on demand** for
  staff who need it.
- Ensure the customer table is in `.gitignore` and never pushed to GitHub.
- Consider a data-retention / minimisation note (only store what's needed, for as
  long as needed).

This keeps the digital twin useful without turning the repo into a customer
database.

## What it enables (digital twin)

Post-construction, the same project answers:
- "Is this address live? When was it connected? Which ONT/router?"
- "Which premises does cabinet/splitter X serve, and how many are live vs RFS?"
- "Trace the full fibre path for this UPRN" (already works via fibre trace).
- Build-progress dashboards: % live per build area, RAG map of the network
  coming alive.

## How the API makes it "live" (plain English)

QGIS knows the *design*; **SMx** knows what's actually lit on the network (ONTs,
subscribers, who's connected). An API is just a doorway between the two. Instead
of exporting a spreadsheet by hand, the plugin "phones" SMx, asks for the current
ONT/subscriber status, and gets structured data back. The shared key — **UPRN
(and/or ONT ID)** — lets the plugin match each SMx record to the right property
on the map, then stamp it with live status/ONT/router/dates and re-colour it.
Press **Refresh** (or schedule nightly) and the map re-syncs from the live
network — that's what makes it a living digital twin rather than a static design.

Loop: authenticate (Basic Auth, on-prem) → request ONT/subscriber/service data →
match by ONT ID/serial (or UPRN if stored in SMx) → write to `live_properties` →
re-style → repeat on demand/schedule.

## SMx API — findings (June 2026)

The platform is **Calix SMx**. Good news: SMx **ships with a built-in REST API**,
so no third-party API is needed. Two surfaces:

- **SMx Northbound API (on-prem, recommended)** — built into SMx, interactive
  Swagger at `https://<your-SMx-FQDN>:18443/rest/v1/smx/doc` (default API port
  `18443`). Directly exposes ONTs, subscribers, and services — the ONT↔subscriber
  mapping the live layer needs.
- **Calix Cloud Subscriber/Device API** — cloud-side, OAuth 2.0 via the Calix
  Cloud developer portal (per-org app registration + tokens); public Postman
  collection available.

**Auth (corrected from the 158-page SMx APIDoc):** the on-prem **Northbound API
uses HTTP Basic Auth** (username + password) over HTTPS on port 18443 — *not*
OAuth. OAuth 2.0 applies only to the **Calix Cloud** API. Basic Auth is much
simpler to implement in the plugin.

"Free": the Northbound API is *included* with SMx (it's the integration
interface), not a separate purchase.

### Key endpoints / fields (from the APIDoc)
- **`GET /rest/v1/ems/service?device-name=…&ont-id=…`** — the core call. Returns
  per connection: `device-name`, `ont-id`, `ont-port-id`, `service-name`,
  **`admin-status`** (e.g. `active` = provisioned/live), **`subscriber-id`**
  (e.g. `CUST1234`). Can query all services on an ONT, a port, or by template.
- ONT config/status: `…/config/device/{device-name}/ont…`, `…/ontport…`
- Operational/up state: `GET /performance/device/{device-name}/ont/{ont-id}/port/…`
- Subscriber/account: `…/ems/subscriber…`
- Network is **device-scoped** → to sweep everything, loop OLTs → ONTs → services.

### The join key (the important design decision)
SMx has **no concept of UPRN** (0 mentions in 158 pages). It identifies by
**OLT `device-name` + `ont-id`**, and links service → **`subscriber-id`**. To tie
SMx's live data to the map you need a shared key — two realistic options:

1. **Join on ONT ID / ONT serial number** — captured at install and stamped on
   the premises (`ont_id` field). Robust; needs install-time capture.
2. **Store UPRN in SMx** — the API exposes `custom` / `external` / `reference`
   fields on subscribers. If provisioning writes the UPRN (or `property_id`) into
   one of those, you get a direct UPRN→SMx join with no install capture.

`live` status = service `admin-status = active` (+ ONT performance/oper-up for
actually-online). **Decide the join key before building the connector** — it also
dictates what must be captured at install or set during provisioning.

**To confirm with Calix account team / partner portal:** that your contract +
SMx version has the Northbound API enabled, and (for the Cloud API only)
developer-portal access for OAuth; plus any per-endpoint licensing.

Reference links:
- Getting Started with the SMx API Interface (R22.x): https://www.calix.com/content/dam/calix/mycalix-misc/lib/iae/sm/22x/smx-api/99808.htm
- Connecting an API Client to SMx: https://www.calix.com/content/dam/calix/mycalix-misc/lib/iae/sm/22x/smx-api/86499.htm
- Accessing the Northbound APIDoc (Swagger): https://www.calix.com/content/dam/calix/mycalix-misc/lib/iae/sm/21x/smx-api/88973.htm
- Calix Cloud Subscriber/Device API (Postman): https://documenter.getpostman.com/view/3367549/S1TN7M75
- Map SMx/CMS-Managed ONTs to Subscribers: https://www.calix.com/content/dam/calix/mycalix-misc/lib/cloud/help/coc/113403.htm

## Open questions
1. **Join key (decide first)** — ONT ID/serial captured at install, or UPRN stored
   in an SMx subscriber custom/external field at provisioning? This dictates
   install/provisioning process, not just code.
2. **SMx API enablement** — confirm the Northbound API is enabled on your SMx and
   get an API service-account (Basic Auth) credential. (Spreadsheet import remains
   the MVP until then.)
2. **`property_id` scheme** — format/source of the internal ID number, and is it
   1:1 with UPRN?
3. **Status definitions** — exact rules for BUILT vs RFS vs LIVE (which records
   /dates flip each transition).
4. New standalone layer vs. status fields added to the existing `premises` layer.

## Rough build order (when picked up)
1. Add `live_properties` layer + schema to the project template / `project_manager`.
2. Status-derivation pass reusing the trace engine ("Refresh Live Status").
3. Spreadsheet importer (UPRN join), mapping columns → attributes.
4. RAG symbology + labelling.
5. (Later) API connector to replace the manual export.
6. Separate PII handling for customer contact fields.
