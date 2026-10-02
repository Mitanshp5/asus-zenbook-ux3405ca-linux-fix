# ASUS Zenbook UX3405CA: Linux slow boot, NVMe timeouts and Intel GSC fix

An Arch Linux workaround tested on an **ASUS Zenbook 14 UX3405CA**, with an
**Intel Core Ultra 9 285H**, **Intel VMD `8086:7d0b`**, and a **Micron 2500 NVMe SSD**.

Repeated `nvme ... timeout, completion polled` errors caused 30-second storage
stalls, slow boot and applications such as Firefox hanging during startup.
Separately, Intel graphics logged `GSC proxy component didn't bind within the
expected timeout` because the MEI proxy modules loaded too late.

The combined workaround reduced one measured boot from **3m19s to 14.907s total**,
eliminated the NVMe timeout messages in the successful boot, and made the GSC
proxy bind at **2.443s**. This is a single-machine result, not a guarantee for
other systems. Firefox's independent post-fix launch time was not measured.

## Tested configuration

| Component | Tested value |
| --- | --- |
| Laptop | ASUS Zenbook 14 UX3405CA / UX3405CA_UX3405CA |
| CPU / memory | Intel Core Ultra 9 285H / 32 GB |
| BIOS | UX3405CA.316 |
| Linux | Arch Linux, `7.2.7-arch1-1` |
| Headers | `linux-headers 7.2.7.arch1-1` |
| VMD controller | Intel `8086:7d0b` |
| SSD | Micron 2500, `MTFDKBA1T0QGN-1BN1AABGA` |
| SSD firmware | `V8MA000` |
| Graphics | Intel `8086:7d51`, i915 |
| Initramfs / boot loader | mkinitcpio 42.1 / systemd-boot |
| Desktop | Hyprland on Wayland |

## What changes

1. **VMD interrupt ordering:** backport the child-device configuration read from
   the upstream MTL016 workaround. Before dispatching an interrupt, read the
   initiating PCI child's configuration space under `cfg_lock`. The backport
   enables this only for device `7d0b`; the older driver has no stored
   `vmd->features` member, so it checks the device ID directly.
2. **Early GSC proxy binding:** include `mei`, `mei_me` and `mei_gsc_proxy` in the
   initramfs `MODULES` array alongside the existing modules.

This builds a separate VMD module and a separate initramfs. The test installer
adds a separate systemd-boot entry and a matching kernel copy. It preserves the
existing Linux entry, original kernel/initramfs and boot default. It makes no
BIOS, VMD firmware setting, partition, Windows driver, Windows boot file or EFI
variable changes. It does not unload or replace the running storage driver.

The tested setup already had `nvme_core.default_ps_max_latency_us=0`. That alone
did not fix the stalls. A boot with `pcie_aspm=off` also still had timeouts. The
successful test did not use `pcie_aspm=off`.

## Scope and prerequisites

- The scripts deliberately target **`7.2.7-arch1-1` and VMD `8086:7d0b`**. They
  refuse a different kernel, mismatched headers or a different VMD device.
- The installer supports systemd-boot `.conf` entries on a separate FAT Linux
  boot partition mounted at `/boot`. GRUB, UKIs and other layouts need their own
  integration; do not run this installer against them.
- The module is unsigned. The builder refuses enforced module signatures or
  kernel lockdown. This project does not include module signing support.
- Install matching headers and the usual Arch build tools: `base-devel`,
  `linux-headers`, `python`, `kmod` and `mkinitcpio`. Follow Arch's supported
  package-update procedure and boot the kernel that matches your headers.
  The `--needed` package option does not pin package versions. Do not downgrade
  or perform a partial upgrade merely to run this historical backport.

If your current supported kernel already contains the workaround, use its stock
driver. This repository records the exact tested backport, not compatibility
with every later kernel. Read the patch and upstream discussion before adapting
it to another kernel or controller.

## Build

```bash
git clone https://github.com/Mitanshp5/asus-zenbook-ux3405ca-linux-fix.git
cd asus-zenbook-ux3405ca-linux-fix
sha256sum -c SOURCE.sha256
python3 build-vmd-test.py
```

