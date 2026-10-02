# SPDX-License-Identifier: GPL-2.0-only
"""Verify actual early-boot drivers without loading any live kernel module."""
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile


def output(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def verify_image(image, kernel, vmd_version, expected_vmd=None):
    with tempfile.TemporaryDirectory(prefix="zenbook-initramfs-check-") as directory:
        root = Path(directory)
        subprocess.run(["lsinitcpio", "-x", str(image)], cwd=root,
                       stdout=subprocess.DEVNULL, check=True)
        modules = root / "usr/lib/modules" / kernel
        files = sorted(modules.rglob("*.ko*"))
        if not files:
            raise SystemExit("The initramfs contains no kernel module files.")
        names = set()
        for path in files:
            # Path.exists() follows absolute links into the running system,
            # which concealed the broken image. Inspect the archive entry itself.
            if not stat.S_ISREG(path.lstat().st_mode):
                raise SystemExit(f"Invalid initramfs module: {path.relative_to(root)} is not a regular file.")
            name = path.name.split(".ko", 1)[0].replace("-", "_")
            names.add(name)
            vermagic = output("modinfo", "-F", "vermagic", str(path)).split()
            if not vermagic or vermagic[0] != kernel:
                raise SystemExit(f"Kernel version mismatch in {path.name}.")
            if name == "vmd":
                version = output("modinfo", "-F", "version", str(path)).strip()
                if version != vmd_version:
                    raise SystemExit(f"Unexpected VMD version in image: {version}")
                if expected_vmd is not None and path.read_bytes() != expected_vmd.read_bytes():
                    raise SystemExit("The image's VMD module differs from the compiled module.")
            else:
                installed = Path("/usr/lib/modules") / kernel / path.relative_to(modules)
                if not installed.is_file() or path.read_bytes() != installed.read_bytes():
                    raise SystemExit(f"The image's {path.name} differs from the installed kernel module.")
        required = {"vmd", "nvme", "nvme_core", "mei", "mei_me", "mei_gsc_proxy", "i915"}
        if missing := required - names:
            raise SystemExit(f"Missing initramfs modules: {sorted(missing)}")
        # --show-depends only resolves files; it never loads a driver. Check that
        # all dependencies resolve to files inside this extracted image.
        for name in sorted(required | {"ext4"}):
            dependencies = output("modprobe", "--show-depends", "--dirname", str(root),
                                  "--set-version", kernel, "--config", "/dev/null", name)
            for line in dependencies.splitlines():
                words = shlex.split(line)
                if words and words[0] == "insmod":
                    dependency = Path(words[1]).resolve()
                    if not dependency.is_relative_to(root) or not dependency.is_file():
                        raise SystemExit(f"Dependency for {name} is unavailable inside the image: {line}")
        return len(files)
