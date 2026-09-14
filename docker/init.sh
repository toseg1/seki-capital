#!/bin/bash
# ---------------------------------------------------------------------------
# Runs once, the first time the Postgres container initialises its data
# directory. Builds the schema, loads the CSVs and runs the data quality
# checks. There are no pre-built views - trainees write the SQL themselves
# in Metabase.
#
# The repo is mounted at /project, so the relative paths below are identical
# to the ones you would use running psql from the repo root on the host.
# ---------------------------------------------------------------------------
set -euo pipefail

cd /project

# The CSVs are generated, not committed, so a fresh clone has an empty data/.
# Fail here with an instruction rather than an opaque \copy error halfway
# through the load, leaving a half-initialised volume behind.
if [ ! -f data/trades.csv ]; then
    echo ""
    echo "ERROR: data/ has no CSVs - they are generated, not committed."
    echo ""
    echo "  Run this on the host first, then recreate the volume:"
    echo ""
    echo "      python3 generate_data.py"
    echo "      docker compose down -v && docker compose up -d"
    echo ""
    exit 1
fi

run() {
    echo ""
    echo ">>> $1"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$1"
}

run sql/01_schema.sql
run sql/02_load.sql
run sql/03_checks.sql

echo ""
echo ">>> Seki Capital is ready."
