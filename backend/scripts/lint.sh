#!/usr/bin/env bash

set -e
set -x

mypy kiwi
ruff check kiwi
ruff format kiwi --check
