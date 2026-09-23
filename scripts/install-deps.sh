#!/usr/bin/env bash
# Install dependencies from pyproject.toml without installing the project.
#
# Installing it would drop an egg-info directory into the tree, and nothing
# needs it: the container puts the package at /app/docket and pytest finds it
# through pythonpath.
#
#   scripts/install-deps.sh          runtime only, used by the image
#   scripts/install-deps.sh --dev    plus pytest and ruff, used by CI
set -euo pipefail

WANT="${1:-}"

python - "$WANT" <<'PY' > deps.txt
import sys
import tomllib

project = tomllib.load(open("pyproject.toml", "rb"))["project"]
deps = list(project["dependencies"])
if sys.argv[1] == "--dev":
    deps += project["optional-dependencies"]["dev"]
print("\n".join(deps))
PY

pip install --no-cache-dir -r deps.txt
rm -f deps.txt
