#!/usr/bin/env bash
# fetch-deps.sh - download the compile-time dependencies for burp-autopilot-ext from Maven
# Central into ./lib. These jars are NOT committed to the repo.
#
#   - montoya-api : compile-only (Burp provides it at runtime; never shaded into our jar)
#   - org.json    : shaded into the jar by build.sh
#
# Override versions via env: MONTOYA_VERSION, JSON_VERSION.
set -euo pipefail

EXT="$(cd "$(dirname "$0")" && pwd)"
LIB="$EXT/lib"
MONTOYA_VERSION="${MONTOYA_VERSION:-2026.4}"
JSON_VERSION="${JSON_VERSION:-20250517}"

MONTOYA_URL="https://repo1.maven.org/maven2/net/portswigger/burp/extensions/montoya-api/${MONTOYA_VERSION}/montoya-api-${MONTOYA_VERSION}.jar"
JSON_URL="https://repo1.maven.org/maven2/org/json/json/${JSON_VERSION}/json-${JSON_VERSION}.jar"

mkdir -p "$LIB"

fetch() {
  local url="$1" dest="$2"
  if [[ -f "$dest" ]]; then
    echo "have  $(basename "$dest")"
    return
  fi
  echo "fetch $(basename "$dest")"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$dest"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$url" -O "$dest"
  else
    echo "need curl or wget to fetch dependencies" >&2
    exit 1
  fi
}

fetch "$MONTOYA_URL" "$LIB/montoya-api-${MONTOYA_VERSION}.jar"
fetch "$JSON_URL"    "$LIB/json-${JSON_VERSION}.jar"

echo "done. now run: ./build.sh"
