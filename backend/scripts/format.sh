#!/bin/sh -e
set -x

ruff check kiwi scripts --fix
ruff format kiwi scripts
