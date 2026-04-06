# Why nvme-stas Does Not Run in Containers

Containers (Docker, Podman, etc.) are the right tool for packaging and isolating network services, web applications, and stateless workloads. nvme-stas is none of those things. This document explains why containerizing `stafd` and `stacd` is not practical, and why it is not a supported or tested deployment target.

## What nvme-stas Actually Does

`stafd` and `stacd` are **systemd daemons** that manage NVMe-over-Fabrics (NVMe-oF) controller connections on behalf of a Linux host. They operate at the boundary between user space and the kernel's NVMe-oF subsystem, reacting to mDNS announcements, udev events, and D-Bus signals to automatically connect and disconnect NVMe-oF controllers as the fabric topology changes.

This is fundamentally **host-level infrastructure**, not an application service. The daemons are as tightly coupled to the host OS as a network manager or a storage daemon would be.

## The Technical Obstacles

### 1. NVMe kernel modules must be loaded on the host

`stafd` and `stacd` communicate with the kernel via `/dev/nvme-fabrics`, which is only present when the `nvme-tcp` (or `nvme-rdma`) kernel module is loaded. Kernel modules are always **host-scoped** — a container cannot load them, and the host must have them loaded before the container starts. The `/dev/nvme-fabrics` device node (and any `/dev/nvme*` nodes that appear as connections are established) must be explicitly passed through to the container with `--device` or `--privileged`.

### 2. All NVMe-oF operations happen in the host's kernel

NVMe-oF connection state lives in the **host kernel**, not in any process. When `stacd` tells the kernel to connect to a controller, that connection belongs to the host, not to the container. The container is just a thin wrapper around a process that happens to issue those kernel calls. Stopping or removing the container does not disconnect the NVMe controllers — those remain in the kernel until explicitly disconnected. This makes lifecycle management (start, stop, restart, upgrade) unreliable in a container model.

### 3. D-Bus is a host-scoped system bus

Both daemons publish objects on the **system D-Bus** (`org.nvmexpress.staf` and `org.nvmexpress.stac`). System D-Bus is a host-level resource. A container cannot join the host's system bus without bind-mounting the host's D-Bus socket (`/var/run/dbus/system_bus_socket`) into the container, which is a significant security exposure and tightly couples the container to the host's D-Bus configuration and policy files.

### 4. Avahi (mDNS) runs on the host

`stafd`'s zero-configuration discovery relies on the **Avahi daemon**, which listens for `_nvme-disc._tcp` mDNS announcements on the host's network interfaces. Avahi itself communicates over D-Bus. For `stafd` to receive mDNS discovery events from inside a container, it would need access to the host D-Bus (see above) and Avahi running on the host — there is no supported way to use the host's Avahi from within a network namespace.

### 5. udev events are host-scoped

`stafd` and `stacd` subscribe to **udev** events to detect when NVMe controller devices appear or disappear (e.g. `/dev/nvme0`). udev is a host service. Containers do not receive udev events by default; doing so requires running with `--privileged` or `--net=host` and specific capability grants, which eliminates the isolation that containers provide.

### 6. systemd integration

Both daemons use `sd_notify()` to signal readiness and status to **systemd**. This mechanism does not function correctly inside a container unless a full init system is present (which itself defeats the purpose of a minimal container image) or the systemd socket is explicitly forwarded.

### 7. The privilege requirements cancel out the isolation benefits

To work around all of the above, a container running `stafd`/`stacd` would need at minimum:

- `--privileged` (or a large set of Linux capabilities)
- `--net=host`
- Bind-mount of `/var/run/dbus`
- Bind-mount or volume for `/run/nvme-stas`
- Bind-mount of `/dev`

At that point, the container has essentially unrestricted access to the host and provides no meaningful isolation. The operational complexity is strictly greater than simply running the daemons as systemd units, which is what they are designed to be.

## The Right Deployment Model

`stafd` and `stacd` should be installed as **systemd services** directly on the host, either via the distribution's package manager or via `meson install`. This is the only deployment model that is tested, supported, and makes architectural sense given their role.

See [DISTROS.md](./DISTROS.md) for distribution-specific installation instructions.
