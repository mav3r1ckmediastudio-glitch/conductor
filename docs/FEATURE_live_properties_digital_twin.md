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

## Open questions
1. **Cloud platform & API** — which platform holds router/ONT/customer data, and
   does it offer a free/REST API? (Determines whether step 3 is feasible, and
   what auth it needs.) Until then, spreadsheet import is the path.
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
