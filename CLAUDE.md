# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Test Commands

```bash
# First-time setup (or after `make purge`)
meson setup .build
meson compile -C .build

# Full test suite (use this — it sets PYTHONPATH correctly)
meson test -C .build

# Run a single test file during development
PYTHONPATH=".build/subprojects/nvme-cli/libnvme:.build" python3 test/test-foo.py -v

# Lint and format checks
ruff check .build/staslib .build/stafctl .build/stacd .build/stafctl .build/stafd .build/stasadm
ruff format --check .build/staslib

# Coverage integration test (requires nvmet kernel module, stops stafd/stacd first)
make coverage

# Make wrappers for common Meson operations
make          # build
make test     # run tests
make clean    # remove build artifacts, keep .build/
make purge    # remove .build/ entirely
```

## Critical: The `.build/` Directory

Meson copies all Python source files into `.build/` at setup time. Tests run against `.build/`, not the source tree directly. After editing source files, Meson's incremental build often does **not** re-copy them (the `configure_file(copy: true)` step doesn't track file timestamps reliably). The safest approach after non-trivial edits:

```bash
rm -rf .build/ && meson setup .build && meson compile -C .build
```

`staslib/defs.py` is a template — `@VERSION@`, `@ETC@`, etc. are substituted by Meson into `.build/staslib/defs.py`. Always read the source version for logic, but the runnable version lives in `.build/`.

Top-level scripts (`stafd.py`, `stacd.py`, `stafctl.py`, etc.) are installed **without the `.py` extension** — the built copies are `.build/stafd`, `.build/stafctl`, etc.

## Architecture

Two cooperating systemd daemons:

- **`stafd`** (STorage Appliance Finder): discovers NVMe controllers via Avahi mDNS (`_nvme-disc._tcp`) and/or manual config, connects to them, retrieves discovery log pages, and exposes results on D-Bus (`org.nvmexpress.staf`).
- **`stacd`** (STorage Appliance Connector): reads discovery results from `stafd` via D-Bus, establishes NVMe-oF I/O controller connections, exposes state on D-Bus (`org.nvmexpress.stac`).

Both daemons are driven by the **GLib main loop** — no `asyncio`, no threading primitives for I/O. Timers, name resolution, udev events, and D-Bus signals all funnel through `GLib.MainLoop`.

### `staslib/` Module Roles

| Module | Purpose |
|--------|---------|
| `stas.py` | Abstract base classes `ControllerABC` and `ServiceABC`; `load_idl()` for D-Bus introspection XML; `_read_lkc()` / `_write_lkc()` for pickle-based last-known-config |
| `ctrl.py` | Concrete `Controller` base (wraps `libnvme3.nvme.ctrl`), `Dc` (discovery controller), `Ioc` (I/O controller) |
| `service.py` | `Service` subclass wiring together D-Bus, Avahi, udev, and controller lifecycle |
| `conf.py` | `SvcConf`, `SysConf`, `NvmeOptions`, `NbftConf` — all **singletons** (see `singleton.py`); `OrderedMultisetDict` for repeated config keys |
| `gutil.py` | GLib utilities: `GTimer` (restartable one-shot timer), `Deferred` (idle-scheduled callback), `AsyncTask` (thread-pool operation with GLib callbacks), `NameResolver` |
| `avahi.py` | Avahi D-Bus client; `ServiceDiscovery` tracks `_nvme-disc._tcp` announcements; `ValueRange` implements exponential-backoff step sequences |
| `trid.py` | `TID` — immutable transport ID (transport, traddr, trsvcid, subsysnqn, host-iface, host-traddr) used as dict key throughout |
| `iputil.py` | IP address utilities, interface enumeration |
| `udev.py` | `UDEV` singleton wrapping `pyudev`; device add/remove/change event dispatch |
| `nbft.py` | NBFT (NVMe Boot Firmware Table) reader via `libnvme3.nvme.nbft_get()` |
| `log.py` | Logging initialisation (syslog + stderr) |

### Key Design Patterns

**Singletons**: `SvcConf`, `SysConf`, `NvmeOptions`, `NbftConf` use a `Singleton` metaclass. Always call them normally — e.g. `conf.SvcConf()` — Python returns the existing instance after first construction. Pass `default_conf=` only on first construction.

