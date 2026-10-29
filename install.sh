#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-only
# Download and install the complete, versioned Linux release. No sudo needed.
set -euo pipefail
version=v0.3.0
base="https://github.com/Prunebrother/edgeloop-ai/releases/download/$version"
cache="${XDG_CACHE_HOME:-$HOME/.cache}/edgeloop-ai/$version"
destination="$HOME/.local/share/edgeloop-ai/releases/$version"
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { echo 'This release supports Linux x86_64.' >&2; exit 1; }
for cmd in curl sha256sum tar gzip flock; do
  command -v "$cmd" >/dev/null || { echo "Required system tool missing: $cmd" >&2; exit 1; }
done
mkdir -p "$cache" "$(dirname "$destination")"
exec 9>"$cache/install.lock"
flock -n 9 || { echo 'An EdgeLoop installation is already running.' >&2; exit 1; }
if [[ -d "$destination" ]]; then
  echo "Using existing $version installation."
  exec bash "$destination/tools/install-bundle.sh" "$@"
fi
echo 'Downloading EdgeLoop AI with all portraits, models, Ollama and Python.'
echo 'Allow approximately 15 GB for downloads and 25 GB for installation (40 GB free recommended).'
curl -fL --retry 3 "$base/SHA256SUMS" -o "$cache/SHA256SUMS"
parts=()
while read -r digest filename; do
  [[ $digest =~ ^[a-f0-9]{64}$ && $filename =~ ^edgeloop-ai-linux-x86_64\.tar\.gz\.part[0-9]{2}$ ]] || continue
  parts+=("$cache/$filename")
  if ! (cd "$cache" && echo "$digest  $filename" | sha256sum -c --status); then
    if curl -fL --retry 3 -C - "$base/$filename" -o "$cache/$filename"; then
      :
    else
      status=$?
      # A complete but corrupt cached file can produce HTTP 416 on resume.
      # Retry that case from scratch without discarding a partial network download.
      if [[ $status == 22 || $status == 33 ]]; then
        curl -fL --retry 3 "$base/$filename" -o "$cache/$filename.retry"
        mv -- "$cache/$filename.retry" "$cache/$filename"
      else
        echo 'Download interrupted. Run this installer again to resume.' >&2; exit 1
      fi
    fi
    if ! (cd "$cache" && echo "$digest  $filename" | sha256sum -c --status); then
      rm -f -- "$cache/$filename"
      echo "Checksum failed for $filename; run the installer again to retry." >&2; exit 1
    fi
  fi
done < "$cache/SHA256SUMS"
[[ ${#parts[@]} -gt 0 ]] || { echo 'Release contains no bundle parts.' >&2; exit 1; }
stage=$(mktemp -d "$(dirname "$destination")/.install-$version.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
echo 'Extracting the complete offline bundle…'
cat "${parts[@]}" | tar -xz --no-same-owner -C "$stage"
"$stage/runtime/python/bin/python3" "$stage/tools/bundle.py" verify
mv -- "$stage" "$destination"
trap - EXIT
bash "$destination/tools/install-bundle.sh" "$@"
