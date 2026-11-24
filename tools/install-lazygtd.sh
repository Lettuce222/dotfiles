#!/bin/sh
# Install the pinned standalone release. Do not pass credentials to GitHub.
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
lock=$(dirname "$0")/lazygtd-release.lock
release=$(LC_ALL=C awk '
    NR == 1 && NF == 2 &&
    $1 ~ /^v[0-9]+\.[0-9]+\.[0-9]+(-preview\.[0-9]+)?$/ &&
    length($2) == 64 && $2 !~ /[^0-9a-f]/ { ref=$1; digest=$2 }
    END { if (NR != 1 || !ref) exit 1; print ref, digest }
' "$lock") || fail "release checksum is not pinned in lazygtd-release.lock; existing install unchanged"
tag=${release% *}
sums_sha256=${release##* }
[ -n "${HOME:-}" ] || fail "HOME is not set"
case "$HOME" in /*) ;; *) fail "HOME must be absolute" ;; esac
bin="$HOME/.local/bin"
destination="$bin/lazygtd"

command -v curl >/dev/null 2>&1 || fail "curl is needed to fetch $tag"
command -v tar >/dev/null 2>&1 || fail "tar is needed to unpack $tag"
if command -v sha256sum >/dev/null 2>&1; then
    checksum_command=sha256sum
elif command -v shasum >/dev/null 2>&1; then
    checksum_command=shasum
else
    fail "sha256sum or shasum is needed to verify $tag"
fi
if [ -L "$destination" ] || { [ -e "$destination" ] && [ ! -f "$destination" ]; }; then
    fail "$destination is not a regular file; left it alone"
fi
mkdir -p -- "$bin" || fail "could not create $bin"
tmp=$(mktemp -d "$bin/.lazygtd-install.XXXXXXXX") || fail "could not create a staging directory"
archive="lazygtd-$tag-$platform.tar.gz"
download="$repo/releases/download/$tag"

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

fetch "$download/SHA256SUMS" "$tmp/SHA256SUMS" || fail "checksum list unavailable for $tag; existing install unchanged"
actual_sums=$(digest "$tmp/SHA256SUMS") || fail "could not calculate SHA-256 for checksum list"
[ "$actual_sums" = "$sums_sha256" ] || fail "checksum list digest does not match the pinned release; existing install unchanged"
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
