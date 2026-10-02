#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Build a VMD/GSC test initramfs without installing a driver or changing /boot."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
from initramfs_checks import verify_image

HERE = Path(__file__).resolve().parent
KERNEL = "7.2.7-arch1-1"
SOURCE_SHA256 = "cf7a4795ff83d1a3f131af7d9323d427fde3881a58fc20ed4c1d1ea48280e725"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    if os.geteuid() == 0:
        raise SystemExit("Run this build as your normal user, without sudo.")
    if os.uname().release != KERNEL:
        raise SystemExit(f"This test is for {KERNEL}; the running kernel has changed.")
    headers = Path("/usr/lib/modules") / KERNEL / "build"
    if not (headers / "Makefile").is_file():
        raise SystemExit("Matching headers are missing. Run: sudo pacman -S linux-headers")
    release = run("make", "-s", "-C", str(headers), "kernelrelease", capture_output=True, text=True).stdout.strip()
    if release != KERNEL:
        raise SystemExit(f"Header version mismatch: {release}")
    if Path("/sys/bus/pci/devices/0000:00:0e.0/device").read_text().strip() != "0x7d0b":
        raise SystemExit("The VMD controller is different from the controller this patch targets.")
    if Path("/sys/module/module/parameters/sig_enforce").read_text().strip() != "N":
        raise SystemExit("Module signature enforcement is enabled; this unsigned test module cannot be used.")
    lockdown = Path("/sys/kernel/security/lockdown")
    if lockdown.exists() and "[none]" not in lockdown.read_text():
        raise SystemExit("Kernel lockdown is enabled; this unsigned test module cannot be used.")
    work = HERE / "vmd-build"
    work.mkdir(exist_ok=True)
    image = HERE / "initramfs-linux-vmd-gsc-test.img"
    manifest_path = Path(str(image) + ".json")
    manifest_path.unlink(missing_ok=True)
    source_path = HERE / "vmd-linux-7.2.7.c"
    data = source_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise SystemExit("The verified 7.2.7 source changed. No system files have been changed.")
    source = data.decode("utf-8")
    (work / "source-url.txt").write_text("https://raw.githubusercontent.com/gregkh/linux/v7.2.7/drivers/pci/controller/vmd.c\n")
    for stale in ["vmd.c.rej", "vmd.c.orig"]:
        (work / stale).unlink(missing_ok=True)
    (work / "vmd-original.c").write_text(source)
    (work / "vmd.c").write_text(source)
    run("patch", "--batch", "--fuzz=0", "-p1", "-i", str(HERE / "vmd-mtl016-backport.patch"), cwd=work)
    (work / "Makefile").write_text("obj-m := vmd.o\n")
    print("Building the driver against the installed kernel's matching headers...", flush=True)
    run("make", "-C", str(headers), f"M={work}", "-j4", "modules")
    module = work / "vmd.ko"
    version = run("modinfo", "-F", "version", str(module), capture_output=True, text=True).stdout.strip()
    vermagic = run("modinfo", "-F", "vermagic", str(module), capture_output=True, text=True).stdout.strip()
    if version != "0.6-mtl016-test" or vermagic.split()[0] != KERNEL:
        raise SystemExit("Built module validation failed; no system files have been changed.")
    module_root = work / "module-root"
    if module_root.exists():
        shutil.rmtree(module_root)
    target = module_root / "usr/lib/modules" / KERNEL
    target.mkdir(parents=True)
    (module_root / "lib").symlink_to("usr/lib")
    installed = Path("/usr/lib/modules") / KERNEL

    for child in installed.iterdir():
        dest = target / child.name
        if child.name in {"build", "source"}:
            continue
        if child.is_dir():
            # mkinitcpio preserves module symlinks in the archive. A link to
            # /usr/lib/modules/... points back to itself during early boot.
            # Stage actual bytes so the image is self-contained.
            shutil.copytree(child, dest, symlinks=False, copy_function=shutil.copyfile)
        elif child.name.startswith("modules."):
            # These are real private copies: depmod must never write through
            # a symlink to the installed kernel's metadata.
            if child.name in {"modules.order", "modules.builtin", "modules.builtin.modinfo", "modules.builtin.ranges"}:
                shutil.copyfile(child, dest)
        else:
            shutil.copyfile(child, dest)
    driver_dir = target / "kernel/drivers/pci/controller"
    for old in driver_dir.glob("vmd.ko*"):
        old.unlink()
    shutil.copyfile(module, driver_dir / "vmd.ko")
    run("depmod", "-b", str(module_root), KERNEL)
    config = HERE / "mkinitcpio-vmd-gsc-test.conf"
    config.write_text(Path("/etc/mkinitcpio.conf").read_text() +
                      '\nMODULES=(mei mei_me mei_gsc_proxy "${MODULES[@]}")\n')
    temporary_image = HERE / "initramfs-linux-vmd-gsc-test.img.building"
    run("mkinitcpio", "-k", KERNEL, "-r", str(module_root), "-c", str(config), "-g", str(temporary_image), "--nopost")
    count = verify_image(temporary_image, KERNEL, version, expected_vmd=module)
    temporary_image.replace(image)
    manifest = {
        "kernel_release": KERNEL,
        "kernel_sha256": hashlib.sha256(Path("/boot/vmlinuz-linux").read_bytes()).hexdigest(),
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "module_version": version,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built and verified {count} real module files and early-boot dependencies:", image)
    print("Patched module SHA256:", hashlib.sha256(module.read_bytes()).hexdigest())
    print("Install the test image with: sudo python3", HERE / "install-test.py")


if __name__ == "__main__":
    main()
