# Notes to Linux distributors

This document contains information about the packaging of nvme-stas.

## Compile-time dependencies

nvme-stas is a Python 3 project and does not require compile-time libraries per se. However, we use the meson build system for installation and testing. With regards to testing, nvme-stas provides static code analysis (pylint, pyflakes), which can be run with "`meson test`".

| Library / Program | Purpose                                           | Mandatory / Optional |
| ----------------- | ------------------------------------------------- | -------------------- |
| meson             | Project configuration, installation, and testing. | Mandatory            |
| pylint            | Static code analysis                              | Optional             |
| python3-pyflakes  | Static code analysis                              | Optional             |

## Run-time dependencies

nvme-stas requires Linux kernel version of 5.14 or later. This version of Linux introduces a new configuration parameter (`host-iface`) needed by the nvme-tcp kernel module.

nvme-stas also depends on the following run-time libraries and modules. Note that versions listed are the versions that were tested with. With the exception of the Linux kernel 5.14, which is the mandatory minimum kernel required, all other libraries could potentially work with an earlier version.

| Library                                         | Min version | stafd         | stacd         |
| ----------------------------------------------- | ----------- | ------------- | ------------- |
| libnvme                                         | 1.0         | **Mandatory** | **Mandatory** |
| python3-dasbus                                  | 1.6         | **Mandatory** | **Mandatory** |
| python3-pyudev                                  | 0.22.0      | **Mandatory** | **Mandatory** |
| python3-systemd                                 | 234         | **Mandatory** | **Mandatory** |
| python3-gi (Debian) OR python3-gobject (Fedora) | 3.40.1      | **Mandatory** | **Mandatory** |
| nvme-tcp (kernel module)                        | 5.14        | **Mandatory** | **Mandatory** |
| dbus-daemon                                     | 1.12.20     | **Mandatory** | **Mandatory** |
| avahi-daemon                                    | 0.8         | **Mandatory** | Not required  |

## Things to do post installation

### Kernel modules

nvme-stas installs **`/usr/lib/modules-load.d/nvme-tcp.conf`**, which loads the `nvme-tcp` kernel module at boot. However, this will only take effect the next time the system is booted. Therefore, after installing `nvme-stas`, one needs to "`modprobe nvme-tcp`" to ensure the kernel module is loaded immediately after installation.

### D-Bus configuration

We also install D-Bus configuration files under `/etc/dbus-1/system.d`. One needs to run **`systemctl reload dbus-broker.service`** for the new configuration to take effect.

### NVMe configuration

`stafd` and `stacd` use the `libnvme` library to interact with the Linux kernel. And `libnvme` relies on two configuration files, `/etc/nvme/hostnqn` and `/etc/nvme/hostid`, to retrieve the Host NQN and ID respectively. These files should be created post installation. Here's an example for Debian-based systems:

```
if [ "$1" = "configure" ]; then
    if [ ! -d "/etc/nvme" ]
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

Note that the above uses the utility program `stasadm` that gets installed with `nvme-stas`.

### Enabling and starting the daemons

Lastly, the two daemons, `stafd` and `stacd`, should be enabled (e.g. `systemctl enable stafd.service stacd.service`) and started (e.g. `systemctl start stafd.service stacd.service`).

