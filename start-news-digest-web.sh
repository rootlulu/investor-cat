#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/news-digest-web"
exec ./start-dev.sh "$@"
