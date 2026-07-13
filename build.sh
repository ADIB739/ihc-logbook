#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

# NOTE: Equipment sync (setup_real_data.py) is intentionally NOT run here.
# The build environment cannot reach the runtime Postgres database, so a DB
# write here would silently hit the SQLite fallback in a throwaway container.
# Instead it runs at startup via the Procfile web command, where DATABASE_URL
# and the real Postgres connection are available.

# NOTE: The database schema is created automatically by db.create_all()
# inside create_app() on first boot (see app/__init__.py). The model already
# declares the uq_worker_equip_datetime constraint, so running
# `flask db upgrade` here on a fresh Postgres DB would try to add that same
# constraint a second time and fail. Schema changes are therefore handled by
# create_all(), not Alembic, for this MVP.
