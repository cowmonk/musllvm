import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
MAKE = shutil.which("make")
TOOLS = "clang clang++ ld.lld llvm-ar llvm-ranlib llvm-nm llvm-objcopy llvm-objdump llvm-readelf llvm-strip llvm-size llvm-strings llvm-addr2line llvm-cxxfilt"
FAKE_TOOL = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"tool": name, "args": args}) + "\n")

def write(path, value="fixture"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)

if name in ("clang", "clang++"):
    version = os.environ.get("FAKE_CLANG_VERSION", "21.1.8")
    if "--version" in args:
        print("clang version " + version + " (fixture)")
    elif "-dumpversion" in args:
        print(version)
    elif "-print-resource-dir" in args:
        print(os.environ["FAKE_RESOURCE"])
    elif "-print-target-triple" in args:
        print(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--target=")))
    elif "-print-libgcc-file-name" in args:
        resource = next(arg.split("=", 1)[1] for arg in args if arg.startswith("-resource-dir="))
        print(str(Path(resource) / "lib/linux" / ("libclang_rt.builtins-" + os.environ["ARCH"] + ".a")))
    else:
        sys.exit("fixture refuses compilation")
elif name == "llvm-config":
    print(os.environ["FAKE_LLVM_CMAKE"])
elif name == "curl":
    destination = Path(args[args.index("--output") + 1])
    archive = args[-1].rsplit("/", 1)[-1]
    if os.environ.get("FAKE_CURL_BAD"):
        destination.write_text("truncated download")
    else:
        shutil.copyfile(Path(os.environ["FAKE_DOWNLOADS"]) / archive, destination)
    if os.environ.get("FAKE_CURL_FAIL"):
        sys.exit(22)
elif name == "make":
    if "headers_install" in args:
        prefix = next(arg.split("=", 1)[1] for arg in args if arg.startswith("INSTALL_HDR_PATH="))
        write(Path(prefix) / "include/linux/version.h")
    elif "install-headers" in args:
        prefix = next(arg.split("=", 1)[1] for arg in args if arg.startswith("DESTDIR="))
        write(Path(prefix) / "usr/include/stdio.h")
    elif "install" in args:
        prefix = next(arg.split("=", 1)[1] for arg in args if arg.startswith("DESTDIR="))
        write(Path(prefix) / "usr/lib/libc.so")
        (Path(prefix) / "lib").mkdir(exist_ok=True)
elif name == "cmake":
    if "-B" in args:
        directory = Path(args[args.index("-B") + 1])
        write(directory / "fixture-config.json", json.dumps(args))
    elif "--build" in args:
        directory = Path(args[args.index("--build") + 1])
        if os.environ.get("FAKE_FAIL_STAGE") == directory.name:
            sys.exit(1)
        if "install-distribution" in args:
            configuration = json.loads((directory / "fixture-config.json").read_text())
            prefix = next(arg.split("=", 1)[1] for arg in configuration if arg.startswith("-DCMAKE_INSTALL_PREFIX="))
            for tool in os.environ["FAKE_TOOLS"].split():
                path = Path(prefix) / "bin" / tool
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(os.environ["FAKE_EXECUTABLE"], path)
                path.chmod(0o755)
    elif "--install" in args:
        directory = Path(args[args.index("--install") + 1])
        configuration = json.loads((directory / "fixture-config.json").read_text())
        prefix = next(arg.split("=", 1)[1] for arg in configuration if arg.startswith("-DCMAKE_INSTALL_PREFIX="))
        if directory.name == "builtins":
            write(Path(prefix) / "lib/linux" / ("libclang_rt.builtins-" + os.environ["ARCH"] + ".a"))
        else:
            write(Path(os.environ["DESTDIR"]) / "usr/lib/libc++.a")
'''

CAPTURE = r'''#!/usr/bin/env python3
import json
import os
import sys
print(json.dumps({"args": sys.argv[1:], "env": dict(os.environ)}))
'''


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="musllvm-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        for name in ("scripts", "files/toolchain"):
            shutil.copytree(ROOT / name, self.root / name)
        for name in ("Makefile", "config.mk"):
            shutil.copyfile(ROOT / name, self.root / name)
        self.tools = Path(self.temporary.name) / "tools"
        self.tools.mkdir()
        self.fake = self.tools / "fixture"
        self.fake.write_text(FAKE_TOOL)
        self.fake.chmod(0o755)
        for name in TOOLS.split() + ["llvm-config", "curl", "make", "cmake", "ninja"]:
            (self.tools / name).symlink_to(self.fake)
        self.resource = Path(self.temporary.name) / "resource/21"
        (self.resource / "include").mkdir(parents=True)
        (self.resource / "include/unwind.h").write_text("fixture")
        self.llvm_cmake = Path(self.temporary.name) / "llvm-cmake"
        self.llvm_cmake.mkdir()
        (self.llvm_cmake / "LLVMConfig.cmake").write_text("fixture")
        self.log = Path(self.temporary.name) / "commands.jsonl"
        self.downloads = Path(self.temporary.name) / "downloads"
        self.downloads.mkdir()
        manifest = []
        for component in ("musl", "linux", "llvm", "atomic"):
            archive = self.downloads / (component + "-test.tar.gz")
            with tarfile.open(archive, "w:gz") as stream:
                relative = "configure" if component == "musl" else "placeholder"
                content = b"#!/bin/sh\nset -eu\n\"$CC\" -print-target-triple\n" if component == "musl" else b"fixture"
                info = tarfile.TarInfo(component + "-test/" + relative)
                info.size = len(content)
                info.mode = 0o755
                stream.addfile(info, io.BytesIO(content))
                if component == "atomic":
                    for relative in ("Makefile", "atomic.c"):
                        info = tarfile.TarInfo(component + "-test/" + relative)
                        info.size = 7
                        stream.addfile(info, io.BytesIO(b"fixture"))
                if component == "llvm":
                    headers = {
                        "unwind.h": b"#include <__libunwind_config.h>\n#include <unwind_itanium.h>\n",
                        "__libunwind_config.h": b"#define UNWIND_CONFIG_FIXTURE 1\n",
                        "unwind_itanium.h": b"#define UNWIND_ITANIUM_FIXTURE 1\n",
                    }
                    for name, content in headers.items():
                        info = tarfile.TarInfo(component + "-test/libunwind/include/" + name)
                        info.size = len(content)
                        stream.addfile(info, io.BytesIO(content))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            manifest.append(f"{component} {archive.name} {digest} https://example.invalid/{archive.name}\n")
        (self.root / "sources.list").write_text("".join(manifest))
        self.env = os.environ.copy()
        for key in ("ARCH", "TARGET", "PREFIX", "BUILD_DIR", "SOURCES_DIR", "SOURCES_FILE", "LLVM_MODE", "JOBS", "LINK_JOBS", "HOST_CC", "HOST_CXX", "TARGET_CFLAGS", "HOST_CFLAGS", "HOST_CXXFLAGS", "HOST_LDFLAGS", "RUNNER", "MAKEFLAGS", "MFLAGS", "MUSLLVM_SYSROOT"):
            self.env.pop(key, None)
        self.env.update({
            "PATH": str(self.tools) + os.pathsep + os.environ["PATH"],
            "FAKE_LOG": str(self.log), "FAKE_RESOURCE": str(self.resource),
            "FAKE_LLVM_CMAKE": str(self.llvm_cmake),
            "FAKE_DOWNLOADS": str(self.downloads), "ARCH": "x86_64",
            "FAKE_EXECUTABLE": str(self.fake), "FAKE_TOOLS": TOOLS,
        })

    def run_make(self, *arguments, success=True, env=None):
        result = subprocess.run([MAKE, *arguments], cwd=self.root, env=env or self.env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def install_capture(self, path):
        path.write_text(CAPTURE)
        path.chmod(0o755)

    def source_patch(self, name, before="fixture", after="patched"):
        path = self.root / "patches/llvm" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("--- a/placeholder\n+++ b/placeholder\n@@ -1 +1 @@\n-" + before +
                        "\n\\ No newline at end of file\n+" + after + "\n\\ No newline at end of file\n")
        return path

    def install_wrapper(self, name, template, prefix=None):
        prefix = prefix or Path(self.temporary.name) / "relocated tools' path"
        (prefix / "bin").mkdir(parents=True, exist_ok=True)
        (prefix / "libexec").mkdir(exist_ok=True)
        script = (ROOT / "files/toolchain" / template).read_text()
        path = prefix / "bin" / name
        path.write_text(script.replace("@TARGET@", "x86_64-linux-musl").replace("@RESOURCE_VERSION@", "21"))
        path.chmod(0o755)
        return path

    def test_configuration_and_command_line_overrides(self):
        result = self.run_make("show-config", "ARCH=aarch64", "JOBS=1")
        self.assertIn("TARGET=aarch64-linux-musl", result.stdout)
        self.assertIn("JOBS=1", result.stdout)
        self.assertIn(f"PREFIX={self.root}/build/aarch64-linux-musl\n", result.stdout)
        self.assertIn(f"BUILD_DIR={self.root}/build/work/aarch64-linux-musl\n", result.stdout)
        self.assertFalse((self.root / "build").exists())

    def test_invalid_configuration_fails_before_work(self):
        for arguments in (("ARCH=mips",), ("JOBS=00",), ("JOBS=-2",), ("LINK_JOBS=1:2",),
                          ("PREFIX=/",), ("BUILD_DIR=/tmp/../home",), ("LLVM_MODE=other",),
                          ("TARGET=aarch64-linux-musl",), ("PREFIX=/tmp/tools with spaces",),
                          ("PREFIX=/tmp/tools$$variable",)):
            with self.subTest(arguments=arguments):
                self.run_make("show-config", *arguments, success=False)
        self.assertFalse((self.root / "build").exists())

    def test_old_system_clang_is_rejected_before_fetch(self):
        result = self.run_make("runtimes", success=False,
                               env={**self.env, "FAKE_CLANG_VERSION": "20.1.8"})
        self.assertIn("requires Clang 21 or newer", result.stdout)
        self.assertFalse((self.root / "sources").exists())

    def test_fetch_verifies_and_skips_downloaded_archives(self):
        self.run_make("pull")
        self.assertEqual(sum(item["tool"] == "curl" for item in self.commands()), 4)
        self.run_make("pull", "verify-sources")
        self.assertEqual(sum(item["tool"] == "curl" for item in self.commands()), 4)

    def test_corrupt_cache_is_repaired(self):
        self.run_make("pull")
        (self.root / "sources/musl-test.tar.gz").write_text("corrupt")
        self.run_make("verify-sources", success=False)
        self.run_make("pull", "verify-sources")
        self.assertEqual(sum(item["tool"] == "curl" for item in self.commands()), 5)

    def test_bad_or_failed_download_is_never_published(self):
        for setting in ("FAKE_CURL_BAD", "FAKE_CURL_FAIL"):
            with self.subTest(setting=setting):
                env = {**self.env, setting: "1"}
                self.run_make("pull", success=False, env=env)
                self.assertEqual(list((self.root / "sources").iterdir()), [])

    def test_full_driver_resumes_and_rejects_changed_configuration(self):
        self.run_make("runtimes")
        first = len([item for item in self.commands() if item["tool"] in ("make", "cmake")])
        self.run_make("runtimes", "JOBS=1")
        second = len([item for item in self.commands() if item["tool"] in ("make", "cmake")])
        self.assertEqual(first, second)
        self.run_make("runtimes", "TARGET_CFLAGS=-Os", success=False)
        self.run_make("clean")
        self.assertFalse((self.root / "build/x86_64-linux-musl").exists())
        self.assertTrue((self.root / "sources/musl-test.tar.gz").exists())

    def test_failed_stage_resumes_without_rebuilding_headers(self):
        self.run_make("runtimes", success=False, env={**self.env, "FAKE_FAIL_STAGE": "builtins"})
        self.assertTrue((self.root / "build/work/x86_64-linux-musl/stamps/headers").exists())
        self.assertFalse((self.root / "build/work/x86_64-linux-musl/stamps/builtins").exists())
        self.run_make("runtimes")
        self.assertEqual(sum("headers_install" in item["args"] for item in self.commands()), 1)

    def test_source_mode_uses_installed_host_tools(self):
        self.run_make("runtimes", "LLVM_MODE=source")
        prefix = self.root / "build/x86_64-linux-musl"
        self.assertEqual(os.readlink(prefix / "libexec/clang"), "../host/bin/clang")
        self.assertTrue((prefix / "bin/x86_64-linux-musl-c++").exists())

    def test_builtins_find_libunwind_headers_before_installation(self):
        for arch in ("x86_64", "aarch64"):
            for mode in ("system", "source"):
                with self.subTest(arch=arch, mode=mode):
                    name = arch + "-" + mode
                    prefix = self.root / "build" / name
                    work = self.root / "build/work" / name
                    self.run_make("builtins", "ARCH=" + arch, "LLVM_MODE=" + mode,
                                  "PREFIX=" + str(prefix), "BUILD_DIR=" + str(work),
                                  "TARGET_CFLAGS=-Os")
                    self.assertFalse((prefix / "sysroot/usr/include/unwind.h").exists())
                    options = json.loads((work / "builtins/fixture-config.json").read_text())
                    directories = [option.split("=", 1)[1] for option in options
                                   if option.startswith("-DCMAKE_C_STANDARD_INCLUDE_DIRECTORIES=")]
                    self.assertEqual(len(directories), 1)
                    include = Path(directories[0])
                    self.assertEqual(include, self.root / "build/src/llvm-test/libunwind/include")
                    for line in (include / "unwind.h").read_text().splitlines():
                        header = line.removeprefix("#include <").removesuffix(">")
                        self.assertTrue((include / header).is_file(), header)
                    flags = next(option for option in options if option.startswith("-DCMAKE_C_FLAGS="))
                    self.assertIn("-Os", flags)
                    self.assertIn("--gcc-toolchain=", flags)
                    self.assertIn("-resource-dir=", flags)

    def test_source_patches_apply_once_in_order_and_are_installed(self):
        self.source_patch("10-second.patch", "first", "second")
        self.source_patch("00-first.patch", "fixture", "first")
        result = self.run_make("runtimes")
        source = self.root / "build/src/llvm-test"
        self.assertEqual((source / "placeholder").read_text(), "second")
        self.assertLess(result.stdout.index("Applying 00-first.patch"), result.stdout.index("Applying 10-second.patch"))
        installed = self.root / "build/x86_64-linux-musl/share/musllvm/patches/llvm/00-first.patch"
        self.assertEqual(installed.read_bytes(), (self.root / "patches/llvm/00-first.patch").read_bytes())
        self.assertNotIn("Applying", self.run_make("runtimes", "JOBS=1").stdout)

    def test_changed_or_removed_patch_rejects_cached_sources(self):
        patch = self.source_patch("00-fixture.patch")
        self.run_make("runtimes")
        commands = sum(item["tool"] in ("make", "cmake") for item in self.commands())
        self.source_patch("00-fixture.patch", after="changed")
        result = self.run_make("runtimes", success=False)
        self.assertIn("source or patches changed", result.stdout)
        patch.unlink()
        result = self.run_make("runtimes", success=False)
        self.assertIn("source or patches changed", result.stdout)
        self.assertEqual(sum(item["tool"] in ("make", "cmake") for item in self.commands()), commands)
        self.assertEqual((self.root / "build/src/llvm-test/placeholder").read_text(), "patched")

    def test_failed_source_patch_does_not_publish_extraction(self):
        self.source_patch("00-broken.patch", before="missing")
        result = self.run_make("runtimes", success=False)
        self.assertIn("could not apply", result.stdout)
        self.assertFalse((self.root / "build/src/llvm-test").exists())
        self.assertFalse((self.root / "build/src/llvm-test.lock").exists())
        self.assertTrue((self.root / "sources/llvm-test.tar.gz").exists())
        self.assertFalse(any(item["tool"] in ("make", "cmake") for item in self.commands()))

    def test_chimera_runtime_settings_preserve_target_flags(self):
        for arch in ("x86_64", "aarch64"):
            with self.subTest(arch=arch):
                self.run_make("runtimes", "ARCH=" + arch, "TARGET_CFLAGS=-Os")
                work = self.root / "build/work" / (arch + "-linux-musl")
                options = json.loads((work / "runtimes/fixture-config.json").read_text())
                self.assertIn("-DLIBCXX_HARDENING_MODE=fast", options)
                self.assertIn("-DLIBCXX_TYPEINFO_COMPARISON_IMPLEMENTATION=2", options)
                calls = [item for item in self.commands() if item["tool"] == "make" and str(work / "atomic") in item["args"]]
                self.assertEqual(len(calls), 2)
                for call in calls:
                    flags = next(argument for argument in call["args"] if argument.startswith("CFLAGS="))
                    self.assertEqual(flags, "CFLAGS=-Os" + (" -mno-outline-atomics" if arch == "aarch64" else ""))

    def test_clean_preserves_unmarked_directory(self):
        prefix = self.root / "unrelated"
        prefix.mkdir()
        sentinel = prefix / "keep"
        sentinel.write_text("user data")
        self.run_make("clean", f"PREFIX={prefix}", success=False)
        self.assertEqual(sentinel.read_text(), "user data")

    def test_concurrent_build_is_rejected(self):
        self.run_make("runtimes")
        (self.root / "build/work/x86_64-linux-musl/lock").mkdir()
        self.run_make("runtimes", success=False)
        self.run_make("clean", success=False)

    def test_cxx_wrapper_relocation_and_host_isolation(self):
        wrapper = self.install_wrapper("x86_64-linux-musl-c++", "cc.sh")
        self.install_capture(wrapper.parent.parent / "libexec/clang")
        env = {**self.env, "CPATH": "/host/headers", "LIBRARY_PATH": "/host/libraries"}
        result = subprocess.check_output([str(wrapper), "source with spaces.cpp"], env=env, text=True)
        invocation = json.loads(result)
        self.assertIn("--driver-mode=g++", invocation["args"])
        self.assertIn(f"--config={wrapper.parent.parent}/share/musllvm/clang.cfg", invocation["args"])
        self.assertIn("source with spaces.cpp", invocation["args"])
        self.assertIn(f"--sysroot={wrapper.parent.parent}/sysroot", invocation["args"])
        self.assertNotIn("CPATH", invocation["env"])
        self.assertNotIn("LIBRARY_PATH", invocation["env"])

    def test_wrapper_omits_default_libraries_for_compile_only_and_freestanding(self):
        wrapper = self.install_wrapper("x86_64-linux-musl-cc", "cc.sh")
        self.install_capture(wrapper.parent.parent / "libexec/clang")
        for option in ("-c", "-E", "-nostdlib", "-nodefaultlibs"):
            with self.subTest(option=option):
                invocation = json.loads(subprocess.check_output([str(wrapper), option, "source.c"], env=self.env, text=True))
                self.assertNotIn("-latomic", invocation["args"])

    def test_sysroot_override_applies_to_compiler_and_pkg_config(self):
        wrapper = self.install_wrapper("x86_64-linux-musl-cc", "cc.sh")
        self.install_capture(wrapper.parent.parent / "libexec/clang")
        env = {**self.env, "MUSLLVM_SYSROOT": "/another/sysroot"}
        invocation = json.loads(subprocess.check_output([str(wrapper), "source.c"], env=env, text=True))
        self.assertIn("--sysroot=/another/sysroot", invocation["args"])
        pkg_wrapper = self.install_wrapper("x86_64-linux-musl-pkg-config", "pkg-config.sh")
        self.install_capture(self.tools / "pkg-config")
        invocation = json.loads(subprocess.check_output([str(pkg_wrapper), "--libs", "target"], env=env, text=True))
        self.assertEqual(invocation["env"]["PKG_CONFIG_SYSROOT_DIR"], "/another/sysroot")

    def test_environment_output_is_safe_to_evaluate(self):
        wrapper = self.install_wrapper("x86_64-linux-musl-env", "env.sh")
        result = subprocess.check_output(["sh", "-c", 'eval "$("$1")"; printf "%s\\n%s\\n" "$CC" "$CMAKE_TOOLCHAIN_FILE"',
                                          "test", str(wrapper)], env=self.env, text=True)
        self.assertEqual(result.splitlines(), [str(wrapper.parent / "x86_64-linux-musl-cc"),
                                             str(wrapper.parent.parent / "share/musllvm/toolchain.cmake")])

    def test_pkg_config_cannot_see_host_packages(self):
        wrapper = self.install_wrapper("x86_64-linux-musl-pkg-config", "pkg-config.sh")
        self.install_capture(self.tools / "pkg-config")
        env = {**self.env, "PKG_CONFIG_PATH": "/host/packages", "PKG_CONFIG_LIBDIR": "/host/packages"}
        invocation = json.loads(subprocess.check_output([str(wrapper), "--libs", "target"], env=env, text=True))
        self.assertEqual(invocation["env"]["PKG_CONFIG_PATH"], "")
        self.assertEqual(invocation["env"]["PKG_CONFIG_SYSROOT_DIR"], str(wrapper.parent.parent / "sysroot"))
        self.assertNotIn("/host/packages", invocation["env"]["PKG_CONFIG_LIBDIR"])


if __name__ == "__main__":
    unittest.main()
