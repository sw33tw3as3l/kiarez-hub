#!/usr/bin/env bash
# Symlink `space` and `space-cli` into ~/.local/bin so they're on PATH.
# Nothing is installed system-wide and no packages are touched.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
target="${1:-$HOME/.local/bin}"
mkdir -p "$target"

for cmd in space space-cli; do
  ln -sf "$repo/bin/$cmd" "$target/$cmd"
  echo "linked $target/$cmd -> $repo/bin/$cmd"
done

case ":$PATH:" in
  *":$target:"*) ;;
  *) echo; echo "note: $target is not on your PATH. Add to ~/.bashrc:";
     echo "  export PATH=\"\$PATH:$target\"" ;;
esac
