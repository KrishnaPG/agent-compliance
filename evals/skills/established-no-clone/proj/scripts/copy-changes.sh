#!/bin/sh
# Copies rows changed since the last run from the source database to the replica, once a minute.
while true; do
  psql "$SOURCE_URL" -c "\copy (SELECT * FROM orders WHERE updated_at > now() - interval '1 minute') TO STDOUT" |
    psql "$REPLICA_URL" -c "\copy orders FROM STDIN"
  sleep 60
done
