---
title: "Fusion's embedded Python runs third-party wheels, including native extensions"
date: 2026-08-19
---

# What was believed

`references/mcp-adapter.md` recorded a live probe as: `os`, `tempfile`, `hashlib`, `uuid`
imported while `secrets`, `sqlite3`, `numpy`, and `requests` did not. That was read as
"Fusion's Python cannot take dependencies", and it drove a stdlib-only design and an
architecture argument for keeping all numerics host-side.

# What is actually true

Probed live against Fusion on 2026-08-19:

- Fusion's Python is **3.14.0**, `EXT_SUFFIX = .cpython-314-darwin.so`,
  `sysconfig.get_platform() = macosx-10.15-universal2`.
- `secrets`, `sqlite3`, `ctypes` and `ensurepip` **all import fine**. The old note is stale.
- `numpy` raised `ModuleNotFoundError` — **not installed**, not unloadable. Different problem.
- `sys.path` already contains a user-writable directory:
  `~/Library/Application Support/Autodesk/Autodesk Fusion 360/MyScripts/ManuallyInstalled/`

Installing the `cp314` / `macosx_11_0_arm64` wheel to a directory and putting it on
`sys.path` inside a Fusion script gives:

    numpy 2.5.2 imported; numpy.linalg.eigh([[1,2],[3,4]] @ .T) -> [0.133931, 29.866069]

`eigh` is the compiled LAPACK path, so **native extensions load and execute**. A
`ModuleNotFoundError` was mistaken for a capability ceiling.

# Why it matters

The wheel must match Fusion's interpreter exactly — `cp314`, macOS, arm64/universal2.
A wheel built for the host's Python will not load. That is a packaging constraint, not a
prohibition, and it is the constraint any in-Fusion dependency mechanism has to solve:
resolve for *Fusion's* tag set, not the host's.

The existing module-bundle mechanism (`module_cache.py`) is `.py`-only by an explicit
`ValueError`, so it cannot carry this today. Extending it is a real option rather than a
dead end — the hash-verification, `O_NOFOLLOW` and verified-import work already there is
the hard part and is done.

# Rule

Probe before concluding. A failed import says a module is absent; it does not say the
runtime refuses that class of module. Record the interpreter's version and ABI tag
alongside any import probe, because those are what determine whether a wheel can load.

# sys.executable is Fusion, not a Python

Inside Fusion's embedded interpreter:

    sys.executable == ".../Autodesk Fusion.app/Contents/MacOS/Autodesk Fusion"

So **anything that shells out to `sys.executable` launches a second full Fusion instance.**
Learned by doing it: `ensurepip._bootstrap()` spawned a Fusion process whose command line
was the pip bootstrap, as a child of the live session. Two instances were running before
it was killed, and which one an MCP client binds to is undefined.

The same trap applies to `subprocess` with `sys.executable` and to `multiprocessing`.

Consequences:

- **In-process pip is impossible.** `ensurepip` imports fine but is a subprocess bootstrap,
  and the subprocess is Fusion.
- **There is no standalone interpreter to shell out to either.** Fusion ships a full
  `Python.framework` with a `bin/python3`, but the inner
  `Resources/Python.app/Contents/MacOS/Python` binary is absent, so the wrapper fails with
  `posix_spawn: ... Undefined error: 0`.

# The working shape

Detect, then resolve elsewhere. Read the triple out of Fusion with a read-only script:

    sys.version_info, sysconfig.get_config_var("EXT_SUFFIX"), sysconfig.get_platform()

observed 2026-08-19 as `3.14.0`, `.cpython-314-darwin.so`, `macosx-10.15-universal2`.

Feed those to pip as explicit target flags:

    pip install --only-binary=:all: \
      --python-version <detected> --implementation cp --abi <detected> \
      --platform <detected> --target <dir> <packages>

`--target` may be `~/Library/Application Support/Autodesk/Autodesk Fusion 360/MyScripts/ManuallyInstalled/`,
already on Fusion's `sys.path`.

**Detect every time; never hardcode the tags.** Fusion auto-updates its bundled Python, and
a pinned `cp314` becomes silently wrong the day it moves to 3.15 — the failure is a
`ModuleNotFoundError` that looks exactly like "not installed".

# Rule

Never invoke `sys.executable` from inside a host application's embedded interpreter without
checking what it points at.
