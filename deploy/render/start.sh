#!/bin/sh
set -eu
python manage.py migrate --noinput
python manage.py seed_demo
python manage.py collectstatic --noinput --verbosity 0
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile -
