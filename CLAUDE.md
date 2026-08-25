# CHCKD content pipeline

## What this repo is

CHCKD is an iOS Flutter app for tracking places you've been, built around
curated checklists ("lists") of places — national parks, UNESCO sites,
stadiums, beaches, and so on. This repo is **not the app**. It's the
content pipeline that sources, tags, and curates all of that reference
data — places, lists, tags, and the hierarchies that organize them — into
a DuckDB database. That database is the deliverable; a later project reads
from it to seed the app's real backend (see "Relationship to the app" below).

Think of it as an ETL project with an unusually well-specified source of
truth: `chckd-context/CHCKD-Taxonomy-Lists.xlsx` already contains a 4-level
place-type taxonomy and a 96-row (92 after removing tier-header rows)
tiered list of "lists to build," sourced from the project's own discovery
research. Most of the work here is operationalizing that spreadsheet, not
inventing a schema from scratch.

### Relationship to the app

`chckd-context/chckd-erd.html` is a **separate**, already-designed
Postgres/Supabase schema for the live app (auth, visits, follows, billing,
saved places, etc.). It's the reason a few naming choices here echo it
(`provider`/`external_id`-style dedup, `is_system` on tags, the
Natural/Region/Place split) — staying consistent makes a future
import/export between this DuckDB content store and that Postgres app
database mechanical rather than a translation exercise. But the two
schemas are not the same, and this repo doesn't try to replicate the app's
user-facing tables (visits, profiles, subscriptions, ...) — those belong
to the app, not to content curation.

### Vocabulary

The brand style guide's own footer names a hierarchy ladder: **Collections
| Series | List | Place | Check**. This repo currently implements only
`List` and `Place` — a `list` is a checklist of `places`. The
`Collections`/`Series` browsing layer above lists, and `Check` (a user's
visit), don't exist here: `Check` is app-side, not content-pipeline-side;
`Collections` was built once (a `collections` self-referencing tree +
`collection_lists` join, auto-derived by-tier/by-domain/by-governing-body
facets) and then deliberately pulled back out — see "Collections — removed
for now" below if it's worth reviving.

---

## Data model

All tables live in `src/chckd_lists/db/schema.sql` — that file is the
single source of truth for shape; this section explains the *why*.

### Content tables

| Table | Purpose |
|---|---|
| `places` | One row per real-world place, deduplicated across every list that references it. |
| `lists` | One curated checklist (e.g. "US National Parks"), with tier/governing_body/approx_count carried from the Master List sheet. |
| `place_tags`, `list_tags` | Many-to-many joins onto `place_categories` — see "Tags are place categories, not a separate concept" below. There is no `tags` table. |
| `list_places` | Many-to-many join between `lists` and `places`, with an optional `sort_order` for naturally-ordered lists (e.g. peaks by height). |

### Hierarchy tables

| Table | Purpose |
|---|---|
| `place_categories` | Self-referencing 4-level tree (Collection → Series → Category → Type, e.g. `natural.land.mountains.summit`) — **what kind of place this is**. Seeded from the Taxonomy sheet. |
| `list_categories` | Flat lookup (Regional / Natural / Place) — **what domain a whole list belongs to**. Seeded from the Master List sheet's `Collection` column. |

No `collections`/`collection_lists` browsing layer over lists right now —
see "Collections — removed for now" below.

### Two different "category" concepts — don't conflate them

`place_categories` classifies **places** (natural / place / region, per the
Taxonomy sheet and the app ERD). `list_categories` classifies **lists**
(Regional / Natural / Place, per the Master List sheet's own `Collection`
column). These are different axes over different entities, and the sheet's
own two collection-ish columns don't line up 1:1 — e.g. Master List's
"Place" spans both the Taxonomy sheet's `place` branch and some of
`natural.park.*`. They're kept as two separate, unreconciled tables on
purpose rather than forced into one taxonomy. If a future need arises to
line them up (e.g. for a single "browse by domain" UI), do that mapping in
a view, not by rewriting either source table.

### Collections — removed for now

An earlier iteration had a `collections` self-referencing tree +
`collection_lists` join — a curation/browse hierarchy over `lists`,
distinct from `list_categories` (one flat classification per list):
`collections` was arbitrary-depth and many-to-many, with three facets
fully auto-derived from the Master List sheet (`by-tier`, `by-domain`,
`by-governing-body`) and a fourth (`by-location` → `us` /
`international`) left as an empty skeleton pending manual curation.

