import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("package", ROOT / "scripts/package.py")
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)
ARCHIVES = [f"musllvm-{arch}-linux-musl-host-x86_64-linux.tar.xz" for arch in ("x86_64", "aarch64")]
FAKE_GH = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\n")
action = args[1]
if action == os.environ.get("FAKE_GH_FAIL"):
    sys.exit(1)
if action == "view":
    state = os.environ.get("FAKE_RELEASE", "missing")
    if state == "missing":
        sys.exit("release not found")
    print("true" if state == "draft" else "false")
elif action in ("create", "upload"):
    for name in ("SHA256SUMS", "sources.list"):
        if not Path(name).is_file():
            sys.exit(2)
'''
FAKE_GIT = r'''#!/usr/bin/env python3
import os
import sys
if "rev-parse" in sys.argv:
    print(os.environ["FAKE_GIT_SHA"])
else:
    print("2026-10-12")
'''


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="musllvm-package-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.prefix = self.root / "original"
        self.output = self.root / "releases"
        self.target = "x86_64-linux-musl"
        for relative in ("host/bin/clang", "host/bin/ld.lld", "bin/" + self.target + "-cc",
                         "sysroot/usr/lib/libc.so", "share/musllvm/resource-version", ".musllvm-config"):
            path = self.prefix / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n")
        (self.prefix / "host/bin/clang").chmod(0o755)
        (self.prefix / "libexec").mkdir()
        (self.prefix / "libexec/clang").symlink_to("../host/bin/clang")
        (self.prefix / "sysroot/lib").mkdir()
        (self.prefix / "sysroot/lib/ld-musl-x86_64.so.1").symlink_to("../usr/lib/libc.so")
        self.sources = self.root / "sources.list"
        self.sources.write_text("llvm llvm-test.tar.xz " + "0" * 64 + " https://example.invalid/llvm\n")
        self.source_root = self.root / "src"
        for relative in ("llvm-test/LICENSE.TXT", "llvm-test/libcxx/LICENSE.TXT",
                         "llvm-test/LICENSES/exceptions/test-exception"):
            path = self.source_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative + "\n")

    def package(self, target=None):
        return PACKAGE.package(self.prefix, target or self.target, self.sources, self.output, self.source_root)

    def test_archive_preserves_links_modes_and_source_metadata(self):
        archive = self.package()
        digest, filename = archive.with_name(archive.name + ".sha256").read_text().split()
        self.assertEqual(digest, hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(filename, archive.name)
        self.assertIn("host-" + platform.machine() + "-linux", filename)
        root = "musllvm-" + self.target
        with tarfile.open(archive) as stream:
            self.assertEqual(stream.getmember(root + "/libexec/clang").linkname, "../host/bin/clang")
            self.assertEqual(stream.getmember(root + "/host/bin/clang").mode, 0o755)
            self.assertNotIn(root + "/.musllvm-config", stream.getnames())
            self.assertEqual(stream.extractfile(root + "/share/musllvm/sources.list").read(), self.sources.read_bytes())
            metadata = json.load(stream.extractfile(root + "/share/musllvm/build-info.json"))
            self.assertEqual(metadata["target"], self.target)
            self.assertEqual(metadata["llvm_mode"], "source")
            self.assertEqual(metadata["source_manifest_sha256"], hashlib.sha256(self.sources.read_bytes()).hexdigest())
            for relative in ("LICENSE.TXT", "libcxx/LICENSE.TXT", "LICENSES/exceptions/test-exception"):
                self.assertEqual(stream.extractfile(root + "/share/musllvm/licenses/llvm/" + relative).read(),
                                 (self.source_root / "llvm-test" / relative).read_bytes())
            self.assertEqual(len({member.mtime for member in stream}), 1)
            extracted = self.root / "unpacked"
            stream.extractall(extracted, filter="data")
        relocated = extracted / root
        self.assertEqual((relocated / "libexec/clang").resolve(), relocated / "host/bin/clang")
        self.assertEqual((relocated / "sysroot/lib/ld-musl-x86_64.so.1").read_bytes(), b"fixture\n")

    def test_archive_is_independent_of_file_timestamps(self):
        archive = self.package()
        first = archive.read_bytes()
        os.utime(self.prefix / "host/bin/clang", (1, 1))
        self.assertEqual(self.package().read_bytes(), first)

    def test_absolute_or_escaping_links_are_rejected(self):
        external = self.root / "external"
        external.write_text("fixture")
        link = self.prefix / "libexec/bad"
        for destination in (str(external), str(self.prefix / "host/bin/clang"), "../../external", "missing"):
            with self.subTest(destination=destination):
                link.symlink_to(destination)
                with self.assertRaises(ValueError):
                    self.package()
                link.unlink()
        self.assertFalse(self.output.exists())

    def test_incomplete_toolchains_and_unsafe_targets_are_rejected(self):
        (self.prefix / "host/bin/ld.lld").unlink()
        with self.assertRaisesRegex(ValueError, "incomplete toolchain"):
            self.package()
        with self.assertRaisesRegex(ValueError, "invalid target"):
            self.package("../../escape")

    def test_failed_packaging_keeps_the_existing_archive(self):
        archive = self.package()
        first = archive.read_bytes()
        with patch.object(PACKAGE.tarfile, "open", side_effect=OSError("fixture write failure")):
            with self.assertRaises(OSError):
                self.package()
        self.assertEqual(archive.read_bytes(), first)
        self.assertFalse(list(self.output.glob(".package-*")))

    def test_new_core_component_keeps_its_license_and_requires_its_source(self):
        with self.sources.open("a") as stream:
            stream.write("pkgconf pkgconf-test.tar.gz " + "1" * 64 + " https://example.invalid/pkgconf\n")
        with self.assertRaisesRegex(ValueError, "missing extracted source"):
            self.package()
        directory = self.source_root / "pkgconf-test"
        directory.mkdir()
        (directory / "COPYING").write_text("pkgconf license fixture\n")
        with tarfile.open(self.package()) as stream:
            self.assertEqual(stream.extractfile("musllvm-" + self.target + "/share/musllvm/licenses/pkgconf/COPYING").read(),
                             b"pkgconf license fixture\n")


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="musllvm-publish-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "scripts").mkdir()
        shutil.copyfile(ROOT / "scripts/publish.sh", self.root / "scripts/publish.sh")
        (self.root / "sources.list").write_text("# component archive sha256 url\nllvm llvm-test.tar.xz digest url\npkgconf pkgconf-test.tar.xz digest url\n")
        self.output = self.root / "build/releases"
        self.output.mkdir(parents=True)
        for name in ARCHIVES:
            content = name.encode()
            (self.output / name).write_bytes(content)
            (self.output / (name + ".sha256")).write_text(hashlib.sha256(content).hexdigest() + "  " + name + "\n")
        tools = self.root / "tools"
        tools.mkdir()
        for name, content in (("gh", FAKE_GH), ("git", FAKE_GIT)):
            path = tools / name
            path.write_text(content)
            path.chmod(0o755)
        self.log = self.root / "gh.jsonl"
        self.env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
                    "GITHUB_SHA": "1" * 40, "FAKE_GIT_SHA": "1" * 40,
                    "FAKE_GH_LOG": str(self.log), "FAKE_RELEASE": "missing", "FAKE_GH_FAIL": ""}

    def publish(self, success=True, **environment):
        result = subprocess.run(["sh", str(self.root / "scripts/publish.sh")],
                                env={**self.env, **environment}, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode == 0, success, result.stdout)
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_new_release_uploads_both_targets_before_publication(self):
        calls = self.publish()
        self.assertEqual([call[1] for call in calls], ["view", "create", "edit"])
        self.assertEqual(calls[1][2], "musllvm-2026-10-12-" + "1" * 12)
        self.assertIn("--draft", calls[1])
        self.assertEqual(calls[1][calls[1].index("--target") + 1], self.env["GITHUB_SHA"])
        for archive in ARCHIVES:
            self.assertIn(archive, calls[1])
        self.assertIn("--draft=false", calls[2])
        self.assertIn("pkgconf-test.tar.xz", (self.output / "notes.md").read_text())
        self.assertEqual(len((self.output / "SHA256SUMS").read_text().splitlines()), 2)

    def test_published_release_is_not_overwritten(self):
        calls = self.publish(FAKE_RELEASE="published")
        self.assertEqual([call[1] for call in calls], ["view"])

    def test_draft_release_resumes_its_upload(self):
        calls = self.publish(FAKE_RELEASE="draft")
        self.assertEqual([call[1] for call in calls], ["view", "upload", "edit"])
        self.assertIn("--clobber", calls[1])

    def test_missing_or_corrupt_archives_prevent_publication(self):
        archive = self.output / ARCHIVES[0]
        archive.write_text("corrupt")
        self.assertEqual(self.publish(success=False), [])
        archive.unlink()
        self.assertEqual(self.publish(success=False), [])

    def test_checksum_for_another_archive_prevents_publication(self):
        shutil.copyfile(self.output / (ARCHIVES[0] + ".sha256"), self.output / (ARCHIVES[1] + ".sha256"))
        self.assertEqual(self.publish(success=False), [])

    def test_upload_failure_leaves_the_release_unpublished(self):
        for state, action in (("missing", "create"), ("draft", "upload")):
            with self.subTest(state=state):
                if self.log.exists():
                    self.log.unlink()
                calls = self.publish(success=False, FAKE_RELEASE=state, FAKE_GH_FAIL=action)
                self.assertNotIn("edit", [call[1] for call in calls])

    def test_failed_release_lookup_creates_nothing(self):
        calls = self.publish(success=False, FAKE_GH_FAIL="view")
        self.assertEqual([call[1] for call in calls], ["view"])

    def test_wrong_checkout_prevents_publication(self):
        self.assertEqual(self.publish(success=False, FAKE_GIT_SHA="2" * 40), [])


if __name__ == "__main__":
    unittest.main()
