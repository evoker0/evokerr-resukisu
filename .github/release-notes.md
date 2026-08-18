## ReSukiSU + SUSFS

GKI kernels with kernel-side root and SUSFS, built fresh from Google's kernel
sources - one build per monthly AOSP branch and KMI generation.

### What every build contains

|  |  |
|---|---|
| **Root** | [ReSukiSU](https://github.com/ReSukiSU/ReSukiSU) - kernel-side, no ramdisk patch needed |
| **Hiding** | **SUSFS** - sus path, sus mount, sus kstat, sus map, open redirect, `uname` and `cmdline` spoofing, AVC log spoofing |
| **KPM** | not in this variant - see [evokerr-sukisu](https://github.com/evoker0/evokerr-sukisu) for KPM |
| **Kernel name** | `EVOKERR` - visible in `uname -r` and Settings > About phone > Kernel version |
| **Contact** | [t.me/evokeroot](https://t.me/evokeroot) |

### Pick the right file

Run this on the device:

```
adb shell uname -r
```

It prints something like `5.10.257-android13-4-g...`. Take the file whose
kernel version **and** `androidXX` both match - `5.10.257` + `android13`.
A kernel from a different KMI generation will not boot.

### Install

Flash the AnyKernel3 zip from a custom recovery, or from the flash-kernel option
in a root manager. If you would rather build your own boot image, unpack the zip
and put `Image` into it with `magiskboot`.

Keep a copy of your current `boot` partition first:

```
adb shell su -c "dd if=/dev/block/by-name/boot$(getprop ro.boot.slot_suffix) of=/sdcard/boot-backup.img"
adb pull /sdcard/boot-backup.img
```

### Manager app

[ReSukiSU manager](https://github.com/ReSukiSU/ReSukiSU/releases)

### File name suffixes

`-noSUSFS` means the SUSFS patches did not apply cleanly to that month's
sources, so the kernel was built with root only. Those combinations get rebuilt
automatically once SUSFS catches up.

