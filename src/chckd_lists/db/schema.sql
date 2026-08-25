-- CHCKD content-pipeline schema (DuckDB)
--
-- This is the single source of truth for table shape. It is applied by
-- `chckd_lists.db.migrate` and is intentionally plain, idempotent DDL
-- (CREATE TABLE IF NOT EXISTS) rather than a migrations framework — see
-- CLAUDE.md "Why no migrations framework" for the reasoning.
--
-- Naming: every table uses a TEXT primary key produced by
-- chckd_lists.ids.make_id(), a deterministic hash of a natural key
-- (e.g. "place:nps:yell"). This makes re-running the pipeline idempotent
-- (upsert by id) without a lookup round-trip, and keeps ids stable across
-- machines/runs. See CLAUDE.md "ID strategy".
--
-- No FOREIGN KEY constraints: DuckDB refuses to UPDATE any row that a FK
-- elsewhere points at (not just on PK change — ANY update), which breaks
-- upsert-with-update on every "one" side of a relationship the moment a
-- child row exists (hit this firsthand on lists/places/place_categories).
-- Columns named *_id below are logical references — the pipeline (fixed
-- insert order, deterministic ids) is what keeps them consistent, not the
-- database. See CLAUDE.md "Why no foreign key constraints".


-- ============================================================================
-- Hierarchy: PLACE taxonomy (what kind of place is this?) — and also the
-- entire tag vocabulary. There is no separate `tags` table: a "tag" IS a
-- place_categories node, full stop (see CLAUDE.md "Tags are place
-- categories, not a separate concept"). place_tags/list_tags below
-- reference this table directly.
--
-- Self-referencing tree seeded from chckd-context/CHCKD-Taxonomy-Lists.xlsx,
-- sheet "Taxonomy". Levels: 0=Collection (natural/place/region),
-- 1=Series, 2=Category, 3=Type. A place points at its most specific known
-- node via places.category_id (its ONE structural classification) —
-- place_tags is how it additionally gets every ancestor of that node,
-- plus any other node someone decides applies to it.
--
-- name is NOT unique — the taxonomy legitimately reuses display names
-- across branches (e.g. "Monument" is both a flat NPS designation under
-- natural.park and a structure type under place.structure.monument).
-- full_path is: it's the dotted path, e.g. "natural.land.mountains.summit".
-- ============================================================================
CREATE TABLE IF NOT EXISTS place_categories (
    id          TEXT PRIMARY KEY,
    parent_id   TEXT,                     -- logical FK -> place_categories.id
    level       INTEGER NOT NULL,          -- 0=Collection, 1=Series, 2=Category, 3=Type
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    full_path   TEXT NOT NULL UNIQUE,      -- e.g. "natural.land.mountains.summit"
    created_at  TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- ============================================================================
-- Hierarchy: LIST category (what domain does this whole list belong to?)
-- Flat-ish lookup, one per list. Seeded from the Master List sheet's
-- "Collection" column (Regional / Natural / Place). NOTE: this is a
-- different, looser 3-way split than place_categories' natural/place/region
-- — it classifies the *list*, not each place in it. See CLAUDE.md
-- "Two different 'category' concepts" for why these are not reconciled.
-- ============================================================================
CREATE TABLE IF NOT EXISTS list_categories (
    id          TEXT PRIMARY KEY,
    parent_id   TEXT,                     -- logical FK -> list_categories.id
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- ============================================================================
-- Places: one row per real-world place, deduplicated across all lists that
-- reference it. external_id + external_id_source identify the place in its
-- authoritative source system (NPS parkCode, UNESCO id, Wikidata QID, ...)
-- and are unique together — this is the dedup key when the same place shows
-- up via two different lists/sources.
-- ============================================================================
CREATE TABLE IF NOT EXISTS places (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    category_id         TEXT,             -- logical FK -> place_categories.id
    external_id         TEXT NOT NULL,
    external_id_source  TEXT NOT NULL,    -- e.g. "nps", "unesco", "wikidata", "manual"
    lat                 DOUBLE,
    lng                 DOUBLE,
    formatted_address   TEXT,
    locality            TEXT,
    admin_area_1        TEXT,             -- state / province
    admin_area_2        TEXT,             -- county / district
    country_code        TEXT,
    description         TEXT,
    source_url          TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at          TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (external_id_source, external_id)
);

-- "Tagging" a place = pointing it at a place_categories node beyond its one
-- structural category_id — every ancestor of that primary category, plus
-- (optionally) any other node someone decides applies. See the
-- place_categories comment above.
CREATE TABLE IF NOT EXISTS place_tags (
    place_id    TEXT NOT NULL,            -- logical FK -> places.id
    category_id TEXT NOT NULL,            -- logical FK -> place_categories.id
    created_at  TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (place_id, category_id)
);

-- ============================================================================
-- Lists: one curated checklist (e.g. "US National Parks"). tier/approx_count/
-- dimension/governing_body are carried straight from the Master List sheet —
-- approx_count is the sheet's *expected* count, useful to sanity-check the
-- actual extracted place count against.
-- ============================================================================
CREATE TABLE IF NOT EXISTS lists (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    description     TEXT,
    category_id     TEXT,                -- logical FK -> list_categories.id
    tier            INTEGER,              -- 1 (must-have) .. 5 (cult following), from Master List sheet
    governing_body  TEXT,
    dimension       TEXT,                 -- e.g. "World / Continent / Year", "State" — optional scoping facet
    approx_count    INTEGER,              -- expected place count per the source sheet
    status          TEXT NOT NULL DEFAULT 'stub', -- stub | active | deprecated — see registry/lists/*.yaml
    source_url      TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT current_timestamp,
    updated_at      TIMESTAMP NOT NULL DEFAULT current_timestamp
);

-- Same idea as place_tags, one level up: a list can be associated with any
-- number of place_categories nodes (e.g. "US National Parks" tagged
-- natural.park.national_park), independent of list_categories (which
-- classifies the list's overall domain, not its place-type affinity).
CREATE TABLE IF NOT EXISTS list_tags (
    list_id     TEXT NOT NULL,            -- logical FK -> lists.id
    category_id TEXT NOT NULL,            -- logical FK -> place_categories.id
    created_at  TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (list_id, category_id)
);

CREATE TABLE IF NOT EXISTS list_places (
    list_id     TEXT NOT NULL,            -- logical FK -> lists.id
    place_id    TEXT NOT NULL,            -- logical FK -> places.id
    sort_order  INTEGER,                  -- optional, for naturally ordered lists (e.g. peaks by height)
    added_at    TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (list_id, place_id)
);

-- ============================================================================
-- Operational: per-run change logging (see CLAUDE.md "Change logging").
-- One pipeline_runs row per invocation of the CLI's `run` command; one
-- table_change_log row per content table touched during that run.
-- ============================================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id          TEXT PRIMARY KEY,
    source_slug TEXT NOT NULL,            -- which registry/lists/*.yaml this run was for, or "all"
    started_at  TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status      TEXT NOT NULL DEFAULT 'running', -- running | success | failed
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS table_change_log (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,           -- logical FK -> pipeline_runs.id
    table_name   TEXT NOT NULL,
    rows_before  INTEGER NOT NULL,
    rows_after   INTEGER NOT NULL,
    rows_added   INTEGER NOT NULL,
    rows_removed INTEGER NOT NULL,
    rows_updated INTEGER NOT NULL,
    logged_at    TIMESTAMP NOT NULL DEFAULT current_timestamp
);
