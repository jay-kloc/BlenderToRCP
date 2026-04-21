#!/bin/bash
# compress_textures.sh — Re-compress all PNG files in a folder using pngquant + optipng.
#
# Usage:
#   ./compress_textures.sh <folder>
#   ./compress_textures.sh textures/
#
# Requires: pngquant, optipng
#   brew install pngquant optipng

set -euo pipefail

FOLDER="${1:-.}"

if [ ! -d "$FOLDER" ]; then
    echo "Error: '$FOLDER' is not a directory."
    exit 1
fi

# Check dependencies
for cmd in pngquant optipng; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: '$cmd' not found. Install with: brew install $cmd"
        exit 1
    fi
done

COUNT=0
SAVED=0

for png in "$FOLDER"/*.png "$FOLDER"/*.PNG; do
    [ -f "$png" ] || continue

    BEFORE=$(stat -f%z "$png" 2>/dev/null || stat -c%s "$png" 2>/dev/null)

    # Lossy pass: pngquant (256 colors, high quality, skip if already quantized)
    pngquant --quality=80-100 --speed 1 --force --ext .png --skip-if-larger "$png" 2>/dev/null || true

    # Lossless pass: optipng (maximum compression)
    optipng -o7 -quiet "$png" 2>/dev/null || true

    AFTER=$(stat -f%z "$png" 2>/dev/null || stat -c%s "$png" 2>/dev/null)
    DIFF=$((BEFORE - AFTER))
    if [ "$DIFF" -gt 0 ]; then
        SAVED=$((SAVED + DIFF))
    fi

    COUNT=$((COUNT + 1))
    echo "  $png: $(( BEFORE / 1024 ))KB → $(( AFTER / 1024 ))KB"
done

if [ "$COUNT" -eq 0 ]; then
    echo "No PNG files found in '$FOLDER'."
else
    echo ""
    echo "Done. $COUNT files processed, $(( SAVED / 1024 ))KB saved."
fi
