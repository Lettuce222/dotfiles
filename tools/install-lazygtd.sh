#!/bin/sh
# Install the latest published standalone release. Do not pass credentials to GitHub.
set -u

repo=https://github.com/Lettuce222/lazygtd
tmp=

fail() {
    printf 'lazygtd: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    if [ -n "$tmp" ]; then
        # Only the files created by this script, in our private directory.
        rm -f -- "$tmp/lazygtd" "$tmp/release.tar.gz" "$tmp/SHA256SUMS"
        rmdir -- "$tmp" 2>/dev/null || :
    fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
umask 077

case "$(uname -s):$(uname -m)" in
    Linux:x86_64) platform=linux-x86_64 ;;
    Linux:aarch64|Linux:arm64) platform=linux-aarch64 ;;
    Darwin:arm64) platform=macos-arm64 ;;
    Darwin:x86_64) platform=macos-x86_64 ;;
    *) fail "no release asset for $(uname -s)/$(uname -m); skipped" ;;
esac
[ "$#" -eq 0 ] || fail "usage: tools/install-lazygtd.sh"
[ -n "${HOME:-}" ] || fail "HOME is not set"
case "$HOME" in /*) ;; *) fail "HOME must be absolute" ;; esac
bin="$HOME/.local/bin"
destination="$bin/lazygtd"

command -v curl >/dev/null 2>&1 || fail "curl is needed to fetch the release"
command -v python3 >/dev/null 2>&1 || fail "python3 is needed to read the release feed"
command -v tar >/dev/null 2>&1 || fail "tar is needed to unpack the release"
if command -v sha256sum >/dev/null 2>&1; then
    checksum_command=sha256sum
elif command -v shasum >/dev/null 2>&1; then
    checksum_command=shasum
else
    fail "sha256sum or shasum is needed to verify the release"
fi
if [ -L "$destination" ] || { [ -e "$destination" ] && [ ! -f "$destination" ]; }; then
    fail "$destination is not a regular file; left it alone"
fi
mkdir -p -- "$bin" || fail "could not create $bin"
tmp=$(mktemp -d "$bin/.lazygtd-install.XXXXXXXX") || fail "could not create a staging directory"
fetch() {
    # -q as the first option disables local .curlrc settings (including
    # settings that could disable TLS checks or add credentials).
    curl -q --proto '=https' --proto-redir '=https' --location --fail --silent --show-error \
        --connect-timeout 8 --max-time 120 --output "$2" "$1"
}

digest() {
    if [ "$checksum_command" = sha256sum ]; then
        output=$(sha256sum < "$1") || return 1
    else
        output=$(shasum -a 256 < "$1") || return 1
    fi
    printf '%s\n' "${output%% *}"
}

# Read the public Atom feed instead of the REST API: unauthenticated API
# calls share a 60/hour per-IP limit. The feed lists published releases only
# (no drafts) but does not mark prereleases, so pick the highest version by
# tag, which also ranks preview.10 after preview.9 and a final release after
# its previews.
tag=$(python3 -I - <<'PY_RELEASE'
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

pattern = re.compile(r"v(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})(?:-preview\.(0|[1-9][0-9]{0,8}))?")
feed = "https://github.com/Lettuce222/lazygtd/releases.atom"
prefix = "https://github.com/Lettuce222/lazygtd/releases/tag/"
atom = "{http://www.w3.org/2005/Atom}"
try:
    body = subprocess.check_output([
        "curl", "-q", "--proto", "=https", "--fail", "--silent", "--show-error",
        "--connect-timeout", "8", "--max-time", "30", "--max-filesize", "10000000",
        "--header", "Accept: application/atom+xml",
        feed,
    ])
    # The feed never needs a DTD; refusing one rules out entity expansion.
    if b"<!DOCTYPE" in body.upper():
        raise ValueError("release feed contains a DTD")
    root = ET.fromstring(body)
    if root.tag != f"{atom}feed":
        raise ValueError("unexpected release feed")
    best = None
    version = (-1,)
    for entry in root.iter(f"{atom}entry"):
        for link in entry.iter(f"{atom}link"):
            href = link.get("href") or ""
            if link.get("rel", "alternate") != "alternate" or not href.startswith(prefix):
                continue
            match = pattern.fullmatch(href[len(prefix):])
            if not match:
                continue
            major, minor, patch, preview = match.groups()
            key = (int(major), int(minor), int(patch), preview is None, int(preview or 0))
            if key > version:
                best, version = match.group(0), key
    if best is None:
        raise ValueError("no published lazygtd release")
    print(best)
except (OSError, subprocess.SubprocessError, ValueError, ET.ParseError) as exc:
    sys.exit(f"lazygtd release lookup: {exc}")
PY_RELEASE
) || fail "could not find the latest published release; existing install unchanged"
archive="lazygtd-$tag-$platform.tar.gz"
download="$repo/releases/download/$tag"

fetch "$download/SHA256SUMS" "$tmp/SHA256SUMS" || fail "checksum list unavailable for $tag; existing install unchanged"
expected=$(LC_ALL=C awk -v asset="$archive" '
    $2 == asset || $2 == "*" asset {
        count++
        if (NF != 2 || length($1) != 64 || $1 ~ /[^0-9a-fA-F]/) invalid = 1
        digest = tolower($1)
    }
    END {
        if (count != 1 || invalid) exit 1
        print digest
    }
' "$tmp/SHA256SUMS") || fail "checksum list has no unique valid entry for $archive"

fetch "$download/$archive" "$tmp/release.tar.gz" || fail "$archive unavailable; existing install unchanged"
actual=$(digest "$tmp/release.tar.gz") || fail "could not calculate SHA-256"
[ "$actual" = "$expected" ] || fail "checksum mismatch for $archive; existing install unchanged"

# Never extract arbitrary archive paths. The CI archive contains one
# root binary and optional notices; only stream the binary into our file.
members=$(tar -tzf "$tmp/release.tar.gz") || fail "could not read $archive"
if ! printf '%s\n' "$members" | LC_ALL=C awk '
    $0 == "lazygtd" || $0 == "LICENSE" || $0 == "THIRD_PARTY_NOTICES.txt" {
        if (++seen[$0] > 1) bad=1
        next
    }
    { bad=1 }
    END { exit (bad || seen["lazygtd"] != 1) }
'; then
    fail "unexpected contents in $archive"
fi
mode=$(tar -tvzf "$tmp/release.tar.gz" lazygtd) || fail "could not inspect lazygtd archive member"
case "$mode" in -*) ;; *) fail "release lazygtd member is not a regular file" ;; esac
tar -xOzf "$tmp/release.tar.gz" lazygtd > "$tmp/lazygtd" || fail "could not unpack lazygtd"
[ -s "$tmp/lazygtd" ] || fail "release contains no binary"
chmod 0755 "$tmp/lazygtd" || fail "could not make the staged binary executable"
version=$("$tmp/lazygtd" --version) || fail "staged binary did not run on this platform"
[ "$version" = "lazygtd ${tag#v}" ] || fail "staged binary has an unexpected version"

if [ -L "$destination" ] || { [ -e "$destination" ] && [ ! -f "$destination" ]; }; then
    fail "$destination is not a regular file; left it alone"
fi
if [ -x "$destination" ] && cmp -s "$tmp/lazygtd" "$destination"; then
    printf 'lazygtd: %s already verified at %s\n' "$tag" "$destination"
else
    mv -f -- "$tmp/lazygtd" "$destination" || fail "could not install to $destination"
    printf 'lazygtd: installed %s to %s\n' "$tag" "$destination"
fi
