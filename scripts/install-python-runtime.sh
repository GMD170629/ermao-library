#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "Usage: sh install-python-runtime.sh PROJECT_DIR VENV_DIR" >&2
  exit 2
fi

project_dir="$1"
venv_dir="$2"
test -f "$project_dir/pyproject.toml"
test -f "$project_dir/uv.lock"

# Both images run app from their copied source directory. Install only the
# locked runtime dependencies: building the project would independently resolve
# its unpinned setuptools/wheel build requirements. Do not select dev extras.
requirements_file="$(mktemp)"
trap 'rm -f "$requirements_file"' EXIT
uv export --project "$project_dir" --locked --no-dev --no-emit-project \
  --no-python-downloads --no-header --no-annotate \
  --output-file "$requirements_file" >/dev/null
uv venv --python python3.11 --no-python-downloads "$venv_dir"
uv pip sync --python "$venv_dir/bin/python" --require-hashes \
  --only-binary :all: "$requirements_file"
uv pip check --python "$venv_dir/bin/python"
