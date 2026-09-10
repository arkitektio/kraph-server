#!/bin/bash
# Abort on the first failing step. Without this the boot ran `ensureadmin` — a
# management command that is not installed — on every start, printed the error,
# and carried on to serve traffic. A boot script that continues past a failed
# migration is a boot script that cannot tell you the deploy is broken.
set -euo pipefail

# Validate the configuration before touching anything: needs no database, and a
# missing secret or a malformed block is reported field by field instead of as a
# traceback from the first import of settings.
echo "=> Validating configuration"
python manage.py validate_settings

echo "=> Waiting for DB to be online"
python manage.py wait_for_database -s 2

# Django's deployment checklist. Fails the boot on errors; warnings (debug on,
# insecure cookies) are printed so the log says what this deployment chose.
echo "=> Deployment checks"
python manage.py check --deploy

echo "=> Performing database migrations..."
python manage.py migrate

# Start the first process
echo "=> Starting Server"
daphne -b 0.0.0.0 -p 80 --websocket_timeout -1 kraph_server.asgi:application 