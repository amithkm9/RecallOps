# Verified data contract

Verified on 2026-10-22 using real HTTP responses from the Ministry of Economy Explore API.

- [Official dataset catalog](https://www.data.gouv.fr/datasets/rappelconso-v2-produits-tries-par-gtin)
- [RappelConso public-data description](https://rappel.conso.gouv.fr/support/open-data)
- Endpoint: `https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/rappelconso-v2-gtin-trie/records`
- Dataset: `rappelconso-v2-gtin-trie`
- Attribution: RappelConso / DGCCRF, distributed by Ministères économiques et financiers. The dataset catalog specifies Licence Ouverte / Open Licence 2.0. Keep source attribution, dates and links with reused data; consult the publisher's linked terms for redistribution requirements.

This GTIN-indexed dataset excludes products without GTIN and does not include all RappelConso recalls. Publication and update schedules belong to the publisher. Do not market polling as a continuous government feed.

## Fields verified in responses

| Official field | Stored meaning |
|---|---|
| `id`, `rappel_guid`, `numero_fiche` | Stable ID, publisher GUID, public reference |
| `numero_version` | Official version string |
| `date_publication` | Official publication timestamp |
| `libelle`, `marque_produit`, `categorie_produit` | Product, brand, category |
| `identification_produits` | Product/lot/date tuples |
| `gtin` | Row projection, sometimes a JSON integer; encoded identifiers are preferred |
| `motif_rappel`, `risques_encourus` | Official reason and risk |
| `lien_vers_la_fiche_rappel` | Official source URL |
| Remaining fields | Preserved without modification in raw JSON |

The observed API records did not provide a distinct source-modification timestamp. `source_updated_at` remains null when unavailable. Never replace it with ingestion time. Application ingestion time and last successful live refresh are stored separately.

## Parser contract

Observed tuple format:

```text
GTIN$lot$date type$start date$end date|GTIN$lot$date type$start date$end date
```

Parse each tuple independently; do not mix one GTIN's lot or date with another. Preserve leading zeros and raw strings. Float/scientific-notation identifiers are rejected. Matching uses zero-padding to the GTIN-14 comparison form while retaining the supplied identifier. Exact lot codes, explicit all-lots declarations, semicolon/comma lists, and ISO expiry intervals are supported. Missing lot information, unsupported prose/ranges, invalid dates and malformed scope trigger review.

A recall may appear in multiple GTIN-indexed rows with the same complete scope. Content hashing excludes only the top-level GTIN projection. Stable source ID plus content hash deduplicates versions; a genuine changed record creates another immutable version. Older snapshot imports cannot downgrade a higher official version.

## Snapshot and example

`data/fixtures/official_snapshot.json` contains four unmodified official API records. `provenance.json` records retrieval time, query, license attribution, SHA-256 and scenario ID. The demonstration uses source ID `17010`, reference `2024-12-0201`, smoked salmon, GTIN `3760099533007`, lot `24326020`, use-by `2024-12-20`. Source publication is `2024-12-27T15:06:58+00:00`.

Inventory: **18 units of SAFE-DEMO-LOT and 24 unknown-lot units are fictional.** Later warehouse and supplier events are also fictional. They are stored as separate evidence, never as changes to official source content.

Live import was exercised successfully: 1,000 rows yielded 518 new versions and 482 duplicate skips; the four archived fixture recalls were already stored. Revalidation details are recorded in `data-verification.json`.

## Operational workflow

1. Fetch bounded latest records and tracked live identifiers; validate the response shape.
2. Preserve raw record, source link and publication timestamp.
3. Parse conservative targets; retain warnings for human review.
4. Deduplicate and create immutable versions.
5. Find matching active-store GTINs and existing incidents affected by changed versions.
6. Commit investigation events in the PostgreSQL outbox.
7. Execute the same investigation graph used by the replay.
8. Record refresh outcome. On API failure, label fixture fallback and preserve the previous successful-live timestamp.

Remaining data work: broader independently reviewed scope corpus; supplementary document retrieval; supplier-evidence upload/connector for live use; backfill/checkpoint strategy for large catalogs; checksums for corrupted but correctly shaped GTINs; deletion/withdrawal handling; explicit ingestion-run history and per-record quarantine UI. Missing source records must never automatically release a protective hold.
