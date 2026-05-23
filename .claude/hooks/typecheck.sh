#!/usr/bin/env bash
# Type-check the desktop app after Edit/Write to .ts/.tsx files.
# Quality bar: warnings only — exit 0 always, surface errors via stderr.

set -u

PAYLOAD=$(cat)
FILE=$(printf '%s' "$PAYLOAD" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)

# Skip non-TS/TSX edits
case "$FILE" in
  *.ts|*.tsx) ;;
  *) exit 0 ;;
esac

# Only type-check edits inside apps/desktop (the only TS project in the monorepo)
case "$FILE" in
  *"/apps/desktop/"*) ;;
  *) exit 0 ;;
esac

# Need a project root to cd into
if [ -z "${CLAUDE_PROJECT_DIR:-}" ] || [ ! -d "$CLAUDE_PROJECT_DIR/apps/desktop" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR/apps/desktop" || exit 0

OUTPUT=$(pnpm exec tsc --build --noEmit 2>&1)
EXIT=$?

if [ "$EXIT" -ne 0 ]; then
  {
    echo "[typecheck] tsc reported errors after editing $FILE:"
    printf '%s\n' "$OUTPUT" | tail -40
  } >&2
fi

exit 0
