#!/bin/bash
# The convergence runner — the second process of a kraph deployment.
#
# Every write draws inside its request; this process is the backstop that
# finishes a drawing the request could not (the write reported `pending`), by
# applying the outbox every few seconds. No `migrate` here: the web process
# (`run.sh`) owns the schema, and two migraters race. If this starts before the
# first migration has run, the first pass fails, is logged, and is retried.
set -euo pipefail

echo "=> Validating configuration"
python manage.py validate_settings

echo "=> Waiting for DB to be online"
python manage.py wait_for_database -s 2

echo "=> Starting the convergence runner"
exec python manage.py reproject --incremental --all --loop --interval "${KRAPH_REPROJECT_INTERVAL:-30}"
