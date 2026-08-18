# evokerr-resukisu

Prebuilt GKI kernels for Android 12 through 16, in three flavours — ReSukiSU,
SukiSU-Ultra and KernelSU-Next — each with SUSFS. Builds run daily and a new release
only appears when something upstream actually moved.

## Grab the right one

```
adb shell uname -r
```

That prints something like `5.10.157-android13-4-00002-g0eacbbcce3d5-ab9881766`. The part
that matters is `5.10` + `android13` — that pair is the KMI. Download the asset whose name
carries the same pair.

**A kernel built for a different KMI generation will not boot.** `android12-5.10` on an
`android13-5.10` device leaves the vendor modules unloadable and the screen dark.

## Install

Either flash the AnyKernel3 zip from a recovery or a root manager, or put the `Image` into
your own boot image:

```
magiskboot unpack boot.img
cp Image kernel
magiskboot repack boot.img new-boot.img
fastboot flash boot new-boot.img
```

Keep your stock `boot.img`. If a kernel does not boot, flash it back.

## Coverage

Every monthly GKI branch that can still be built, for six of the seven KMIs.

That qualifier matters. The manifest repo lists every dated branch it ever had —
`common-android12-5.10-2023-03` is still there — but each one pins `kernel/common` at a
branch of the same name, and **`kernel/common` only keeps roughly the last five to seven
months**. The older manifest branches point at something that no longer exists and cannot
be synced at all. Old assets in other builders' repos are historical builds from when
those branches were alive; they are not reproducible today.

| KMI | buildable months | distinct kernels |
|---|---|---|
| android12-5.10 | 5 of 38 | 5 |
| android13-5.10 | 5 of 39 | 5 |
| android13-5.15 | 5 of 38 | 5 |
| android14-5.15 | 5 of 23 | 5 |
| android14-6.1 | 6 of 31 | 5 |
| android15-6.6 | 7 of 19 | 6 |
| android16-6.12 | none yet — see below | |

Months that carry the same sublevel are the same kernel, so they are built once and the
remaining months of that sublevel serve as fallbacks if SUSFS does not fit the newest one.

**android16-6.12 is not built yet.** Its kleaf module list expects
`drivers/android/rust_binder.ko`, which needs `CONFIG_RUST`, which needs rustc from
`prebuilts/rust`. On 6.12 that manifest project sits in the `ddk` group, which a default
`repo sync` skips; on android15-6.6 the same project has no group, which is why 6.6 builds
and 6.12 does not. Syncing `--groups=default,ddk,ddk-external` did not fix it on its own —
rustc still never appears in the build log. Left out of the matrix until that is solved,
rather than failing one job per variant on every run.

## What each flavour gives you

| | SUSFS | KPM |
|---|---|---|
| ReSukiSU | yes, built into the driver | no |
| SukiSU-Ultra | yes, via susfs4ksu | yes |
| KernelSU-Next | yes, via susfs4ksu | no |

KPM is a SukiSU-Ultra feature — `CONFIG_KPM` does not exist in the other two, so asking
for it there is refused rather than silently ignored.

## Repository layout

```
.github/workflows/
  gki-build.yml        builds one KMI x one flavour, end to end
  build-all-gki.yml    manual fan-out over every KMI
  auto-release.yml     daily upstream check, then build and publish
scripts/
  check_upstream.py    decides what is stale
  uname_changer.py     rewrites the name the kernel reports in uname / Settings
state.json             what was last built, per KMI and flavour
```

`check_upstream.py` compares two things against `state.json`: the newest AOSP manifest
branch for each KMI, and the newest tag of each root solution. Only the pairs that changed
get rebuilt, so a quiet week costs nothing.

## Building it yourself

Actions → **Build all GKI** → Run workflow. Pick the flavour and the naming, or run
**GKI build** for a single KMI.

`gki-build.yml` checks the manifest branch before syncing, so a wrong `os_patch_level`
fails in seconds with the list of valid values instead of after a fifteen minute sync.

## Naming

The kernel name, the builder line and the version string are templates:

```
kernel name   {base}-evokerr
builder       evokerr@evokeroot
link          t.me/evokeroot
```

Tokens: `{name} {NAME} {base} {release} {kver} {kmi} {smp} {date}`

Three slots inside the Image carry the name: `linux_proc_banner` and `linux_banner` in
`.rodata`, and `init_uts_ns` in `.data`. The rodata slots are fixed size and can only
shrink; the utsname fields are 65 bytes, so the name and the version string cap at 64
characters. **vermagic is never touched**, which is what keeps `vendor_dlkm` modules
loading. The host part must not contain a dot — Android's Settings screen parses
`/proc/version` with `\(([^\s@]+@[^\s.]+).*\)` and would cut the name there.

## Credits

Kernel source is Google's [Android Common Kernel](https://android.googlesource.com/kernel/common/).
Root solutions: [ReSukiSU](https://github.com/ReSukiSU/ReSukiSU),
[SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra),
[KernelSU-Next](https://github.com/KernelSU-Next/KernelSU-Next).
SUSFS by [simonpunk](https://gitlab.com/simonpunk/susfs4ksu).
Packaging via [AnyKernel3](https://github.com/osm0sis/AnyKernel3).

GPL-2.0, same as the kernel.