**GTimer restart behaviour**: `GTimer.start()` on an already-running timer resets the deadline from *now* (via `set_ready_time()`). Calling it on a stopped timer creates a new GLib source.

**Controller removal**: When `_on_ctrl_removed()` fires (udev "remove" event), `_connect_attempts` resets to 0 and the retry timer restarts at `FAST_CONNECT_RETRY_PERIOD_SEC` — effectively a fresh connection attempt.

**Last-known-config**: Persisted as a pickle file in `$RUNTIME_DIRECTORY` (typically `/run/nvme-stas/`). `pickle.load()` is safe here because that directory is root-only writable.

## NVMe Specification Context

### Key Terms (NVMe Base Spec 2.3, §1.5)

| Term | Definition |
|------|-----------|
| **Centralized Discovery controller (CDC)** | A Discovery controller that reports discovery information registered by Direct Discovery controllers and hosts |
| **Direct Discovery controller (DDC)** | A Discovery controller that is capable of registering discovery information with a Centralized Discovery controller |
| **Discovery controller** | A controller that allows a host to retrieve a Discovery Log Page; does not implement I/O Queues or access non-volatile storage |
| **Fabric Zoning** | A technique to specify access control configurations between hosts and NVM subsystems |
| **I/O controller** | A controller that implements I/O queues intended to access a non-volatile storage medium |

Capitalisation: the spec writes "Centralized Discovery **c**ontroller" (lowercase c). Always **Centralized**, never "Central".

### TP8009 vs. TP8010 Scope

**TP8009** — *Automated Discovery of NVMe-oF Discovery Controllers for IP Networks*  
Defines how hosts find CDC/DDC IP addresses using DNS-SD (mDNS or unicast DNS). IP fabrics only.  
- mDNS service name: `_nvme-disc._tcp` (TCP/iWARP) or `_nvme-disc._udp` (RoCE)  
- CDC detection subtype: `_cdc._sub._nvme-disc._tcp`  
- Host reads the A/AAAA record IP and issues a Fabrics Connect command  
- This is called **zeroconf** (zero-configuration networking) — never "ZTP" (zero-touch provisioning, a different concept)  
- TP8009 has **no registration mechanism** — registration is exclusively TP8010

**TP8010** — *NVMe-oF Centralized Discovery Controller*  
Defines everything that requires persistent host state:
- Host/DDC registration with the CDC via the Discovery Information Management (DIM) command (push or pull model)
- AENs from the CDC when Host Discovery Log Page changes (new/removed subsystems visible to the host)
- Fabric Zoning: CDC controls which hosts see which subsystems; zone changes trigger connect/disconnect in nvme-stas
- Kernel support: `host-iface` (5.14), DC unique NQN (5.16), runtime feature detection (5.17), full TP8010 (5.18)

### Terminology Decisions

| Avoid | Use instead | Reason |
|-------|-------------|--------|
| "Central Discovery Controller" | **Centralized** Discovery controller | NVMe Base Spec §1.5.16 |
| "zero-touch provisioning / ZTP" | **zeroconf** | TP8009 and all nvme-stas docs use this term |
| "caches storage subsystem information" | "caches discovery log pages" | Log pages contain both I/O controller entries and DC referrals |
| Attributing CDC registration to TP8009 | TP8009 = mDNS discovery only; TP8010 = registration/AEN/Zoning | TP8009 has no registration mechanism |

## Tests

Test files are in `test/` and are named `test-*.py`. They use `unittest` (not pytest, despite pytest being listed as a dev dependency — Meson runs them directly with `python3`).

Tests that need filesystem mocking use `pyfakefs` (`from pyfakefs.fake_filesystem_unittest import TestCase`).

`test-stasadm.py` loads `stasadm.py` at module level using `importlib.util.spec_from_file_location` with `sys.argv`, `sys.exit`, `sys.stdout`, and `sys.stderr` all mocked — because `stasadm.py` runs entry-point code at import time.

The Avahi test requires `avahi-daemon` and `dbus` to be active; Meson skips it automatically if they are not running.

## Python Version Compatibility

Code must remain compatible with **Python 3.6+**. This is enforced by `vermin` (configured in `test/vermin.conf`, target `3.6`). Excluded from vermin analysis: `importlib.resources` and `importlib_resources` (handled by the three-tier fallback in `stas.py`). Line length limit is **120** characters (configured in `pyproject.toml`).
