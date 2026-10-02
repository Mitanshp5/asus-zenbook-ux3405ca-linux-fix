#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Install a separate systemd-boot test entry, preserving the existing entry."""
from datetime import datetime
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile

from initramfs_checks import verify_image

HERE = Path(__file__).resolve().parent
KERNEL = "7.2.7-arch1-1"
IMAGE = "initramfs-linux-vmd-gsc-test.img"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_entry(text):
    result = {}
    for line in text.splitlines():
        words = line.strip().split(None, 1)
        if len(words) == 2 and not words[0].startswith("#"):
            result.setdefault(words[0], []).append(words[1])
    return result


def atomic_copy(source, destination):
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".vmd-test-", delete=False) as file:
        temporary = Path(file.name)
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(0o644)
        if digest(source) != digest(temporary):
            raise RuntimeError(f"Copy verification failed: {destination.name}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-entry", required=True, type=Path,
                        help="Your existing working Linux .conf entry under /boot/loader/entries.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    boot = Path("/boot")
    entries = boot / "loader/entries"
    base = args.base_entry.resolve()
    if base.parent != entries.resolve() or base.suffix != ".conf" or not base.is_file():
        raise SystemExit("Use an existing systemd-boot Linux .conf entry under /boot/loader/entries.")
    if os.uname().release != KERNEL:
        raise SystemExit(f"This build is only for {KERNEL}. Nothing changed.")
    mount = subprocess.run(["findmnt", "-n", "-o", "TARGET,FSTYPE", "-T", str(boot)],
                           check=True, capture_output=True, text=True).stdout.split()
    if mount != ["/boot", "vfat"]:
        raise SystemExit("This installer requires a separate FAT Linux boot partition mounted at /boot.")
    original = base.read_text()
    values = parse_entry(original)
    kernels = values.get("linux", [])
    initrds = values.get("initrd", [])
    options = values.get("options", [])
    if len(kernels) != 1 or len(options) != 1 or not initrds:
        raise SystemExit("Unsupported Linux entry format. Nothing changed.")
    if not any(part.startswith("root=") for part in options[0].split()):
        raise SystemExit("The selected entry has no Linux root option. Nothing changed.")
    def boot_file(reference):
        path = (boot / reference.lstrip("/")).resolve()
        if not path.is_relative_to(boot) or not path.is_file():
            raise SystemExit(f"Invalid boot file in selected entry: {reference}")
        return path
    kernel = boot_file(kernels[0])
    original_initrds = [boot_file(reference) for reference in initrds]
    # This workaround uses the standard mkinitcpio image, including microcode.
    # Only an optional separate Intel microcode image is retained from the entry.
    if len(initrds) > 2 or (len(initrds) == 2 and initrds[0] != "/intel-ucode.img"):
        raise SystemExit("Unsupported initrd sequence. Review and install manually.")
    image = HERE / IMAGE
    manifest = json.loads(Path(str(image) + ".json").read_text())
    if manifest["kernel_release"] != KERNEL or manifest["module_version"] != "0.6-mtl016-test":
        raise SystemExit("Build verification manifest mismatch. Nothing changed.")
    if digest(image) != manifest["image_sha256"] or digest(kernel) != manifest["kernel_sha256"]:
        raise SystemExit("The kernel/image changed after building. Nothing changed.")
    count = verify_image(image, KERNEL, manifest["module_version"])
    test_entry = entries / "arch-vmd-gsc-test.conf"
    test_kernel = boot / "vmlinuz-linux-vmd-gsc-test"
    test_image = boot / IMAGE
    if any(path.exists() for path in [test_entry, test_kernel, test_image]):
        raise SystemExit("A destination already exists. This installer refuses to overwrite it.")
    lines = ["title Arch Linux (VMD + GSC test)", f"linux /{test_kernel.name}"]
    if len(initrds) == 2:
        lines.append("initrd /intel-ucode.img")
    lines += [f"initrd /{test_image.name}", f"options {options[0]}"]
    content = "\n".join(lines) + "\n"
    print(f"Verified {count} actual driver files and early-boot dependencies.")
    print("New test entry:\n" + content)
    print("The existing entry and boot default are preserved.")
    if args.dry_run:
        return
    if os.geteuid() != 0:
        raise SystemExit("Run the installation with sudo from your normal terminal.")
    mount_options = subprocess.run(["findmnt", "-n", "-o", "OPTIONS", "-T", str(boot)],
                                   check=True, capture_output=True, text=True).stdout.split(",")
    if "ro" in mount_options:
        raise SystemExit("/boot is read-only. Nothing changed.")
    if shutil.disk_usage(boot).free < image.stat().st_size + kernel.stat().st_size + 16 * 1024 * 1024:
        raise SystemExit("Not enough free space on /boot. Nothing changed.")
    protected = {path: digest(path) for path in [base, kernel, *original_initrds, boot / "loader/loader.conf"]}
    backup = HERE / "boot-entry-backups" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(base, backup / base.name)
    shutil.copyfile(boot / "loader/loader.conf", backup / "loader.conf")
    created = []
    try:
        for source, destination in [(kernel, test_kernel), (image, test_image)]:
            atomic_copy(source, destination)
            created.append(destination)
        with tempfile.TemporaryDirectory(prefix="vmd-entry-") as directory:
            entry_source = Path(directory) / "entry.conf"
            entry_source.write_text(content)
            atomic_copy(entry_source, test_entry)
            created.append(test_entry)
        os.sync()
        if any(digest(path) != expected for path, expected in protected.items()):
            raise RuntimeError("An existing boot file changed during installation.")
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        os.sync()
        raise
    print("Installed. Select Arch Linux (VMD + GSC test) for one boot.")
    print("Rollback: select your original Linux entry. No live driver was replaced.")


if __name__ == "__main__":
    main()
