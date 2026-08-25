"""Repo-wide paths. No env-var indirection, no settings framework — this is a
single-environment pipeline, so plain constants are enough. If that stops
being true (e.g. a staging vs prod DuckDB file), revisit then.

The one thing that *does* come from the environment is API keys
(NPS_API_KEY, PROTECTED_PLANET_API_KEY, ...) — those are read directly with
os.environ.get() in each sources/*.py module, not routed through this file.
Loading .env here (once, as an import side effect) is what makes a key
dropped in the repo-root .env file show up in os.environ for them without
every entrypoint remembering to load it — see .env.example.
"""

from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(REPO_ROOT / ".env")

CONTEXT_DIR = REPO_ROOT / "chckd-context"
REGISTRY_DIR = REPO_ROOT / "registry"
LISTS_REGISTRY_DIR = REGISTRY_DIR / "lists"
PLACE_TAXONOMY_YAML = REGISTRY_DIR / "place_taxonomy.yaml"  # also the tag vocabulary — see CLAUDE.md
LIST_CATEGORIES_YAML = REGISTRY_DIR / "list_categories.yaml"

DATA_DIR = REPO_ROOT / "data"
DB_PATH = DATA_DIR / "chckd.duckdb"

LOGS_DIR = REPO_ROOT / "logs"

TAXONOMY_XLSX = CONTEXT_DIR / "CHCKD-Taxonomy-Lists.xlsx"
