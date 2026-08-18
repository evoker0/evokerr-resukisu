#!/usr/bin/env python3
"""scripts/uname_changer.py - change the name a raw GKI kernel Image reports.

Three kinds of slot carry the name, and a kernel can hold MORE THAN ONE COPY of
each.  Every copy has to be rewritten: the live `init_uts_ns` is not always the
first one in the file, so patching only the first match leaves `uname -r`
reporting the original name while the banners already show the new one.

  1. linux_proc_banner (.rodata)  "%s version %s (user@host) (compiler) %s\\n"
                                  -> /proc/version, and the Settings screen
  2. linux_banner      (.rodata)  the full literal   -> boot dmesg
  3. init_uts_ns       (.data)    6 fields x 65 bytes -> uname -r / uname -v

Rules that keep the kernel bootable:
  * .rodata strings may be SHORTENED, never lengthened - they sit in fixed slots.
  * init_uts_ns fields are 65 bytes, so up to 64 chars + NUL.
  * vermagic is NEVER touched, so vendor_dlkm modules keep loading.
  * the firmware search paths (/lib/firmware/<release>) keep the original name
    on purpose - they must match the directories the modules were installed to.
  * the builder host must not contain a dot: Android's Settings parses
    /proc/version with  \\(([^\\s@]+@[^\\s.]+).*\\)  and cuts at the first dot.

Tokens usable in --name / --builder / --link:
  {name} {NAME} {base} {release} {kver} {kmi} {smp} {date}
"""

import argparse
import re
import sys

UTS_FIELD = 65  # __NEW_UTS_LEN + 1

# struct new_utsname: sysname nodename release version machine domainname
UTS_RELEASE = 2 * UTS_FIELD
UTS_VERSION = 3 * UTS_FIELD
UTS_MACHINE = 4 * UTS_FIELD


def field(blob, off):
    return blob[off:off + UTS_FIELD].split(b"\x00")[0]


def find_uts(blob):
    """Every init_uts_ns-shaped struct in the image, not just the first."""
    hits = []
    for m in re.finditer(b"Linux\x00", blob):
        o = m.start()
        if o + 6 * UTS_FIELD > len(blob):
            continue
        ver = field(blob, o + UTS_VERSION)
        mach = field(blob, o + UTS_MACHINE)
        if ver.startswith(b"#") and mach in (b"aarch64", b"x86_64", b"armv8l"):
            hits.append(o)
    return hits


def find_all(blob, pattern):
    """Offset and slot size of every NUL-terminated string matching pattern."""
    return [(m.start(), m.end() - m.start()) for m in re.finditer(pattern, blob)]


def expand(tpl, release, smp, name):
    m = re.match(r"^(\d+\.\d+\.\d+)", release)
    kver = m.group(1) if m else ""
    m = re.search(r"android\d+(-\d+)?", release)
    kmi = m.group(0) if m else ""
    # {base} is the version plus the KMI generation and nothing else, so a
    # vendor tag in the upstream name ("...-android14-Wild") does not leak into
    # the new one and end up doubled.
    if kver and kmi:
        base = kver + "-" + kmi
    else:
        base = release.split("-g")[0] if "-g" in release else release
    m = re.search(r"((Sun|Mon|Tue|Wed|Thu|Fri|Sat).+)$", smp)
    date = m.group(1) if m else ""
    out = (tpl.replace("{NAME}", name.upper())
              .replace("{name}", name)
              .replace("{base}", base)
              .replace("{release}", release)
              .replace("{kver}", kver)
              .replace("{kmi}", kmi)
              .replace("{smp}", smp)
              .replace("{date}", date))
    return re.sub(r"\s{2,}", " ", out).strip()


def write_slot(buf, off, room, text):
    raw = text.encode("ascii")
    if len(raw) >= room:
        raise SystemExit(
            "'%s' does not fit: %d >= %d bytes. This slot cannot grow - shorten it."
            % (text, len(raw), room))
    buf[off:off + room] = raw + b"\x00" * (room - len(raw))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--name", default="{base}-custom", help="kernel name -> uname -r")
    ap.add_argument("--builder", default="custom@custom", help="user@host, no dot after @")
    ap.add_argument("--link", default="", help="goes into the compiler field and uname -v")
    ap.add_argument("--version", default="#1 {link} {smp}", help="uname -v template")
    args = ap.parse_args()

    buf = bytearray(open(args.image, "rb").read())
    blob = bytes(buf)

    uts_offsets = find_uts(blob)
    if not uts_offsets:
        raise SystemExit("init_uts_ns not found - is the Image compressed?")

    rel_old = field(blob, uts_offsets[0] + UTS_RELEASE).decode("ascii", "replace")
    ver_old = field(blob, uts_offsets[0] + UTS_VERSION).decode("ascii", "replace")
    smp = re.sub(r"^#\d+\s*", "", ver_old)

    plain = re.sub(r"[^A-Za-z0-9_]+", "", args.builder.split("@")[0]) or "custom"
    rel = expand(args.name, rel_old, smp, plain)
    who = expand(args.builder, rel_old, smp, plain)
    link = expand(args.link, rel_old, smp, plain)
    cc = link if link else "kernel"
    ver = expand(args.version.replace("{link}", link), rel_old, smp, plain)

    if "@" in who and "." in who.split("@", 1)[1]:
        print("WARNING: the host part contains a dot - Android's Settings screen "
              "will cut the name there.", file=sys.stderr)
    if len(rel) > UTS_FIELD - 1:
        raise SystemExit("kernel name is %d chars, the slot holds %d" % (len(rel), UTS_FIELD - 1))
    if len(ver) > UTS_FIELD - 1:
        raise SystemExit("version is %d chars, the slot holds %d" % (len(ver), UTS_FIELD - 1))

    # ---- 1. every init_uts_ns copy ----
    for off in uts_offsets:
        write_slot(buf, off + UTS_RELEASE, UTS_FIELD, rel)
        write_slot(buf, off + UTS_VERSION, UTS_FIELD, ver)

    # ---- 2. every linux_banner literal (shrink-only, so try shorter forms) ----
    n_banner = 0
    for off, room in find_all(blob, b"Linux version [0-9][^\x00]{0,600}?\x00"):
        for text in ("Linux version %s (%s) (%s) %s" % (rel, who, cc, ver),
                     "Linux version %s (%s) (%s) #1" % (rel, who, cc),
                     "Linux version %s (%s) #1" % (rel, who)):
            if len(text.encode("ascii")) + 1 <= room:
                write_slot(buf, off, room, text)
                n_banner += 1
                break

    # ---- 3. every linux_proc_banner format string ----
    n_proc = 0
    for off, room in find_all(blob, b"%s version %s[^\x00]{0,600}?\x00"):
        text = "%s version %s (" + who + ") (" + cc + ") %s\n"
        if len(text.encode("ascii")) + 1 <= room:
            write_slot(buf, off, room, text)
            n_proc += 1

    if not n_proc:
        raise SystemExit("linux_proc_banner not found - /proc/version would keep the old name")

    open(args.image, "wb").write(bytes(buf))

    print("  was : " + rel_old)
    print("  now : " + rel)
    print("  patched %d init_uts_ns, %d linux_banner, %d linux_proc_banner"
          % (len(uts_offsets), n_banner, n_proc))
    print("Settings > About phone > Kernel version will read:")
    print("  " + rel)
    print("  " + who + " #1")
    print("  " + re.sub(r"^#\d+\s*", "", ver))


if __name__ == "__main__":
    main()
