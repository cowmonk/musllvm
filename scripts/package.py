import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parent.parent


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


def package(prefix, target, sources, output, source_root=None):
    if not target or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in target):
        raise ValueError("invalid target: " + target)
    if platform.system() != "Linux":
        raise ValueError("packaging requires a Linux host")
    prefix = prefix.resolve()
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
        "llvm_mode": "source",
        "source_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
    }
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
    parser.add_argument("--target", required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(package(args.prefix, args.target, args.sources, args.output))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, "package: " + str(error) + "\n")


if __name__ == "__main__":
    main()
