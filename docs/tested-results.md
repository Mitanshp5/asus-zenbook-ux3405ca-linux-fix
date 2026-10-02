# Sanitized ASUS UX3405CA test result

Reported on Arch Linux with `7.2.7-arch1-1`, Core Ultra 9 285H, VMD `8086:7d0b`,
Micron 2500 SSD (`V8MA000`) and i915 graphics. This is one machine's observed
result. Device serial numbers, disk UUIDs, usernames and full system logs are
omitted.

| Observation | Stock / earlier test | Corrected VMD + GSC setup |
| --- | --- | --- |
| Total startup | 3m19s in the earlier ASPM test | 14.907s |
| NVMe completion timeouts | Repeated, approximately 30-second stalls | None recorded in the observed successful boot |
| GSC proxy | Failed to bind within expected timeout | Bound at 2.443s |
| Active VMD version | `0.6` | `0.6-mtl016-test` |

Successful boot timing from systemd:

```text
6.685s firmware + 2.059s loader + 1.500s kernel
+ 2.842s initrd + 1.818s userspace = 14.907s total
```

Linux kernel/initramfs/userspace together took 6.160s. The owner reported that
the corrected boot was fast with no wait. GSC firmware also loaded normally.
No independent Firefox launch benchmark was recorded.

The running system used the patched VMD version and the corrected initramfs;
this was not just a compilation result. The owner subsequently promoted that
kernel/image pair to their sole Arch entry.

An earlier development image failed to find the root disk because the staged
modules were absolute symlinks back to their own boot-time paths. That packaging
error was corrected by staging real module bytes. The corrected verification
rejects non-regular module files and checks all early-boot dependencies. The
successful image contained 42 real module files; the original had 39, with the
three MEI modules added by the fix.
