#!/bin/sh
# nightly: one native dump per database, uploaded; the restore drill reads the newest dump
pg_dump --format=custom "$DATABASE" | gsutil cp - "gs://backups/$DATABASE/$(date +%F).dump"
