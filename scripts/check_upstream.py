#!/usr/bin/env python3
"""scripts/check_upstream.py - work out what needs building.

Google keeps every monthly GKI branch alive, not just the newest, and other builders
publish one kernel per month per KMI rather than one per KMI. This does the same: it
enumerates every dated manifest branch, reads the real SUBLEVEL out of each, and emits
the pairs that are not in state.json yet.

Two things make a pair stale:
  * the month is new to us
  * the root solution shipped a new tag since we last built that month

state.json keeps a sublevel cache as well, so the second run does not re-read a few
hundred Makefiles.

Outputs (GitHub Actions):
    matrix   JSON list of {kmi, android_version, kernel_version, sub_level,
                           os_patch_level, root_solution, reason}
    count    number of entries

Locally:  python3 scripts/check_upstream.py --print --mode newest
"""

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

MANIFEST_REFS = "https://android.googlesource.com/kernel/manifest/+refs/heads/?format=JSON"
COMMON_MAKEFILE = ("https://android.googlesource.com/kernel/common/+/refs/heads/"
                   "{branch}/Makefile?format=TEXT")

KMIS = [
    ("android12-5.10", "android12", "5.10"),
    ("android13-5.10", "android13", "5.10"),
    ("android13-5.15", "android13", "5.15"),
    ("android14-5.15", "android14", "5.15"),
    ("android14-6.1",  "android14", "6.1"),
    ("android15-6.6",  "android15", "6.6"),
]

# android16-6.12 is left out on purpose.
#
# Its kleaf module list expects drivers/android/rust_binder.ko, which needs CONFIG_RUST,
# which needs rustc from prebuilts/rust. That project sits in the manifest's "ddk" group,
# so a default `repo sync` skips it - on android15-6.6 the same project has no groups
# attribute, which is exactly why 6.6 builds and 6.12 does not. Syncing with
# --groups=default,ddk,ddk-external was not enough on its own: rustc still never shows up
# in the build log and the module is still missing after 35 minutes of compiling.
#
# Rather than burn one failing job per variant on every run, it stays out until that is
# actually solved. Next thing to try: put CONFIG_RUST=y in the fragment, so kleaf reports
# "actual '' expected y" and tells us plainly whether rustc arrived at all.
SKIPPED_KMIS = [("android16-6.12", "android16", "6.12")]

ROOTS = {
    "ReSukiSU":      ("ReSukiSU/ReSukiSU", "main"),
    "SukiSU-Ultra":  ("SukiSU-Ultra/SukiSU-Ultra", "builtin"),
    "KernelSU-Next": ("pershoot/KernelSU-Next", "next-susfs"),
}


def get(url, token=None):
    req = urllib.request.Request(url, headers={"User-Agent": "evokerr-kernels"})
    if token and "api.github.com" in url:
        req.add_header("Authorization", "Bearer " + token)
        req.add_header("Accept", "application/vnd.github+json")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError:
            raise
        except Exception:
            if attempt == 3:
                raise
    return ""


def gitiles_json(url, token=None):
    txt = get(url, token)          # gitiles prefixes its JSON with an anti-XSSI line
    return json.loads(txt[txt.index("{"):])


def months_per_kmi(token=None):
    refs = gitiles_json(MANIFEST_REFS, token)
    out = {}
    for kmi, _, _ in KMIS:
        pat = re.compile(r"^common-" + re.escape(kmi) + r"-(\d{4}-\d{2})$")
        out[kmi] = sorted((m.group(1) for m in (pat.match(n) for n in refs) if m), reverse=True)
    return out


def sublevel(kmi, month, cache, token=None):
    """SUBLEVEL from kernel/common's Makefile on that branch, cached in state.json.

    A failed read is never cached. Caching one produced artifacts called 5.15.0 and
    6.6.0 that then stayed wrong on every later run. The build reads the sublevel out of
    the synced tree anyway, so this value is only a hint for the matrix label.
    """
    key = "%s-%s" % (kmi, month)
    if cache.get(key) not in (None, "0"):
        return cache[key]
    try:
        mk = base64.b64decode(get(COMMON_MAKEFILE.format(branch=key), token)).decode("utf-8", "replace")
        m = re.search(r"^SUBLEVEL\s*=\s*(\d+)", mk, re.M)
        if m:
            cache[key] = m.group(1)
            return cache[key]
        print("  note: no SUBLEVEL line in %s" % key, file=sys.stderr)
    except Exception as e:
        print("  note: could not read %s (%s)" % (key, e), file=sys.stderr)
    return "0"


