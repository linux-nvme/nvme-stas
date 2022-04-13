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

The next table shows different features that were added to the NVMe driver and in which version of the Linux kernel they were added (the list of git patches can be found in addendum). Note that the ability to query the NVMe driver to determine what options it supports was added in 5.17. This is needed if nvme-stas is to make the right decision on whether a feature is supported. Otherwise, nvme-stas can only rely on the kernel version to decide what is supported. This can greatly limit the features supported on back-ported kernels.

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

# Addendum

## Kernel patches

Here's the list of kernel patches (added in kernels 5.14 to 5.18) that will enable all features of nvme-stas.

```
commit e3448b134426741902b6e2c07cbaf5f66cfd2ebc
Author: Martin Belanger <martin.belanger@dell.com>
Date:   Tue Feb 8 14:18:02 2022 -0500

    nvme: Expose cntrltype and dctype through sysfs

    TP8010 introduces the Discovery Controller Type attribute (dctype).
    The dctype is returned in the response to the Identify command. This
    patch exposes the dctype through the sysfs. Since the dctype depends on
    the Controller Type (cntrltype), another attribute of the Identify
    response, the patch also exposes the cntrltype as well. The dctype will
    only be displayed for discovery controllers.

    A note about the naming of this attribute:
    Although TP8010 calls this attribute the Discovery Controller Type,
    note that the dctype is now part of the response to the Identify
    command for all controller types. I/O, Discovery, and Admin controllers
    all share the same Identify response PDU structure. Non-discovery
    controllers as well as pre-TP8010 discovery controllers will continue
    to set this field to 0 (which has always been the default for reserved
    bytes). Per TP8010, the value 0 now means "Discovery controller type is
    not reported" instead of "Reserved". One could argue that this
    definition is correct even for non-discovery controllers, and by
    extension, exposing it in the sysfs for non-discovery controllers is
    appropriate.

    Signed-off-by: Martin Belanger <martin.belanger@dell.com>

commit 68c483a105ce7107f1cf8e1ed6c2c2abb5baa551
Author: Martin Belanger <martin.belanger@dell.com>
Date:   Thu Feb 3 16:04:29 2022 -0500

    nvme: send uevent on connection up

    When connectivity with a controller is lost, the driver will keep
    trying to reconnect once every 10 sec. When connection is restored,
    user-space apps need to be informed so that they can take proper
    action. For example, TP8010 introduces the DIM PDU, which is used to
    register with a discovery controller (DC). The DIM PDU is sent from
    user-space.  The DIM PDU must be sent every time a connection is
    established with a DC. Therefore, the kernel must tell user-space apps
    when connection is restored so that registration can happen.

    The uevent sent is a "change" uevent with environmental data
    set to: "NVME_EVENT=connected".

    Signed-off-by: Martin Belanger <martin.belanger@dell.com>
    Reviewed-by: Hannes Reinecke <hare@suse.de>
    Reviewed-by: Sagi Grimberg <sagi@grimberg.me>
    Reviewed-by: Chaitanya Kulkarni <kch@nvidia.com>

commit f18ee3d988157ebcadc9b7e5fd34811938f50223
Author: Hannes Reinecke <hare@suse.de>
Date:   Tue Dec 7 14:55:49 2021 +0100

    nvme-fabrics: print out valid arguments when reading from /dev/nvme-fabrics

    Currently applications have a hard time figuring out which
    nvme-over-fabrics arguments are supported for any given kernel;
    the ioctl will return an error code on failure, and the application
    has to guess whether this was due to an invalid argument or due
    to a connection or controller error.
    With this patch applications can read a list of supported
    arguments by simply reading from /dev/nvme-fabrics, allowing
    them to validate the connection string.

    Signed-off-by: Hannes Reinecke <hare@suse.de>
    Reviewed-by: Chaitanya Kulkarni <kch@nvidia.com>
    Signed-off-by: Christoph Hellwig <hch@lst.de>


commit e5ea42faa773c6a6bb5d9e9f5c2cc808940b5a55
Author: Hannes Reinecke <hare@suse.de>
Date:   Wed Sep 22 08:35:25 2021 +0200

    nvme: display correct subsystem NQN

    With discovery controllers supporting unique subsystem NQNs the
    actual subsystem NQN might be different from that one passed in
    via the connect args. So add a helper to display the resulting
    subsystem NQN.

    Signed-off-by: Hannes Reinecke <hare@suse.de>
    Reviewed-by: Chaitanya Kulkarni <kch@nvidia.com>
    Signed-off-by: Christoph Hellwig <hch@lst.de>

commit 20e8b689c9088027b7495ffd6f80812c11ecc872
Author: Hannes Reinecke <hare@suse.de>
Date:   Wed Sep 22 08:35:24 2021 +0200

    nvme: Add connect option 'discovery'

    Add a connect option 'discovery' to specify that the connection
    should be made to a discovery controller, not a normal I/O controller.
    With discovery controllers supporting unique subsystem NQNs we
    cannot easily distinguish by the subsystem NQN if this should be
    a discovery connection, but we need this information to blank out
    options not supported by discovery controllers.

    Signed-off-by: Hannes Reinecke <hare@suse.de>
    Reviewed-by: Chaitanya Kulkarni <kch@nvidia.com>
    Signed-off-by: Christoph Hellwig <hch@lst.de>

commit 954ae16681f6bdf684f016ca626329302a38e177
Author: Hannes Reinecke <hare@suse.de>
Date:   Wed Sep 22 08:35:23 2021 +0200

    nvme: expose subsystem type in sysfs attribute 'subsystype'

    With unique discovery controller NQNs we cannot distinguish the
    subsystem type by the NQN alone, but need to check the subsystem
    type, too.
    So expose the subsystem type in a new sysfs attribute 'subsystype'.

    Signed-off-by: Hannes Reinecke <hare@suse.de>
    Reviewed-by: Chaitanya Kulkarni <kch@nvidia.com>
    Signed-off-by: Christoph Hellwig <hch@lst.de>


commit 3ede8f72a9a2825efca23a3552e80a1202ea88fd
Author: Martin Belanger <martin.belanger@dell.com>
Date:   Thu May 20 15:09:34 2021 -0400

    nvme-tcp: allow selecting the network interface for connections

    In our application, we need a way to force TCP connections to go out a
    specific IP interface instead of letting Linux select the interface
    based on the routing tables.

    Add the 'host-iface' option to allow specifying the interface to use.
    When the option host-iface is specified, the driver uses the specified
    interface to set the option SO_BINDTODEVICE on the TCP socket before
    connecting.

    This new option is needed in addtion to the existing host-traddr for
    the following reasons:

    Specifying an IP interface by its associated IP address is less
    intuitive than specifying the actual interface name and, in some cases,
    simply doesn't work. That's because the association between interfaces
    and IP addresses is not predictable. IP addresses can be changed or can
    change by themselves over time (e.g. DHCP). Interface names are
    predictable [1] and will persist over time. Consider the following
    configuration.

    1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state ...
        link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
        inet 100.0.0.100/24 scope global lo
           valid_lft forever preferred_lft forever
    2: enp0s3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc ...
        link/ether 08:00:27:21:65:ec brd ff:ff:ff:ff:ff:ff
        inet 100.0.0.100/24 scope global enp0s3
           valid_lft forever preferred_lft forever
    3: enp0s8: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc ...
        link/ether 08:00:27:4f:95:5c brd ff:ff:ff:ff:ff:ff
        inet 100.0.0.100/24 scope global enp0s8
           valid_lft forever preferred_lft forever

    The above is a VM that I configured with the same IP address
    (100.0.0.100) on all interfaces. Doing a reverse lookup to identify the
    unique interface associated with 100.0.0.100 does not work here. And
    this is why the option host_iface is required. I understand that the
    above config does not represent a standard host system, but I'm using
    this to prove a point: "We can never know how users will configure
    their systems". By te way, The above configuration is perfectly fine
    by Linux.

    The current TCP implementation for host_traddr performs a
    bind()-before-connect(). This is a common construct to set the source
    IP address on a TCP socket before connecting. This has no effect on how
    Linux selects the interface for the connection. That's because Linux
    uses the Weak End System model as described in RFC1122 [2]. On the other
    hand, setting the Source IP Address has benefits and should be supported
    by linux-nvme. In fact, setting the Source IP Address is a mandatory
    FedGov requirement (e.g. connection to a RADIUS/TACACS+ server).
    Consider the following configuration.

    $ ip addr list dev enp0s8
    3: enp0s8: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc ...
        link/ether 08:00:27:4f:95:5c brd ff:ff:ff:ff:ff:ff
        inet 192.168.56.101/24 brd 192.168.56.255 scope global enp0s8
           valid_lft 426sec preferred_lft 426sec
        inet 192.168.56.102/24 scope global secondary enp0s8
           valid_lft forever preferred_lft forever
        inet 192.168.56.103/24 scope global secondary enp0s8
           valid_lft forever preferred_lft forever
        inet 192.168.56.104/24 scope global secondary enp0s8
           valid_lft forever preferred_lft forever

    Here we can see that several addresses are associated with interface
    enp0s8. By default, Linux always selects the default IP address,
    192.168.56.101, as the source address when connecting over interface
    enp0s8. Some users, however, want the ability to specify a different
    source address (e.g., 192.168.56.102, 192.168.56.103, ...). The option
    host_traddr can be used as-is to perform this function.

    In conclusion, I believe that we need 2 options for TCP connections.
    One that can be used to specify an interface (host-iface). And one that
    can be used to set the source address (host-traddr). Users should be
    allowed to use one or the other, or both, or none. Of course, the
    documentation for host_traddr will need some clarification. It should
    state that when used for TCP connection, this option only sets the
    source address. And the documentation for host_iface should say that
    this option is only available for TCP connections.

    References:
    [1] https://www.freedesktop.org/wiki/Software/systemd/PredictableNetworkInterfaceNames/
    [2] https://tools.ietf.org/html/rfc1122

    Tested both IPv4 and IPv6 connections.

    Signed-off-by: Martin Belanger <martin.belanger@dell.com>
    Reviewed-by: Sagi Grimberg <sagi@grimberg.me>
    Reviewed-by: Hannes Reinecke <hare@suse.de>
    Signed-off-by: Christoph Hellwig <hch@lst.de>
```

