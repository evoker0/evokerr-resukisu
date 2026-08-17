#!/usr/bin/env python3
"""scripts/brand_kernel.py - put your own name into a raw GKI kernel Image.

Same three slots the Windows tool patches:

  1. linux_proc_banner (.rodata)  "%s version %s (user@host) (compiler) %s\\n"
                                  -> /proc/version, and the Settings screen
  2. linux_banner      (.rodata)  the full literal   -> boot dmesg
  3. init_uts_ns       (.data)    6 fields x 65 bytes -> uname -r / uname -v

Rules that keep the kernel bootable:
  * .rodata strings may be SHORTENED, never lengthened - they sit in fixed slots.
  * init_uts_ns fields are 65 bytes, so up to 64 chars + NUL.
  * vermagic is NEVER touched, so vendor_dlkm modules keep loading.
  * the builder host must not contain a dot: Android's Settings parses
    /proc/version with  \\(([^\\s@]+@[^\\s.]+).*\\)  and cuts at the first dot.

Tokens usable in --name / --builder / --link:
  {name} {NAME} {base} {release} {kver} {kmi} {smp} {date}
"""

import argparse
import re
import sys

UTS_FIELD = 65  # __NEW_UTS_LEN + 1


def expand(tpl, release, smp, name):
    base = release.split("-g")[0] if "-g" in release else release
    m = re.match(r"^(\d+\.\d+\.\d+)", release)
    kver = m.group(1) if m else ""
    m = re.search(r"android\d+(-\d+)?", release)
    kmi = m.group(0) if m else ""
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

    # ---- 1. linux_banner, and the original release string ----
    lb = blob.find(b"Linux version ")
    if lb < 0:
        raise SystemExit("linux_banner not found - is the Image compressed?")
    if blob[lb:lb + 16] == b"Linux version %s":
        lb = blob.find(b"Linux version ", lb + 1)
    lend = blob.find(b"\x00", lb)
    lroom = lend - lb + 1
    banner = blob[lb:lend].decode("ascii", "replace")
    parts = banner.split(" ")
    if len(parts) < 3:
        raise SystemExit("could not parse the banner: " + banner)
    rel_old = parts[2]

    # ---- 2. init_uts_ns: the release copy whose +65 neighbour starts with "#1 " ----
    uts = -1
    i = 0
    needle = rel_old.encode("ascii")
    while True:
        i = blob.find(needle, i)
        if i < 0:
            break
        if blob[i + UTS_FIELD:i + UTS_FIELD + 3] == b"#1 ":
            uts = i
            break
        i += 1
    if uts < 0:
        raise SystemExit("init_uts_ns not found")
    ver_old = blob[uts + UTS_FIELD:uts + 2 * UTS_FIELD].split(b"\x00")[0].decode("ascii")
    smp = re.sub(r"^#\d+\s*", "", ver_old)

    # ---- 3. linux_proc_banner (the printf format string) ----
    pb = blob.find(b"%s version %s")
    if pb < 0:
        raise SystemExit("linux_proc_banner not found")
    proom = blob.find(b"\x00", pb) - pb + 1

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

    write_slot(buf, pb, proom, "%s version %s (" + who + ") (" + cc + ") %s\n")
    write_slot(buf, lb, lroom, "Linux version " + rel + " (" + who + ") (" + cc + ") " + ver)
    write_slot(buf, uts, UTS_FIELD, rel)
    write_slot(buf, uts + UTS_FIELD, UTS_FIELD, ver)

    open(args.image, "wb").write(bytes(buf))

    print("  was : " + rel_old)
    print("  now : " + rel)
    print("Settings > About phone > Kernel version will read:")
    print("  " + rel)
    print("  " + who + " #1")
    print("  " + re.sub(r"^#\d+\s*", "", ver))


if __name__ == "__main__":
    main()
