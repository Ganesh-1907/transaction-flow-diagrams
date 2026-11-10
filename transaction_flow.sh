#!/bin/bash
# transaction_flow.sh - build transaction flow diagrams from YAML files
# Usage:
#   ./transaction_flow.sh                          # build all YAML files + index.html
#   ./transaction_flow.sh registration-sale        # build registration-sale.yaml
#   ./transaction_flow.sh registration-sale.yaml   # same as above
#   ./transaction_flow.sh all                      # build all YAML files + index.html
#   ./transaction_flow.sh --open                   # build all, then open docs/index.html in the browser
#   ./transaction_flow.sh registration-sale --open # --open works with any of the above

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
shopt -s nullglob   # no YAML files yet = nothing to build, not an error

OPEN_AFTER=0
ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--open" || "$arg" == "-o" ]]; then OPEN_AFTER=1; else ARGS+=("$arg"); fi
done
set -- "${ARGS[@]}"

if [ ! -f "$SCRIPT_DIR/venv/bin/activate" ]; then
  echo "Setting up Python virtual environment..."
  python3 -m venv "$SCRIPT_DIR/venv"
  source "$SCRIPT_DIR/venv/bin/activate"
  pip3 install -r "$SCRIPT_DIR/requirements.txt"
else
  source "$SCRIPT_DIR/venv/bin/activate"
fi

build_file() {
  local yaml_file="$1"
  echo "Building: $(basename "$yaml_file")"
  python "$SCRIPT_DIR/transaction_flow_converter.py" "$yaml_file" --output-dir "$SCRIPT_DIR/docs"
}

build_index() {
  python "$SCRIPT_DIR/transaction_flow_converter.py" --index --output-dir "$SCRIPT_DIR/docs"
}

open_index() {
  local index="$SCRIPT_DIR/docs/index.html"
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$index" >/dev/null 2>&1 &
  elif command -v open >/dev/null 2>&1; then
    open "$index"
  else
    echo "No browser opener found. Open this file yourself: $index"
  fi
}

if [[ -z "$1" || "$1" == "all" ]]; then
  for f in "$SCRIPT_DIR"/*.yaml; do
    build_file "$f"
  done
  build_index
else
  input="$1"
  [[ "$input" != *.yaml ]] && input="${input}.yaml"
  [[ ! -f "$input" ]] && input="$SCRIPT_DIR/$input"
  if [[ ! -f "$input" ]]; then
    echo "Error: file not found: $input"
    echo "Available YAML files:"
    ls "$SCRIPT_DIR"/*.yaml | xargs -n1 basename
    exit 1
  fi
  build_file "$input"
  build_index
fi

if [[ "$OPEN_AFTER" == 1 ]]; then
  open_index
fi
