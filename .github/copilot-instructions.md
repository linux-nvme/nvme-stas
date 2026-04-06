# Copilot Instructions for nvme-stas

## Project Overview

nvme-stas (NVMe STorage Appliance Services) provides two cooperating systemd daemons:

- **`stafd`** — discovers NVMe controllers via Avahi mDNS and/or manual config, connects to them, retrieves discovery log pages, and exposes results on D-Bus (`org.nvmexpress.staf`).
- **`stacd`** — reads discovery results from `stafd` via D-Bus and establishes NVMe-oF I/O controller connections, exposing state on D-Bus (`org.nvmexpress.stac`).

Both daemons are driven by the **GLib main loop**. There is no `asyncio`, no threads, and no thread synchronization primitives. All I/O — timers, name resolution, udev events, D-Bus signals — goes through `GLib.MainLoop`.

## Build System

The project uses **Meson**. Source files are copied (and some templated) into `.build/` at setup time. All tests run against `.build/`, not the source tree. In particular:

- `staslib/defs.py` is a template: `@VERSION@`, `@ETC@`, etc. are substituted by Meson into `.build/staslib/defs.py`.
- Top-level scripts (`stafd.py`, `stacd.py`, etc.) are installed without the `.py` extension; the built copies are `.build/stafd`, `.build/stacd`, etc.
- Meson's incremental build does not reliably re-copy files after edits. A full rebuild (`rm -rf .build/ && meson setup .build && meson compile -C .build`) is often needed.

## Python Compatibility

Code must remain compatible with **Python 3.6+**. This is enforced by `vermin`. Avoid any syntax or stdlib features introduced after 3.6 (e.g., walrus operator `:=`, `math.prod`, `str.removeprefix`).

## Code Style

- **Line length**: 120 characters maximum.
- **Linter/formatter**: `ruff` (configured in `pyproject.toml`). Quote style is `preserve` — do not normalize single vs. double quotes.
- **No docstrings or comments** should be added to code that wasn't changed.

## Key Design Patterns

### Singletons
`SvcConf`, `SysConf`, `NvmeOptions`, and `NbftConf` (all in `staslib/conf.py`) use a `Singleton` metaclass. Always instantiate them by calling the class normally, e.g. `conf.SvcConf()`. Python returns the existing instance after first construction. Pass `default_conf=` only on the very first construction.

### Transport IDs (`TID`)
`staslib/trid.py` defines `TID` — an immutable transport ID (transport, traddr, trsvcid, subsysnqn, host-iface, host-traddr). It is used as a dictionary key throughout the codebase. Do not add mutable state to it.

### GTimer
`GTimer` (in `staslib/gutil.py`) wraps GLib one-shot timers. Calling `start()` on an already-running timer resets the deadline from *now* — it does not stack or queue. Calling it on a stopped timer creates a new GLib source.

### Controller Lifecycle
When a udev "remove" event fires for a controller, `_connect_attempts` resets to 0 and the retry timer restarts at `FAST_CONNECT_RETRY_PERIOD_SEC` — this is intentional, not a bug.

## Tests

- Test files are in `test/` and named `test-*.py`.
- They use **`unittest`**, not pytest (even though pytest is a dev dependency — Meson runs them directly with `python3`).
- Tests needing filesystem mocking use `pyfakefs`.
- Run the full suite with: `meson test -C .build`
- Run a single test: `PYTHONPATH=".build/subprojects/nvme-cli/libnvme:.build" python3 test/test-foo.py -v`
