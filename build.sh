#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

# Sync real IHC equipment (Chillers, VFD, Transformers, Gensets, etc.) to the
# production database. This is idempotent and DATA-SAFE: it only creates/updates
# equipment definitions and their parameter templates. It NEVER deletes LogEntry
# or LogReading rows, so all previously submitted worker logs are preserved.
python setup_real_data.py

# NOTE: The database schema is created automatically by db.create_all()
# inside create_app() on first boot (see app/__init__.py). The model already
# declares the uq_worker_equip_datetime constraint, so running
# `flask db upgrade` here on a fresh Postgres DB would try to add that same
# constraint a second time and fail. Schema changes are therefore handled by
# create_all(), not Alembic, for this MVP.
