#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="SPhillips1337"
REPO_NAME="DynamicMCPProxy"
REPO_URL="https://github.com/${REPO_OWNER}/${REPO_NAME}.git"
PROJECT_NAME="dynamic-mcp-proxy"
DEFAULT_INSTALL_DIR="${HOME}/DynamicMCPProxy"

log() {
  printf '[%s] %s\n' "${PROJECT_NAME}" "$*"
}

fail() {
  printf '[%s] ERROR: %s\n' "${PROJECT_NAME}" "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command '$1' is not installed or not on PATH."
}

usage() {
  cat <<USAGE
Install ${REPO_OWNER}/${REPO_NAME}.

Usage: ./install.sh [--dir PATH] [--no-sync]

Options:
  --dir PATH   Clone/install into PATH (default: ${DEFAULT_INSTALL_DIR})
  --no-sync    Skip 'uv sync' after checkout/validation
  -h, --help   Show this help

Run from inside an existing ${REPO_NAME} checkout to install in place, or run
from another directory to clone/update ${REPO_URL} into --dir.
USAGE
}

install_dir="${INSTALL_DIR:-${DEFAULT_INSTALL_DIR}}"
sync_deps=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)
      [[ $# -ge 2 ]] || fail "--dir requires a path"
      install_dir="$2"
      shift 2
      ;;
    --no-sync)
      sync_deps=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

need_cmd git
need_cmd uv

is_project_dir() {
  [[ -f "pyproject.toml" ]] && grep -q "name = \"${PROJECT_NAME}\"" "pyproject.toml" && [[ -f "src/proxy_server.py" ]]
}

validate_existing_dir() {
  local dir="$1"
  [[ -d "$dir" ]] || return 1
  cd "$dir"

  if [[ -d ".git" ]]; then
    local origin
    origin="$(git remote get-url origin 2>/dev/null || true)"
    case "$origin" in
      "git@github.com:${REPO_OWNER}/${REPO_NAME}.git"|"https://github.com/${REPO_OWNER}/${REPO_NAME}.git"|"https://github.com/${REPO_OWNER}/${REPO_NAME}")
        return 0
        ;;
      *)
        fail "Existing git checkout has unexpected origin remote: ${origin:-<none>}"
        ;;
    esac
  fi

  if is_project_dir; then
    log "Existing non-git directory has matching project markers."
    return 0
  fi

  return 1
}

# Install in place when executed from a valid checkout; otherwise clone/update --dir.
if is_project_dir; then
  target_dir="$(pwd -P)"
  log "Installing in existing checkout: ${target_dir}"
else
  target_dir="$install_dir"
  if [[ -e "$target_dir" ]]; then
    validate_existing_dir "$target_dir" || fail "Refusing to use existing non-${REPO_NAME} directory: ${target_dir}"
    log "Updating existing checkout: ${target_dir}"
    cd "$target_dir"
    if [[ -d ".git" ]]; then
      git fetch --prune origin
      current_branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
      if [[ -n "$current_branch" ]]; then
        git pull --ff-only origin "$current_branch" || log "Fast-forward skipped; continuing with local checkout."
      fi
    fi
  else
    mkdir -p "$(dirname "$target_dir")"
    log "Cloning ${REPO_URL} into ${target_dir}"
    git clone "$REPO_URL" "$target_dir"
    cd "$target_dir"
  fi
fi

[[ -f "pyproject.toml" ]] || fail "pyproject.toml not found in $(pwd)"
[[ -f "catalogue.json" ]] || fail "catalogue.json not found in $(pwd)"
[[ -f "src/proxy_server.py" ]] || fail "src/proxy_server.py not found in $(pwd)"

if [[ "$sync_deps" -eq 1 ]]; then
  log "Synchronizing Python dependencies with uv."
  uv sync
else
  log "Skipping dependency sync (--no-sync)."
fi

if [[ ! -f "proxy_config.json" && -f "proxy_config.json.example" ]]; then
  cp "proxy_config.json.example" "proxy_config.json"
  log "Created proxy_config.json from example. Review it before production use."
fi

log "Install complete. Add this project to your MCP client with:"
printf '  uv run --quiet --project %q python -m src.proxy_server\n' "$(pwd -P)"
log "If catalogue entries use npx/uvx, ensure your MCP client env PATH includes those binaries."
