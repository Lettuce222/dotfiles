"""Exercise the production install command with a local fixture for curl."""
import hashlib
import io
from xml.sax.saxutils import quoteattr
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools" / "install-lazygtd.sh"
TAG = "v0.1.0-preview.10"
FEED = "https://github.com/Lettuce222/lazygtd/releases.atom"
RELEASE = f"https://github.com/Lettuce222/lazygtd/releases/download/{TAG}"


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.installer = self.root / INSTALLER.name
        self.installer.write_bytes(INSTALLER.read_bytes())
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.bin = self.home / ".local/bin"
        self.destination = self.bin / "lazygtd"
        self.fixtures = self.root / "release"
        self.fixtures.mkdir()
        self.feed([TAG])
        self.calls = self.root / "calls"
        self.shims = self.root / "shims"
        self.shims.mkdir()
        self.shim("curl", """
test "$1" = "-q" || exit 33
while [ "$#" -gt 1 ]; do
    if [ "$1" = --output ]; then destination=$2; shift; fi
    shift
done
printf '%s\n' "$1" >> "$CALLS"
case "$1" in
    'https://github.com/Lettuce222/lazygtd/releases.atom')
        cat "$FIXTURES/releases.atom"; exit ;;
esac
test -f "$FIXTURES/${1##*/}" || exit 22
cp "$FIXTURES/${1##*/}" "$destination"
""")
        self.shim("uname", """case "$1" in -s) printf '%s\n' "$OS";; -m) printf '%s\n' "$ARCH";; esac""")
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "PATH": f"{self.shims}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(self.calls),
            "FIXTURES": str(self.fixtures),
            "OS": "Linux",
            "ARCH": "x86_64",
        }

    def feed(self, tags, header='<?xml version="1.0" encoding="UTF-8"?>\n'):
        """Write a feed shaped like GitHub's releases.atom, newest entry first."""
        entries = "".join(
            "<entry>"
            f"<id>tag:github.com,2008:Repository/1/{tag}</id>"
            "<link rel=\"alternate\" type=\"text/html\" "
            f"href={quoteattr('https://github.com/Lettuce222/lazygtd/releases/tag/' + tag)}/>"
            f"<title>lazygtd {tag}</title>"
            "</entry>"
            for tag in tags
        )
        (self.fixtures / "releases.atom").write_text(
            header + '<feed xmlns="http://www.w3.org/2005/Atom">'
            '<link type="text/html" rel="alternate" href="https://github.com/Lettuce222/lazygtd/releases"/>'
            f"{entries}</feed>"
        )

    def shim(self, name, contents):
        script = self.shims / name
        script.write_text("#!/bin/sh\nset -eu\n" + contents)
        script.chmod(0o700)

    def release(self, platform="linux-x86_64", extra=(), version=TAG[1:]):
        name = f"lazygtd-{TAG}-{platform}.tar.gz"
        archive = self.fixtures / name
        binary = f'#!/bin/sh\nprintf "%s\\n" "lazygtd {version}"\n'.encode()
        with tarfile.open(archive, "w:gz") as tar:
            info = tarfile.TarInfo("lazygtd")
            info.size = len(binary)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(binary))
            for member in extra:
                info = tarfile.TarInfo(member)
                info.size = 1
                tar.addfile(info, io.BytesIO(b"x"))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        sums = self.fixtures / "SHA256SUMS"
        sums.write_text(f"{digest}  {name}\n")
        return name, archive, sums, binary

    def invoke(self):
        return subprocess.run(
            ["sh", str(self.installer)], cwd=self.root, env=self.env, text=True,
            capture_output=True, check=False,
        )

    def existing(self):
        self.bin.mkdir(parents=True)
        self.destination.write_bytes(b"previous binary")
        self.destination.chmod(0o755)

    def test_latest_filename_and_verified_install_are_idempotent(self):
        name, _, _, binary = self.release(extra=("LICENSE", "THIRD_PARTY_NOTICES.txt"))
        out = self.invoke()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.destination.read_bytes(), binary)
        self.assertTrue(os.access(self.destination, os.X_OK))
        self.assertEqual(self.calls.read_text().splitlines(),
                         [FEED, f"{RELEASE}/SHA256SUMS", f"{RELEASE}/{name}"])
        before = self.destination.stat().st_ino
        out = self.invoke()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("already verified", out.stdout)
        self.assertEqual(self.destination.stat().st_ino, before)
        self.assertEqual(list(self.bin.iterdir()), [self.destination])

    def test_release_unavailable_keeps_previous_install(self):
        self.existing()
        out = self.invoke()
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("checksum list unavailable", out.stderr)
        self.assertEqual(self.destination.read_bytes(), b"previous binary")
        self.assertEqual(self.calls.read_text().splitlines(), [FEED, f"{RELEASE}/SHA256SUMS"])

    def test_wrong_digest_or_duplicate_never_replaces_previous_binary(self):
        self.existing()
        _, archive, sums, _ = self.release()
        sums.write_text(sums.read_text() * 2)
        out = self.invoke()
        self.assertIn("no unique valid entry", out.stderr)
        self.assertEqual(self.destination.read_bytes(), b"previous binary")
        self.release()
        archive.write_bytes(b"tampered")
        out = self.invoke()
        self.assertIn("checksum mismatch", out.stderr)
        self.assertEqual(self.destination.read_bytes(), b"previous binary")

    def test_unreadable_feed_keeps_previous_install(self):
        self.existing()
        self.release()
        for feed in ("not xml", "<rss/>", '<feed xmlns="http://www.w3.org/2005/Atom"/>'):
            (self.fixtures / "releases.atom").write_text(feed)
            out = self.invoke()
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("could not find the latest published release", out.stderr)
            self.assertEqual(self.destination.read_bytes(), b"previous binary")
        self.feed([TAG], header='<!DOCTYPE feed [<!ENTITY x "y">]>')
        out = self.invoke()
        self.assertIn("contains a DTD", out.stderr)
        self.assertEqual(set(self.calls.read_text().splitlines()), {FEED})
        self.assertEqual(self.destination.read_bytes(), b"previous binary")

    def test_unexpected_archive_member_and_version_are_refused(self):
        self.existing()
        self.release(extra=("../not-written",))
        out = self.invoke()
        self.assertIn("unexpected contents", out.stderr)
        self.assertFalse((self.bin / "not-written").exists())
        self.assertEqual(self.destination.read_bytes(), b"previous binary")
        self.release(version="0.0.0")
        out = self.invoke()
        self.assertIn("unexpected version", out.stderr)
        self.assertEqual(self.destination.read_bytes(), b"previous binary")

    def test_supported_and_unsupported_platforms(self):
        self.env.update(OS="Darwin", ARCH="arm64")
        name, _, _, _ = self.release(platform="macos-arm64")
        out = self.invoke()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(name, self.calls.read_text())
        self.calls.unlink()
        self.env.update(OS="Linux", ARCH="aarch64")
        name, _, _, _ = self.release(platform="linux-aarch64")
        out = self.invoke()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(name, self.calls.read_text())
        self.calls.unlink()
        self.env.update(OS="Linux", ARCH="riscv64")
        out = self.invoke()
        self.assertIn("no release asset", out.stderr)
        self.assertFalse(self.calls.exists())

    def test_selects_highest_version_in_feed_including_previews(self):
        self.release()
        # Feed order is by update time; a later-edited old release must not win.
        self.feed(["v0.1.0-preview.9", TAG, "v0.0.9", "v0.1.0-preview.2", "latest", "v9.0.0-rc.1"])
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls.read_text().splitlines()[:2], [FEED, f"{RELEASE}/SHA256SUMS"])
        self.assertIn(TAG, result.stdout)

    def test_final_release_outranks_its_previews(self):
        self.feed(["v0.1.0-preview.11", "v0.1.0", "v0.0.10"])
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum list unavailable for v0.1.0;", result.stderr)

    def test_does_not_fall_back_to_older_release_if_latest_is_incomplete(self):
        self.existing()
        self.feed(["v0.1.0", TAG])
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum list unavailable for v0.1.0;", result.stderr)
        self.assertEqual(self.calls.read_text().splitlines(),
                         [FEED, "https://github.com/Lettuce222/lazygtd/releases/download/v0.1.0/SHA256SUMS"])
        self.assertEqual(self.destination.read_bytes(), b"previous binary")

    def test_feed_without_releases_keeps_previous_install(self):
        self.existing()
        self.feed(["nightly"])
        result = self.invoke()
        self.assertIn("no published lazygtd release", result.stderr)
        self.assertEqual(self.calls.read_text().splitlines(), [FEED])
        self.assertEqual(self.destination.read_bytes(), b"previous binary")

    def test_no_api_or_credentials_are_used(self):
        text = INSTALLER.read_text()
        self.assertNotIn("api.github.com", text)
        for word in ("GITHUB_TOKEN", "GH_TOKEN", "Authorization", "--user", "netrc"):
            self.assertNotIn(word, text)

    def test_existing_symlink_is_not_followed_or_overwritten(self):
        self.existing()
        own = self.bin / "external"
        self.destination.rename(own)
        self.destination.symlink_to(own)
        self.release()
        out = self.invoke()
        self.assertNotEqual(out.returncode, 0)
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(own.read_bytes(), b"previous binary")
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
