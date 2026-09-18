#!/usr/bin/env bash
# Symlink space, space-cli and space-track into ~/.local/bin.
# Nothing system-wide, no packages, no services enabled.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
target="${1:-$HOME/.local/bin}"
mkdir -p "$target"

for cmd in space space-cli space-track; do
  ln -sf "$repo/bin/$cmd" "$target/$cmd"
  echo "linked $target/$cmd -> $repo/bin/$cmd"
done

case ":$PATH:" in
  *":$target:"*) ;;
  *) echo; echo "note: $target is not on your PATH. Add to ~/.bashrc:";
     echo "  export PATH=\"\$PATH:$target\"" ;;
esac

echo
echo "To have the focus tracker start with your session, see"
echo "  scripts/space-track.service"
