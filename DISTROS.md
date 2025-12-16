# Notes for Linux Distributors

This document describes the requirements and guidelines for packaging **nvme-stas** for Linux distributions. It covers build-time and runtime dependencies, kernel feature requirements, post-installation tasks, and interactions with `nvme-cli`.

## Build-time dependencies

`nvme-stas` is a Python 3 project and does not require build-time libraries. However, it uses **Meson** for installation and testing. 

| Library / Program | Purpose                                         | Madatory? |
| ----------------- | ----------------------------------------------- | --------- |
| meson             | Project configuration, installation, and tests. | Yes       |

## Unit test dependencies

Static code analysis tools can be executed via `meson test`. These tools are **not required for runtime packaging**, but may be useful for distro QA.

| Library / Program | Purpose                                                      | Mandatory? |
| ----------------- | ------------------------------------------------------------ | ---------- |
| pylint            | Static code analysis                                         | Optional   |
| python3-pyflakes  | Static code analysis                                         | Optional   |
| python3-pyfakefs  | Filesystem-related test mocking                              | Optional   |
| vermin            | Verify minimum Python version requirements (currently Python 3.6) | Optional   |

## Runtime dependencies

### **Python and nvme-stas Requirements**

- **Minimum Python version:** **3.6**
- nvme-stas relies on **libnvme** for kernel interaction. nvme-stas **3.0** requires **libnvme 3.0 or later**.
- Full nvme-stas functionality requires **Linux kernel 5.18**.
  - Older kernels work but will have reduced functionality unless distribution kernels have appropriate backports.

### **Kernel Feature Requirements**

The following NVMe driver features affect nvme-stas behavior. Kernel 5.17+ is strongly recommended because it allows querying driver capabilities at runtime.

| Feature                     | Introduced in Kernel | Notes                                                        |
| --------------------------- | -------------------- | ------------------------------------------------------------ |
| `host-iface` option         | **5.14**             | Required for correct TCP interface selection (zeroconf provisioning) |
| TP8013 (DC Unique NQN)      | **5.16**             | Allows Discovery Controllers to use a non-default NQN        |
| Query supported options     | **5.17**             | Enables user-space feature detection instead of relying on kernel version |
| TP8010 (Host Registration)  | **5.18**             | Adds DC reconnect events and exposes `dctype` via sysfs      |
| Additional TCP improvements | **6.1**              | Source IP exposure, `host_iface` improvements, rediscover events |

### **nvme-stas 3.0: Required Runtime Packages and Modules**

The following were validated during development; equivalent or newer versions should work.

| Package / Module                            | Min Version | stafd     | stacd        | Version Check                                             | Notes                                                    |
| ------------------------------------------- | ----------- | --------- | ------------ | --------------------------------------------------------- | -------------------------------------------------------- |
| **python3**                                 | 3.6         | Mandatory | Mandatory    | `python3 --version`                                       | Minimum supported Python                                 |
| **python3-libnvme**                         | **3.0**     | Mandatory | Mandatory    | `python3 -c 'import libnvme; print(libnvme.__version__)'` | Userspace NVMe library                                   |
| **python3-gi / python3-gobject**            | 3.36.0      | Mandatory | Mandatory    | `python3 -c 'import gi; print(gi.__version__)'`           | GObject introspection                                    |
| **python3-dasbus**                          | 1.6         | Mandatory | Mandatory    | `pip list \| grep dasbus`                                 | D-Bus bindings                                           |
| **python3-pyudev**                          | 0.22.0      | Mandatory | Mandatory    | `python3 -c 'import pyudev; print(pyudev.__version__)'`   | udev integration                                         |
| **python3-systemd**                         | 240         | Mandatory | Mandatory    | `systemd --version`                                       | Journaling and notifications                             |
| **nvme-tcp (kernel module)**                | 5.18*       | Mandatory | Mandatory    | N/A                                                       | Required for TCP transports                              |
| **dbus-daemon**                             | 1.12.2      | Mandatory | Mandatory    | `dbus-daemon --version`                                   | System D-Bus services                                    |
| **avahi-daemon**                            | 0.7         | Mandatory | Not required | `avahi-daemon --version`                                  | mDNS discovery (stafd only)                              |
| **importlib.resources.files()** or backport | —           | Optional  | Optional     | Built-in / backport                                       | `importlib_resources` is used automatically if available |

\* Kernel 5.18 provides full feature coverage. Earlier kernels may work with appropriate NVMe driver backports.

## Post-installation Tasks

### **D-Bus Configuration Reload**

nvme-stas installs configuration files under:

```
/usr/share/dbus-1/system.d
```

After installation, reload D-Bus:

- **Fedora:** `systemctl reload dbus-broker.service`
- **SUSE, Debian:** `systemctl reload dbus.service`

### **Host Identity Configuration (Shared with libnvme / nvme-cli)**

Both `libnvme` and `nvme-cli` rely on:

- `/etc/nvme/hostnqn`
- `/etc/nvme/hostid`

Distributions should create these files on install using `stasadm`.
 Example (Debian maintainer script):

```
if [ "$1" = "configure" ]; then
    if [ ! -d "/etc/nvme" ]; then
        mkdir /etc/nvme
    fi
    if [ ! -s "/etc/nvme/hostnqn" ]; then
        stasadm hostnqn -f /etc/nvme/hostnqn
    fi
    if [ ! -s "/etc/nvme/hostid" ]; then
        stasadm hostid -f /etc/nvme/hostid
    fi
fi
```

`stasadm` is installed with nvme-stas and also manages:

```
/etc/stas/sys.conf
```

### nvme-stas Configuration Files

nvme-stas uses three configuration files:

- `/etc/stas/sys.conf`
- `/etc/stas/stafd.conf`
- `/etc/stas/stacd.conf`

**Guidelines for packagers:**

- Do **not** overwrite these files on upgrade.
- Preserve user configurations.
- A future migration mechanism will define how parameters are updated during upgrades.

### Enabling and starting services

stafd and stacd must be enabled and started:

```
systemctl enable --now stafd.service stacd.service
```

## Compatibility with nvme-cli

`nvme-cli` installs udev rules such as:

```
/usr/lib/udev/rules.d/70-nvmf-autoconnect.rules
```

These rules attempt to auto-connect I/O controllers on kernel events.

### The Race Condition

- `nvme-cli` (via udev rules) and `nvme-stas` both react to the same NVMe events.
- The udev rules in **nvme-cli ≤ 2.1.2** do **not** propagate the `host-iface` argument.
- Because udev rules run in C and nvme-stas runs in Python, the udev rules typically win the race.
- Result: connections may be established using the wrong TCP interface.

### Resolution

nvme-stas **disables nvme-cli’s udev rules** and assumes those responsibilities. It does that by installing a new udev rulefile,  `/run/udev/rules.d/70-nvmf-autoconnect.rules`., which takes precedence over the file installed by the nvme-cli package.
This ensures:

- A single orchestrator handles connection events
- Race conditions are eliminated
- All NVMe/TCP connections consistently use the correct `host-iface`
