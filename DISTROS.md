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

nvme-stas is built on top of libnvme, which is used to interact with the kernel's NVMe driver (i.e. `drivers/nvme/host/`). To support all the features of nvme-stas, several changes to the Linux kernel are required. nvme-stas can also operate with older kernels, but with limited functionality. Kernel 5.18 provides all the features needed by nvme-stas. nvme-stas can also work with older kernels that include back-ported changes to the NVMe driver.

The next table shows different features that were added to the NVMe driver and in which version of the Linux kernel they were added. Note that the ability to query the NVMe driver to determine what options it supports was added in 5.17. This is needed if nvme-stas is to make the right decision on whether a feature is supported. Otherwise, nvme-stas can only rely on the kernel version to decide what is supported. This can greatly limit the features supported on back-ported kernels.

| Feature                                                      | Introduced in kernel version |
| ------------------------------------------------------------ | ---------------------------- |
| **`host-iface` option** - Ability to force TCP connections over a specific interface. Needed for zeroconf provisioning. | 5.14                         |
| **TP8013 Support** - Discovery Controller (DC) Unique NQN. Allow the creation of connections to DC with a NQN other than the default `nqn.2014-08.org.nvmexpress.discovery` | 5.16                         |
| **Query supported options** - Allow user-space applications to query which options the NVMe driver supports | 5.17                         |
| **TP8010 Support** - Ability for a Host to register with a Discovery Controller. This version of the kernel introduces a new event to indicate to user-space apps (e.g. nvme-stas) when a connection to a DC is restored. This is used to trigger a re-registration of the host. This kernel also exposes the DC Type (dctype) attribute through the sysfs, which is needed to determine whether registration is supported. | 5.18                         |

nvme-stas also depends on the following run-time libraries and modules. Note that versions listed are the versions that were tested with. 

| Library                                         | Min version | stafd         | stacd         |
| ----------------------------------------------- | ----------- | ------------- | ------------- |
| libnvme                                         | 1.0         | **Mandatory** | **Mandatory** |
| python3-dasbus                                  | 1.6         | **Mandatory** | **Mandatory** |
| python3-pyudev                                  | 0.22.0      | **Mandatory** | **Mandatory** |
| python3-systemd                                 | 234         | **Mandatory** | **Mandatory** |
| python3-gi (Debian) OR python3-gobject (Fedora) | 3.36.0      | **Mandatory** | **Mandatory** |
| nvme-tcp (kernel module)                        | 5.18 *      | **Mandatory** | **Mandatory** |
| dbus-daemon                                     | 1.12.2      | **Mandatory** | **Mandatory** |
| avahi-daemon                                    | 0.8         | **Mandatory** | Not required  |

* Kernel 5.18 provides full functionality. nvme-stas can work with older kernels, but with limited functionality. 

## Things to do post installation

### D-Bus configuration

We install D-Bus configuration files under `/usr/share/dbus-1/system.d`. One needs to run **`systemctl reload dbus-broker.service`** (Fedora) OR **`systemctl reload dbus.service`** (SuSE, Debian) for the new configuration to take effect.

### Configuration shared with `libnvme` and `nvme-cli`

`stafd` and `stacd` use the `libnvme` library to interact with the Linux kernel. And `libnvme` as well as `nvme-cli` rely on two configuration files, `/etc/nvme/hostnqn` and `/etc/nvme/hostid`, to retrieve the Host NQN and ID respectively. These files should be created post installation with the help of the `stadadm` utility. Here's an example for Debian-based systems:

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

The utility program `stasadm` gets installed with `nvme-stas`. `stasadm` also manages the creation (and updating) of `/etc/stas/sys.conf`, the `nvme-stas` system configuration file.

### Configuration specific to nvme-stas

The [README](./README.md) file defines the following three configuration files:

- `/etc/stas/sys.conf`
- `/etc/stas/stafd.conf`
- `/etc/stas/stacd.conf`

Care should be taken during upgrades to preserve customer configuration and not simply overwrite it.  The process to migrate the configuration data and the list of parameters to migrate is still to be defined.

### Enabling and starting the daemons

Lastly, the two daemons, `stafd` and `stacd`, should be enabled (e.g. `systemctl enable stafd.service stacd.service`) and started (e.g. `systemctl start stafd.service stacd.service`).