That's been pulled out — no `collections`/`collection_lists` tables, no
`registry/collections.yaml`, no `collections:` field on a list's registry
YAML — while the browsing-hierarchy question gets settled properly rather
than carried as a half-derived guess. `tier` and `governing_body` are
still plain columns on `lists` itself (from the Master List sheet), so
that data isn't lost, just not organized into a separate browse tree.
Reviving this means reintroducing: the two tables in `schema.sql`, a
`build_collections`/`_collection_slugs_for`-style generation step in
`seed_from_context.py`, a `load_collections_table` step in
`load_dimensions.py`, and the collection-placement loop in
`pipeline/load.py::upsert_list`.

### Tags are place categories, not a separate concept

There is no `tags` table, and no `registry/tags.yaml`. A "tag" is just a
`place_categories` row: tagging a place or list means pointing it at one
or more taxonomy nodes via `place_tags`/`list_tags`, whose `category_id`
column references `place_categories.id` directly. When a place is
upserted, `pipeline/load.py::taxonomy_ancestor_category_ids` attaches its
*entire* ancestor chain, not just its one leaf category — Mount Everest
(`category_path: natural.land.mountains.summit`) ends up in `place_tags`
against `natural`, `natural.land`, `natural.land.mountains`, and
`natural.land.mountains.summit`, all four. That's what makes tag-based
browsing (the app's "BROWSE BY TAG" chips) work at any level: filter by
the broad `natural` tag, or drill into `mountains`, or go straight to
`summit`, all from the same table.

This wasn't the original design — earlier iterations had `tags` as its
own table, first duplicating the full taxonomy into a second file
(`tags.yaml`, kept "in sync" with `place_taxonomy.yaml` by regeneration),
then even after collapsing that back to one file, still a second *table*
with the same 241 rows re-hashed under a different id scheme. Both were
the same mistake at different layers: tags and place-taxonomy nodes were
never actually two things, so keeping two representations just meant two
places for the same fact to drift apart. Collapsing them means: one file
(`place_taxonomy.yaml`), one table (`place_categories`), and `place_tags`/
`list_tags` are just join tables onto it — nothing else to keep in sync.

A place's or list's `tags:` field in its registry YAML (see
`schemas/models.py::ConformedPlace.tags` / `ConformedList.tags`) holds
*additional* `place_categories.full_path` strings beyond its primary
`category_path` — e.g. a state park that's also on the coast would have
`category_path: natural.park.state_park` and `tags: [natural.water.coastal]`.
Each entry gets the same ancestor-chain expansion as the primary category.
An unrecognized path logs a warning and is skipped, the same way an
unrecognized `category_path` is (see `resolve_category_id`).

Ordering matters here: a place's tag ids are computed by hashing its
category path directly, the same way `place_categories.id` is computed
when the table is loaded — so they're only valid once `chckd-lists seed`
has actually loaded `place_categories`. Always run `seed` before `run`.

### Operational tables

`pipeline_runs` and `table_change_log` exist purely for the "log changes
between runs" requirement — see "Change logging" below.

---

## Design decisions

### ID strategy

Every table's primary key is a `TEXT` id from `chckd_lists.ids.make_id(kind,
natural_key)` — a deterministic `uuid5` hash (e.g. `make_id("place",
"nps:yell")`). Same natural key → same id, always. This makes every insert
in the pipeline an idempotent upsert with no "does this already exist"
lookup: re-running a list is always safe, and ids are stable across
machines and re-seeds.

### Why no foreign key constraints

The schema *looks* relational (every `*_id` column documents what it
logically points to), but none of them are declared as `REFERENCES` in
DDL. This was a deliberate reversal after hitting a real DuckDB
limitation: DuckDB refuses to `UPDATE` **any** column of a row that's
referenced by a FK elsewhere — not just the key column — which breaks
upsert-with-update on every "one" side of a relationship the moment one
child row exists. `places`/`lists`/`place_categories` all get updated on
every re-run (a re-scraped description, a corrected name), so this wasn't
a corner case, it broke the very first end-to-end run. Given DuckDB is a
single-writer analytical engine and every write here goes through this
pipeline's controlled insert order, app-level integrity (deterministic ids
+ fixed load order in `pipeline/load.py` / `pipeline/load_dimensions.py`)
is enough. Revisit this only if the db ever needs to be safely writable by
something other than this pipeline.

### Why no migrations framework

`schema.sql` is applied with plain `CREATE TABLE IF NOT EXISTS` — no
Alembic-style versioned migrations. This is a single-developer content
pipeline where the database is 100% derived from `registry/` +
`chckd-context/` + the source APIs; nothing in it is hand-entered or
irreplaceable. An additive schema change (new table/column) just works on
the next `migrate`. A breaking change to an existing column means: edit
`schema.sql`, delete `data/chckd.duckdb`, and rebuild with `migrate` →
`seed` → `run --all`. That's cheap here specifically because nothing is
one-of-a-kind data — don't port this convention to a project where the db
holds anything that can't be regenerated.

### Upsert conventions

- `places`, `lists`: real upsert (`ON CONFLICT ... DO UPDATE`) — these are
  expected to change on re-extraction (descriptions, coordinates).
- `place_categories`, `list_categories`: `INSERT OR IGNORE` only. These
  are wholesale regenerated from `registry/*.yaml` every `seed` run; a
  renamed node is the one case this misses (fixed by a full db rebuild,
  see above — not worth a special case for something this rare).
- Join tables (`*_tags`, `list_places`): `INSERT OR IGNORE`, append-only
  in practice.

### Change logging

Every table a pipeline run touches gets wrapped in
`chckd_lists.db.diff.TableDiff`, which snapshots row counts before/after
(excluding `updated_at`, which would otherwise make every re-run of an
unchanged row look like a full remove+add) and writes one row to
`table_change_log` plus a log line — `"places: +3 -0 (61 -> 64)"` on a real
change, `"places: no change (64 rows)"` otherwise. One `pipeline_runs` row
wraps each CLI `run` invocation. This is plain SQL set-arithmetic
(`EXCEPT`), not a diffing library — DuckDB is the right tool to do that
arithmetic itself.

### Registry pattern (the "easily add/remove lists" hierarchy)

`registry/lists/tier-<n>/<slug>.yaml` is the unit of "a list," grouped into
`tier-1` (must-have) through `tier-5` (cult following) subfolders — the
same tiers the Master List sheet defines — purely so the directory stays
navigable at 90+ lists; it has no effect on loading. Everything about one
list — its metadata, its tags, and *how* to fetch its places — lives in
one file. Adding a list: drop a new
YAML file under the right tier folder (see "Adding a list" below).
Removing one: delete the file (and drop `data/chckd.duckdb` to actually
clear its rows, or just leave it — harmless if never `run` again). No
plugin registry, no auto-discovery magic —
`pipeline/registry_loader.py::load_all_list_entries` just globs
`tier-*/*.yaml`, and `load_list_entry(slug)` globs `tier-*/<slug>.yaml` so
callers never need to know which tier a slug lives in.

`registry/place_taxonomy.yaml` and `registry/list_categories.yaml` are the
dimension tables' seed data, generated (and safe to regenerate — `seed`
overwrites them wholesale) by `chckd_lists.seed.seed_from_context` from
the xlsx. They're committed to
git as plain YAML specifically so a diff of "what changed in the taxonomy"
is readable in a PR, not buried in binary xlsx diffs. There is no
`tags.yaml` — see "Tags are place categories, not a separate concept"
below.

---

## Repository layout

```
CLAUDE.md                      you are here
README.md                      quickstart + day-to-day usage
pyproject.toml / poetry.lock   deps (poetry), installed into the chckd-lists conda env
environment.yml                conda env spec (python=3.13 only — poetry owns the rest)
.env.example                   template for API keys — copy to .env (gitignored), see README "Setup"
chckd-context/                 source material: taxonomy xlsx, discovery research, brand, app ERD
registry/                      human-editable content — see "Registry pattern" above
  place_taxonomy.yaml          fully regenerated by `seed` — don't hand-edit. Also IS the tag vocabulary — no tags.yaml.
  list_categories.yaml         fully regenerated by `seed` — don't hand-edit
  lists/tier-<1..5>/<slug>.yaml  one file per list, grouped by tier
