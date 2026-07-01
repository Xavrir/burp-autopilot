#!/usr/bin/env bash
# Build burp-autopilot-ext.jar with plain javac (no Gradle/Maven needed).
# Montoya API is compile-only (provided by Burp at runtime); org.json is shaded into the jar.
set -euo pipefail

EXT="$(cd "$(dirname "$0")" && pwd)"
MONTOYA="${MONTOYA_JAR:-$EXT/lib/montoya-api-2026.4.jar}"
JSONJAR="${JSON_JAR:-$EXT/lib/json-20250517.jar}"
OUT="$EXT/build/burp-autopilot-ext.jar"

[[ -f "$MONTOYA" ]] || { echo "missing Montoya jar: $MONTOYA" >&2; exit 1; }
[[ -f "$JSONJAR" ]] || { echo "missing org.json jar: $JSONJAR" >&2; exit 1; }

rm -rf "$EXT/build"
mkdir -p "$EXT/build/classes"

echo "[1/3] compiling..."
javac -Xlint:none -cp "$MONTOYA:$JSONJAR" -d "$EXT/build/classes" \
  "$EXT/src/burpautopilot/BurpAutopilotExtension.java"

echo "[2/3] shading org.json (Montoya is NOT shaded - Burp provides it)..."
( cd "$EXT/build/classes" && unzip -oq "$JSONJAR" 'org/json/*' )

echo "[3/3] packaging $OUT"
jar cf "$OUT" -C "$EXT/build/classes" .

echo "done: $OUT"
