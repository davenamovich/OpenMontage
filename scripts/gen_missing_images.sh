#!/bin/bash
# Generate missing scene images using z-ai CLI directly.
# Uses process group isolation to prevent zombie processes.
#
# Usage: bash scripts/gen_missing_images.sh projects/<slug>

set -e
PROJECT_DIR="${1:-projects/emma-a-34-year-old-waitress-rebuilding-her-life-after-a-pain}"

# Get list of missing scene IDs by comparing scene_plan.json with existing images
MISSING=$(python3 -c "
import json
from pathlib import Path
sp = json.load(open('${PROJECT_DIR}/scene_plan.json'))
img_dir = Path('${PROJECT_DIR}/assets/images')
existing = {f.stem.replace('scene-', '') for f in img_dir.glob('*.png')}
missing = [sc['id'] for sc in sp['scenes'] if sc['id'] not in existing]
print(' '.join(missing))
")

echo "Missing scenes: $MISSING"
echo ""

for SID in $MISSING; do
    OUT_PATH="${PROJECT_DIR}/assets/images/scene-${SID}.png"

    # Skip if already exists
    if [ -f "$OUT_PATH" ] && [ -s "$OUT_PATH" ]; then
        echo "$SID: already exists, skipping"
        continue
    fi

    # Get the prompt for this scene
    PROMPT=$(python3 -c "
import json
sp = json.load(open('${PROJECT_DIR}/scene_plan.json'))
for sc in sp['scenes']:
    if sc['id'] == '${SID}':
        meta = sc.get('metadata', {})
        prompt = meta.get('image_prompt', '')
        neg = meta.get('negative_prompt', '')
        if neg:
            print(prompt + '\n\nAvoid: ' + neg)
        else:
            print(prompt)
        break
")

    if [ -z "$PROMPT" ]; then
        echo "$SID: no prompt found, skipping"
        continue
    fi

    echo -n "$SID: generating... "
    # Run z-ai image in a new process group, with a 60s timeout
    # Redirect all output to /dev/null to prevent terminal interference
    timeout 60 bash -c "z-ai image --prompt \"\$0\" --output \"\$1\" --size 1344x768" \
        "$PROMPT" "$OUT_PATH" > /dev/null 2>&1 &
    ZAI_PID=$!

    # Wait for it to complete
    wait $ZAI_PID 2>/dev/null
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ] && [ -f "$OUT_PATH" ] && [ -s "$OUT_PATH" ]; then
        SIZE=$(stat -c%s "$OUT_PATH" 2>/dev/null || echo "?")
        echo "OK ($SIZE bytes)"
    else
        echo "FAILED (exit $EXIT_CODE)"
        # Try again after a delay
        echo "  Retrying in 15s..."
        sleep 15
        timeout 60 bash -c "z-ai image --prompt \"\$0\" --output \"\$1\" --size 1344x768" \
            "$PROMPT" "$OUT_PATH" > /dev/null 2>&1 &
        wait $! 2>/dev/null
        if [ -f "$OUT_PATH" ] && [ -s "$OUT_PATH" ]; then
            SIZE=$(stat -c%s "$OUT_PATH" 2>/dev/null || echo "?")
            echo "  OK on retry ($SIZE bytes)"
        else
            echo "  Still failed — skipping"
        fi
    fi

    # Kill any zombie z-ai processes
    pkill -9 -f "z-ai image" 2>/dev/null || true
    sleep 3
done

echo ""
echo "Done. Total images:"
ls -1 "${PROJECT_DIR}/assets/images/" | wc -l
