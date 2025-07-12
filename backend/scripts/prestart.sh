#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python kiwi/backend_pre_start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python kiwi/initial_data.py