Build as your normal user, **without sudo**. The complete original Linux 7.2.7
`vmd.c` is included and verified against its pinned SHA256. The patch must apply
with no fuzzy matching. Build artifacts stay in the repository directory.

The builder stages real copies of the installed kernel modules, replaces VMD
only in that private tree, and runs mkinitcpio with `--nopost`. It extracts the
result and checks all module files, kernel versions, stock module bytes,
the exact patched VMD bytes, and dependency resolution for VMD, NVMe, MEI,
i915 and ext4. Verification uses `modprobe --show-depends`, never insertion.

Do not use a `.ko` or initramfs downloaded from someone else's machine. Build
against your matching kernel and headers. No built binaries or personal boot
configuration are distributed here.

## Install one test entry

Identify your current Linux entry under `/boot/loader/entries`. Replace
`arch.conf` below if your existing entry has a different name. Its own root,
filesystem and other kernel options are retained; no example disk UUID is used.

```bash
python3 install-test.py --base-entry /boot/loader/entries/arch.conf --dry-run
sudo python3 install-test.py --base-entry /boot/loader/entries/arch.conf
```

The installer checks the built image and kernel again, requires free boot
partition space, refuses existing destination files, and copies the matching
kernel before creating `arch-vmd-gsc-test.conf`. Reboot and select
**Arch Linux (VMD + GSC test)**. Keep your original entry available for rollback.

## Verify the boot

```bash
cat /sys/module/vmd/version
systemd-analyze
journalctl -b -k -o short-monotonic --no-pager \
  | rg 'nvme.*timeout|GSC proxy|mei_gsc_proxy'
```

The VMD version should be `0.6-mtl016-test`. On the tested machine, the GSC proxy
bound early and NVMe timeout messages disappeared. See
[the sanitized result](docs/tested-results.md).

After verifying your own successful boot, you can set
`default arch-vmd-gsc-test.conf` in `/boot/loader/loader.conf`. Preserve the other
loader settings and original Linux entry. Roll back by selecting the original
entry and restoring its default if needed.

The test entry uses its own matching kernel copy. A package update will not
update that selected kernel automatically. Rebuild and validate the fix for a
new kernel before moving to it; this project has no DKMS or automatic update
integration. Do not leave a historical kernel selected indefinitely.

## Upstream work and related reports

This backport adapts existing upstream work; the hardware diagnosis and interrupt
ordering fix were not invented here.

- [Rickey Bartlett's PCI/VMD patch and review](https://lore-kernel.gnuweeb.org/linux-pci/178835209832.79920.2886314748680261549.b4-ty@b4/T/):
  implements the initiating-device read, credits Kai-Heng Feng's original
  diagnosis and Keith Busch's ordering guidance. The upstream explanation
  identifies MTL016 as the cause of the same NVMe timeout pattern.
- [Kai-Heng Feng's earlier patch](https://lore.kernel.org/all/20240909082657.19660-1-kai.heng.feng@canonical.com/).
- [Report with the same ASUS model, CPU, SSD and firmware](https://discussion.fedoraproject.org/t/nvme-i-o-timeouts-and-slow-boot-on-asus-zenbook-with-micron-mtfdkba1t0qgn/187890).
- [VMD report with the same Micron 2500 firmware](https://lore-kernel.gnuweeb.org/linux-pci/CAH12Smk8jRCNtkWb%2B-6JJUegcYrH73X_Hv3KgnoWyARUMLmEgA%40mail.gmail.com/T/).
- [Original Linux 7.2.7 VMD source](https://raw.githubusercontent.com/gregkh/linux/v7.2.7/drivers/pci/controller/vmd.c).

The local backport is [vmd-mtl016-backport.patch](vmd-mtl016-backport.patch).
Linux's original source retains its Intel copyright and SPDX notice.
Repository code is distributed under **GPL-2.0-only**; see [LICENSE](LICENSE).

For issue reports, include laptop model, controller PCI ID, kernel and header
versions, SSD model/firmware and relevant timeout lines. Remove serial numbers,
disk UUIDs, usernames and other private data before posting logs.