def root_revision(repo, branch, token=None):
    """Latest tag if there is one, else the head commit of the tracked branch."""
    try:
        tags = json.loads(get("https://api.github.com/repos/%s/tags?per_page=1" % repo, token))
        if tags:
            return tags[0]["name"]
    except Exception:
        pass
    try:
        br = json.loads(get("https://api.github.com/repos/%s/branches/%s" % (repo, branch), token))
        return br["commit"]["sha"][:12]
    except Exception as e:
        print("  note: cannot read %s@%s (%s)" % (repo, branch, e), file=sys.stderr)
        return "unknown"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="state.json")
    ap.add_argument("--roots", default="ReSukiSU,SukiSU-Ultra,KernelSU-Next")
    ap.add_argument("--mode", choices=["all", "newest"], default="all",
                    help="all = every dated manifest branch; newest = only the latest per KMI")
    ap.add_argument("--limit", type=int, default=0, help="cap the matrix, 0 = no cap")
    ap.add_argument("--force", action="store_true", help="ignore state.json")
    ap.add_argument("--print", dest="show", action="store_true")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    wanted = [r.strip() for r in args.roots.split(",") if r.strip()]

    state = {"_sublevels": {}, "builds": {}}
    if os.path.exists(args.state):
        try:
            old = json.load(open(args.state, encoding="utf-8"))
            if isinstance(old, dict) and "builds" in old:
                state = old
                state.setdefault("_sublevels", {})
            # a flat dict is the older format; its keys no longer mean the same thing
        except Exception:
            pass
    subs = state["_sublevels"]
    built = {} if args.force else state["builds"]

    print("Reading AOSP manifest ...", file=sys.stderr)
    months = months_per_kmi(token)

    print("Reading root solution revisions ...", file=sys.stderr)
    revs = {r: root_revision(ROOTS[r][0], ROOTS[r][1], token) for r in wanted}
    for r in wanted:
        print("  %-14s %s" % (r, revs[r]), file=sys.stderr)

    matrix, new_builds = [], {}
    for kmi, av, kv in KMIS:
        chosen = months[kmi] if args.mode == "all" else months[kmi][:1]
        if not chosen:
            continue
        print("%-16s %d month(s)" % (kmi, len(chosen)), file=sys.stderr)
        for month in chosen:
            sub = sublevel(kmi, month, subs, token)
            for root in wanted:
                key = "%s|%s|%s" % (kmi, month, root)
                stamp = "%s|%s" % (sub, revs[root])
                new_builds[key] = stamp
                if key not in built:
                    reason = "new"
                elif built[key] != stamp:
                    reason = "%s %s -> %s" % (root, built[key].split("|")[-1], revs[root])
                else:
                    continue
                matrix.append({
                    "kmi": kmi, "android_version": av, "kernel_version": kv,
                    "sub_level": sub, "os_patch_level": month,
                    "root_solution": root, "reason": reason,
                })

    # newest months first so a capped run covers the interesting ones
    matrix.sort(key=lambda e: (e["os_patch_level"], e["kmi"]), reverse=True)
    dropped = 0
    if args.limit and len(matrix) > args.limit:
        dropped = len(matrix) - args.limit
        matrix = matrix[:args.limit]

    if args.show or not os.environ.get("GITHUB_OUTPUT"):
        print(json.dumps(matrix, indent=2))
        print("\n%d build(s) needed, %d combination(s) known%s"
              % (len(matrix), len(new_builds),
                 (", %d over the limit and skipped this run" % dropped) if dropped else ""),
              file=sys.stderr)
        return

    # Only the pairs that are actually being built get recorded, so anything skipped by
    # --limit comes back on the next run instead of being quietly forgotten.
    keep = set("%s|%s|%s" % (e["kmi"], e["os_patch_level"], e["root_solution"]) for e in matrix)
    merged = dict(built)
    for k, v in new_builds.items():
        if k in keep or k in built:
            merged[k] = v
    state["builds"] = merged
    state["_sublevels"] = subs
    json.dump(state, open(args.state, "w", encoding="utf-8"), indent=2, sort_keys=True)

    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write("count=%d\n" % len(matrix))
        f.write("matrix=%s\n" % json.dumps({"include": matrix}))
    if dropped:
        print("::notice::%d build(s) over --limit were skipped and will be picked up next run" % dropped)
    print("%d build(s) needed" % len(matrix), file=sys.stderr)


if __name__ == "__main__":
    main()
