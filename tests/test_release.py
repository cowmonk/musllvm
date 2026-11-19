import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import struct
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


def host_elf(arch="x86_64", pie=False, interpreter=False, needed=False):
    count = 1 + interpreter + (pie or needed)
    start = 64 + 56 * count
    payload = b"\x90"
    segments = []
    if interpreter:
        loader = b"/lib/fixture-loader.so\0"
        segments.append((3, start + len(payload), len(loader)))
        payload += loader
    if pie or needed:
        dynamic = struct.pack("<qQ", 1 if needed else 0x6ffffffb, 1)
        dynamic += struct.pack("<qQ", 0, 0)
        segments.append((2, start + len(payload), len(dynamic)))
        payload += dynamic
    size = start + len(payload)
    header = b"\x7fELF\x02\x01\x01" + b"\0" * 9
    header += struct.pack("<HHIQQQIHHHHHH", 3 if pie else 2,
                          {"x86_64": 62, "aarch64": 183}[arch], 1, 0x400000 + start,
                          64, 0, 0, 64, 56, count, 0, 0, 0)
    program = struct.pack("<IIQQQQQQ", 1, 5, 0, 0x400000, 0x400000, size, size, 4096)
    for kind, offset, length in segments:
        program += struct.pack("<IIQQQQQQ", kind, 4, offset, 0x400000 + offset, 0,
                               length, length, 8)
    return header + program + payload


class StaticHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="musllvm-static-test-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "clang"

    def test_static_executables_and_static_pie_for_both_hosts(self):
        for arch in ("x86_64", "aarch64"):
            for pie in (False, True):
                with self.subTest(arch=arch, pie=pie):
                    self.path.write_bytes(host_elf(arch, pie=pie))
                    PACKAGE.check_static_elf(self.path, arch)

    def test_dynamic_loader_is_rejected_without_a_needed_entry(self):
        self.path.write_bytes(host_elf(interpreter=True))
        with self.assertRaisesRegex(ValueError, "dynamic loader"):
            PACKAGE.check_static_elf(self.path, "x86_64")

    def test_needed_library_is_rejected_without_a_loader(self):
        self.path.write_bytes(host_elf(pie=True, needed=True))
        with self.assertRaisesRegex(ValueError, "shared library"):
            PACKAGE.check_static_elf(self.path, "x86_64")

    def test_wrong_host_and_malformed_elf_are_rejected(self):
        valid = host_elf()
        for content in (b"#!/bin/sh\n", valid[:40], valid[:80],
                        valid[:5] + b"\x02" + valid[6:],
                        valid[:16] + struct.pack("<H", 1) + valid[18:]):
            with self.subTest(content=content[:20]):
                self.path.write_bytes(content)
                with self.assertRaises(ValueError):
                    PACKAGE.check_static_elf(self.path, "x86_64")
        self.path.write_bytes(host_elf("aarch64"))
        with self.assertRaisesRegex(ValueError, "architecture"):
            PACKAGE.check_static_elf(self.path, "x86_64")

    def test_truncated_or_unterminated_dynamic_section_is_rejected(self):
        content = host_elf(pie=True)
        for invalid in (content[:-1], content[:-16] + struct.pack("<qQ", 21, 0)):
            with self.subTest(length=len(invalid)):
                self.path.write_bytes(invalid)
                with self.assertRaises(ValueError):
                    PACKAGE.check_static_elf(self.path, "x86_64")


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

    def package(self, target=None, mode="source"):
        return PACKAGE.package(self.prefix, target or self.target, self.sources, self.output,
                               self.source_root, llvm_mode=mode)

    def install_static_host(self):
        for name in ("clang", "clang++", "ld.lld", "llvm-ar", "llvm-readelf"):
            path = self.prefix / "host/bin" / name
            path.write_bytes(host_elf(platform.machine()))
            path.chmod(0o755)
        (self.prefix / "share/musllvm/llvm-mode").write_text("static\n")

    def test_static_cross_package_records_the_compiler_host_runtime(self):
        self.install_static_host()
        target = "aarch64-linux-musl" if platform.machine() == "x86_64" else "x86_64-linux-musl"
        (self.prefix / "bin" / (target + "-cc")).write_text("fixture\n")
        with patch.object(PACKAGE.platform, "libc_ver", return_value=("glibc", "2.39")):
            archive = self.package(target, mode="static")
        with tarfile.open(archive) as stream:
            metadata = json.load(stream.extractfile("musllvm-" + target + "/share/musllvm/build-info.json"))
        self.assertEqual(metadata["llvm_mode"], "static")
        self.assertEqual(metadata["host"], platform.machine() + "-linux")
        self.assertEqual(metadata["host_libc"], {"name": "musl"})
        self.assertEqual(metadata["host_linkage"], "static")
        self.assertEqual(metadata["build_host_libc"], {"name": "glibc", "version": "2.39"})

    def test_static_packaging_checks_every_host_executable(self):
        self.install_static_host()
        extra = self.prefix / "host/bin/llvm-extra"
        extra.write_bytes(host_elf(platform.machine(), needed=True))
        extra.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "shared library"):
            self.package(mode="static")
        self.assertFalse(self.output.exists())

    def test_packaging_rejects_a_missing_or_wrong_build_mode(self):
        self.install_static_host()
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.package()
        (self.prefix / "share/musllvm/llvm-mode").unlink()
        with self.assertRaisesRegex(ValueError, "marker is missing"):
            self.package(mode="static")

    def test_static_host_requires_bundled_executable_tools(self):
        self.install_static_host()
        path = self.prefix / "host/bin/llvm-ar"
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "not executable"):
            self.package(mode="static")
        path.unlink()
        path.symlink_to("/bin/sh")
        with self.assertRaisesRegex(ValueError, "outside"):
            self.package(mode="static")

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
