import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parent.parent


def check_static_elf(path, arch):
    machines = {"x86_64": 62, "aarch64": 183}
    if arch not in machines:
        raise ValueError("unsupported host architecture: " + arch)
    with path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        header = stream.read(64)
        if len(header) != 64 or header[:6] != b"\x7fELF\x02\x01" or header[6] != 1:
            raise ValueError("host tool is not a little-endian ELF64 executable: " + str(path))
        fields = struct.unpack("<HHIQQQIHHHHHH", header[16:])
        kind, machine, version, entry, offset = fields[:5]
        header_size, stride, count = fields[7:10]
        if kind not in (2, 3) or not entry or version != 1 or machine != machines[arch]:
            raise ValueError("wrong host ELF type or architecture: " + str(path))
        if header_size != 64 or stride != 56 or not count or offset < 64 or offset + stride * count > size:
            raise ValueError("invalid host ELF program headers: " + str(path))
        loaded = False
        for index in range(count):
            stream.seek(offset + stride * index)
            segment = struct.unpack("<IIQQQQQQ", stream.read(56))
            tag, _, start, _, _, length, _, _ = segment
            if start + length > size:
                raise ValueError("truncated host ELF segment: " + str(path))
            if tag == 3:
                raise ValueError("host tool needs a dynamic loader: " + str(path))
            loaded |= tag == 1
            if tag == 2:
                if not length or length % 16:
                    raise ValueError("invalid host ELF dynamic section: " + str(path))
                stream.seek(start)
                for _ in range(length // 16):
                    dynamic_tag, _ = struct.unpack("<qQ", stream.read(16))
                    if dynamic_tag == 0:
                        break
                    if dynamic_tag in (1, 0x7fffffff, 0x7ffffffd):
                        raise ValueError("host tool needs a shared library: " + str(path))
                else:
                    raise ValueError("unterminated host ELF dynamic section: " + str(path))
        if not loaded:
            raise ValueError("host tool has no loadable segment: " + str(path))


def check_static_host(prefix, arch=None):
    prefix = prefix.resolve()
    tools = prefix / "host/bin"
    for required in ("clang", "clang++", "ld.lld", "llvm-ar", "llvm-readelf"):
        if not (tools / required).is_file():
            raise ValueError("missing host tool: " + required)
    seen = set()
    for path in sorted(tools.iterdir()):
        if not path.is_file() or not path.stat().st_mode & 0o111:
            raise ValueError("host tool is not executable: " + str(path))
        try:
            path.resolve(strict=True).relative_to(prefix)
        except (ValueError, OSError, RuntimeError) as error:
            raise ValueError("host tool points outside the toolchain: " + str(path)) from error
        identity = (path.stat().st_dev, path.stat().st_ino)
        if identity not in seen:
            check_static_elf(path, arch or platform.machine())
            seen.add(identity)


def source_licenses(manifest, source_root, root):
    licenses = {}
    for line in manifest.decode().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        component, archive, *_ = line.split()
        for value in (component, archive):
            if value in (".", "..") or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in value):
                raise ValueError("invalid source name: " + value)
        directory = source_root / archive.rsplit(".tar.", 1)[0]
        if not directory.is_dir():
            raise ValueError("missing extracted source: " + str(directory))
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(directory)
            if (path.name.upper().startswith(("LICENSE", "COPYING", "COPYRIGHT", "NOTICE"))
                    or relative.parts[0].upper() == "LICENSES") and path.is_file():
                licenses[root + "/share/musllvm/licenses/" + component + "/" + relative.as_posix()] = path.read_bytes()
    return licenses


def package(prefix, target, sources, output, source_root=None, llvm_mode="source"):
    if not target or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in target):
        raise ValueError("invalid target: " + target)
    if platform.system() != "Linux":
        raise ValueError("packaging requires a Linux host")
    prefix = prefix.resolve()
    if llvm_mode not in ("source", "static"):
        raise ValueError("packaging requires source or static LLVM")
    mode = prefix / "share/musllvm/llvm-mode"
    if mode.exists() and mode.read_text().strip() != llvm_mode:
        raise ValueError("LLVM_MODE does not match the installed toolchain")
    if llvm_mode == "static":
        if not mode.is_file():
            raise ValueError("static LLVM build marker is missing")
        check_static_host(prefix)
    for required in ("host/bin/clang", "host/bin/ld.lld", "bin/" + target + "-cc",
                     "sysroot/usr/lib/libc.so", "share/musllvm/resource-version"):
        if not (prefix / required).is_file():
            raise ValueError("incomplete toolchain: " + required)
    for path in prefix.rglob("*"):
        if path.is_symlink():
            if os.path.isabs(os.readlink(path)):
                raise ValueError("absolute symlink: " + str(path))
            try:
                path.resolve(strict=True).relative_to(prefix)
            except (ValueError, FileNotFoundError, RuntimeError) as error:
                raise ValueError("symlink outside the toolchain or missing its target: " + str(path)) from error

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    epoch = int(subprocess.check_output(["git", "show", "-s", "--format=%ct", commit], cwd=ROOT, text=True))
    host = platform.machine() + "-linux"
    libc_name, libc_version = platform.libc_ver()
    manifest = sources.read_bytes()
    metadata = {
        "commit": commit,
        "host": host,
        "host_libc": {"name": libc_name, "version": libc_version},
        "target": target,
        "llvm_mode": llvm_mode,
        "source_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
    }
    if llvm_mode == "static":
        metadata["build_host_libc"] = metadata["host_libc"]
        metadata["host_libc"] = {"name": "musl"}
        metadata["host_linkage"] = "static"
    root = "musllvm-" + target
    generated = {
        root + "/share/musllvm/sources.list": manifest,
        root + "/share/musllvm/build-info.json": (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode(),
    }
    generated.update(source_licenses(manifest, source_root or ROOT / "build/src", root))

    def normalize(info):
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = epoch
        return info

    def installed(info):
        if info.name == root + "/.musllvm-config" or info.name in generated:
            return None
        return normalize(info)

    output.mkdir(parents=True, exist_ok=True)
    archive = output / (root + "-host-" + host + ".tar.xz")
    descriptor, temporary = tempfile.mkstemp(prefix=".package-", dir=output)
    os.close(descriptor)
    try:
        with tarfile.open(temporary, "w:xz", dereference=False) as stream:
            stream.add(prefix, arcname=root, filter=installed)
            for name, content in generated.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o644
                stream.addfile(normalize(info), io.BytesIO(content))
        os.replace(temporary, archive)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    archive.with_name(archive.name + ".sha256").write_text(digest.hexdigest() + "  " + archive.name + "\n")
    return archive


def main():
    parser = argparse.ArgumentParser(description="Package a toolchain with bundled host tools")
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--target")
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--llvm-mode", choices=("source", "static"), default="source")
    parser.add_argument("--check-host", action="store_true")
    args = parser.parse_args()
    if not args.check_host and not all((args.target, args.sources, args.output)):
        parser.error("packaging requires --target, --sources and --output")
    try:
        if args.check_host:
            check_static_host(args.prefix)
            print("Verified static host tools: " + str(args.prefix))
        else:
            print(package(args.prefix, args.target, args.sources, args.output, llvm_mode=args.llvm_mode))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, "package: " + str(error) + "\n")


if __name__ == "__main__":
    main()