src/chckd_lists/
  config.py                    all paths, in one place; also loads .env on import
  ids.py                       make_id()
  logging_conf.py              stdlib logging setup (console + rotating file)
  cli.py                       `chckd-lists` entrypoint
  db/
    schema.sql                 source of truth for table shape
    connection.py, migrate.py, diff.py
  schemas/models.py            ConformedPlace / ConformedList (pydantic)
  sources/                     one module per *kind* of source
    base.py                    ListSource ABC
    static.py                  fixed-membership lists (registry YAML holds the data)
    nps.py                     NPS API — narrow, one designation, rich metadata
    protected_planet.py        WDPA API — broad, many designations/countries
  pipeline/
    registry_loader.py         reads registry/*.yaml
    conform.py                 raw dict -> ConformedPlace/ConformedList (validation only)
    load.py                    conformed -> upserts (places/lists/place_tags/list_tags/list_places)
    load_dimensions.py         registry dimension YAML -> place_categories/list_categories
    run.py                     orchestrates one list: extract -> conform -> load, with change logging
  seed/seed_from_context.py    xlsx -> registry/*.yaml generator
data/chckd.duckdb               gitignored, fully regenerable
logs/pipeline.log                gitignored, rotating
tests/
```

---

## Environment setup

Conda owns the interpreter, poetry owns the dependencies — poetry is
configured (`poetry.toml`, committed) to install straight into the active
conda env rather than creating its own nested virtualenv underneath it.

```bash
conda env create -f environment.yml   # creates the chckd-lists env, python 3.13, once
conda activate chckd-lists
poetry install                         # reads pyproject.toml, installs into chckd-lists
```

**API keys go in a `.env` file at the repo root** — `cp .env.example .env`
and fill in `NPS_API_KEY` / `PROTECTED_PLANET_API_KEY`. `.env` is
gitignored; `config.py` calls `load_dotenv(REPO_ROOT / ".env")` as an
import side effect, so every entrypoint (`chckd-lists ...`, `pytest`, a
one-off script) picks the keys up automatically the moment anything
imports `chckd_lists.config` — which every real entrypoint does
transitively (e.g. `cli.py` → `db.connection` → `config`) before any
source's `extract()` runs and calls `os.environ.get(...)`. No manual
`export`/`source` step, and nothing beyond `config.py` needs to know `.env`
exists.

If `poetry env info` ever shows an `Executable` outside
`.../envs/chckd-lists/...` (e.g. after `poetry env use` was run before the
env was created/activated), run `poetry env remove --all` and `poetry
install` again with the conda env active — poetry caches which env it's
bound to per-project and can get stuck pointing at a stray one.

---

## Adding a list

1. Run `chckd-lists list` to see if it already exists as a stub (every row
   from the Master List sheet already has one, via `seed`).
2. Open `registry/lists/tier-<n>/<slug>.yaml`. Decide its source:
   - **Fixed, small membership** (Seven Summits, Five Oceans, ...): set
     `source.type: static` and put the place records directly under
     `source.places:` — see `registry/lists/tier-1/the-seven-summits.yaml`
     for the shape every place needs (matches `ConformedPlace` in
     `schemas/models.py`: `name`, `external_id`, `external_id_source`,
     `category_path`, `lat`/`lng`, etc.).
   - **A US park/protected-area designation** (national parks, state
     parks, wildlife refuges, monuments, ...): `source.type:
     protected_planet` almost always fits — see "Protected Planet source"
     below. `source.type: nps` is a narrower, no-designation-lookup-needed
     alternative for exactly the National Park Service's own "National
     Park" designation.
   - **Anything else API-backed** (UNESCO sites, sports venues, ...): write
     a `ListSource` subclass in `sources/<name>.py` whose `extract()`
     returns dicts already shaped like `ConformedPlace` fields (see
     `sources/nps.py` for the pattern — map the API's field names onto
     ours right there, not in `pipeline/conform.py`, which stays
     source-agnostic). Register it in `SOURCE_TYPES` in `pipeline/run.py`,
     and set `source.type` in the YAML to match its key.
3. Set `status: active` once the source is real and you've verified a run
   against it (leave `stub` otherwise — `run --all` skips anything whose
   `status` isn't `active`, regardless of whether `source.type` is wired
   up, so half-verified sources never silently write rows).
4. `chckd-lists run <slug>`. Check the log line for a place-count mismatch
   against `approx_count` — that's usually a sign the source needs a filter
   tweak, not that the sheet's estimate is wrong.

## Removing a list

Delete `registry/lists/tier-<n>/<slug>.yaml`. Its rows stay in the db until
the next full rebuild (`rm data/chckd.duckdb && chckd-lists migrate &&
chckd-lists seed && chckd-lists run --all`) — fine to leave them if you're
just pausing on a list, since nothing else depends on unlisted rows still
being there.

## Protected Planet source

`sources/protected_planet.py` wraps the WDPA API
(api.protectedplanet.net/documentation) — one source module covers almost
every "US National ___" / "___ Parks" / "___ Reserves" list, since WDPA
tracks each as a "protected area" with a `designation` and country. It's
already wired (`source.type: protected_planet`, `status: stub`) into 19
lists — `us-state-parks`, `us-national-wildlife-refuges`,
`us-national-marine-sanctuaries`, `ramsar-wetland-sites-us`,
`biosphere-reserves-us`, `us-national-forests`, `us-national-grasslands`,
`us-national-preserves`, `us-national-recreation-areas`,
`us-national-lakeshores`, `us-national-seashores`, `us-national-monuments`,
`us-national-natural-landmarks`, `us-national-battlefields`,
`us-national-military-parks`, `us-national-historical-parks`,
`us-national-memorials`, `us-national-historic-sites`, and
`us-national-wild-scenic-rivers` — each with a `source.category_path`
already mapped onto the matching `natural.park.*` taxonomy leaf.

None of these have been run against a live API yet, for two reasons that
have to be resolved per list before flipping `status: active`:

1. **Need a free token.** Request one at `api.protectedplanet.net/request`,
   set `PROTECTED_PLANET_API_KEY`.
2. **`designation` is an integer id, not a name**, and the API doesn't
   publish a fixed id table. Find it once per list: call `/v4/protected_areas/search`
   filtered only by `country`, look at the `designation.id`/`designation.name`
   on a few results for the type you want, then add
   `designation_id: <that id>` to the list's `source.params`.

Every wired-up list's `source.params` currently has only `{country: USA}`
— broad enough to run without erroring, but returning *all* US protected
areas of every designation, not the specific one the list is named for.
Add the `designation_id` before trusting a run's output.

## Running things

```bash
chckd-lists migrate              # apply schema.sql
chckd-lists seed                 # regenerate registry/ from chckd-context/, load dimension tables
chckd-lists list                 # every registered list + its status
chckd-lists run <slug>           # run one list
chckd-lists run --all             # run every list (skips anything not status: active)
```

## Testing

`tests/test_pipeline.py` runs the real pipeline (migrate → load dimensions
→ run a real list → re-run it) against a throwaway DuckDB file in
`tmp_path`, and asserts the change log reports zero rows added on the
idempotent re-run. Run with `pytest` (installed as a poetry dev dependency).

---

## Current status / roadmap

- **Schema, registry pattern, and full pipeline: working**, proven
  end-to-end on `the-seven-summits` (static source → conform → categorize
  → tag with the full taxonomy ancestor chain → load → change-log,
  verified idempotent across 3 runs, including a list-level tag).
- **92 lists stubbed** (now organized into `tier-1`..`tier-5` folders), 1
  implemented (`the-seven-summits`). 20 more (`us-national-parks` +
  the 19 `protected_planet`-wired lists, see "Protected Planet source")
  have a real source module wired up but are still `status: stub` pending
  an API key and, for the WDPA ones, a `designation_id` lookup — everything
  else is still `source.type: unimplemented`. Actually sourcing/verifying
  each remaining list is future work, not part of this foundation pass.
- `sources/nps.py` and `sources/protected_planet.py` show the API-source
  pattern but neither has been run against a live API yet — both need a
  free key (see "Protected Planet source" and `sources/nps.py`'s
  docstring) that this environment doesn't have.
- No browsing hierarchy over lists right now — see "Collections — removed
  for now" above.
- Places have no lat/lng geocoding pass yet beyond what a source provides
  directly — the app ERD's `provider`/`provider_place_id`/`place_boundaries`
  concepts (Google/Mapbox geocoding, PostGIS boundaries for region-type
  places) live on the app side and aren't replicated here. If this content
  db ever needs to feed that directly, that's a separate enrichment step,
  not a change to this schema.
- Known data-quality wrinkle in the source xlsx, not yet cleaned up: one row
  in the Taxonomy sheet labels "Cultural Site" under `place | unesco`,
  interleaved with `natural.unesco`'s "Natural Site" — inconsistent with
  the rest of the sheet's structure. Doesn't break the seed script (it just
  creates the branch as given), but worth fixing at the source next time
  the xlsx is touched.
