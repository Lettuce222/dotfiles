"""Exercise the production install command with a local fixture for curl."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "tools" / "install-lazygtd.sh"
TAG = (ROOT / "tools" / "lazygtd-release.lock").read_text().split()[0]
RELEASE = f"https://github.com/Lettuce222/lazygtd/releases/download/{TAG}"


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.installer = self.root / INSTALLER.name
        self.installer.write_bytes(INSTALLER.read_bytes())
        self.lock = self.root / "lazygtd-release.lock"
        self.pin("0" * 64)
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.bin = self.home / ".local/bin"
        self.destination = self.bin / "lazygtd"
        self.fixtures = self.root / "release"
        self.fixtures.mkdir()
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

    def pin(self, digest):
        self.lock.write_text(f"{TAG} {digest}\n")

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
        self.pin(hashlib.sha256(sums.read_bytes()).hexdigest())
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

    def test_pinned_filename_and_verified_install_are_idempotent(self):
        name, _, _, binary = self.release(extra=("LICENSE", "THIRD_PARTY_NOTICES.txt"))
        out = self.invoke()
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.destination.read_bytes(), binary)
        self.assertTrue(os.access(self.destination, os.X_OK))
        self.assertEqual(self.calls.read_text().splitlines(),
                         [f"{RELEASE}/SHA256SUMS", f"{RELEASE}/{name}"])
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
        self.assertEqual(self.calls.read_text().splitlines(), [f"{RELEASE}/SHA256SUMS"])

    def test_wrong_digest_or_duplicate_never_replaces_previous_binary(self):
        self.existing()
        _, archive, sums, _ = self.release()
        sums.write_text(sums.read_text() * 2)
        self.pin(hashlib.sha256(sums.read_bytes()).hexdigest())
        out = self.invoke()
        self.assertIn("no unique valid entry", out.stderr)
        self.assertEqual(self.destination.read_bytes(), b"previous binary")
        self.release()
        archive.write_bytes(b"tampered")
        out = self.invoke()
        self.assertIn("checksum mismatch", out.stderr)
        self.assertEqual(self.destination.read_bytes(), b"previous binary")

    def test_unpinned_or_replaced_checksum_manifest_fails_before_asset(self):
        self.existing()
        _, _, sums, _ = self.release()
        previous_manifest = sums.read_bytes()
        self.release(version="1.2.3")
        self.pin(hashlib.sha256(previous_manifest).hexdigest())
        out = self.invoke()
        self.assertIn("does not match the pinned release", out.stderr)
        self.assertEqual(self.calls.read_text().splitlines(), [f"{RELEASE}/SHA256SUMS"])
        self.assertEqual(self.destination.read_bytes(), b"previous binary")
        self.calls.unlink()
        self.pin("pending")
        out = self.invoke()
        self.assertIn("not pinned", out.stderr)
        self.assertFalse(self.calls.exists())

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
