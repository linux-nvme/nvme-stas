# STorage Appliance Services (STAS)

## Changes with release 2.0

Because of incompatibilities between 1.1.6 and 1.2 (ref. `sticky-connections`), it was decided to skip release 1.2 and have a 2.0 release instead. Release 2.0 contains everything listed in 1.2 (below) plus the following:

* Add support for PLEO - Port-Local Entries Only, see TP8010.
  * Add new configuration parameter to stafd.conf: `pleo=[enabled|disabled]`
  * This requires `libnvme` 1.2 or later although nvme-stas can stil operate with 1.1 (but PLEO will not be supported).

## ~~Changes with release 1.2~~ (never released - use 2.0 instead)

- In `stacd.conf`, add a new configuration section, `[I/O controller connection management]`.
  - This is to replace `sticky-connections` by `disconnect-scope` and `disconnect-trtypes`, which is needed so that hosts can better react to Fabric Zoning changes at the CDC.
  - Add `connect-attempts-on-ncc` to control how stacd will react to the NCC bit (Not Connected to CDC).
- When the host's symbolic name is changed in `sys.conf`, allow re-issuing the DIM command (register with DC) on a `reload` signal (`systemctl reload stafd`).
- Replace `blacklist=` by `exclude=` is `stafd.conf` and `stacd.conf`. Warning: this may create an incompatibility for people that were using `blacklist=`. They will need to manually migrate their configuration files.
- Change `TID.__eq__()` and `TID.__ne__()` to recognize a TID object even when the `host-iface` is not set. This is to fix system audits where `nvme-stas` would not recognize connections made by `nvme-cli`. The TID object, or Transport ID, contains all the parameters needed to establish a connection with a controller, e.g. (`trtype`, `traddr`, `trsvcid`, `nqn`, `host-traddr`, and `host-iface`). `nvme-stas` can scan the `sysfs` (`/sys/class/nvme/`) to find exiting NVMe connections. It relies on the `address` and other attributes for that. For example the attribute `/sys/class/nvme/nvme0/address` may contain something like:  `traddr=192.168.56.1,trsvcid=8009,host_iface=enp0s8`.

  `nvme-stas` always specify the `host-iface` when making connections but `nvme-cli` typically does not. Instead, `nvme-cli` relies on the routing table to select the interface. This creates a discrepancy between the `address` attribute of connections made by `nvme-cli` and those made by `nvme-stas` (i.e. `host_iface=` is missing for `nvme-cli` connections). And this results in `nvme-stas` not being able to recognize connections made by `nvme-cli`. Two solutions have been proposed to workaround this problem:

  - First, a short term solution changes `TID.__eq__()` and `TID.__ne__()` so that the `host-iface` has a lesser weight when comparing two TIDs. This way, the TID of a connection created by `nvme-cli` can be compared to the TID of a connection made with `nvme-stas` and still result in a match. The downside to this approach is that a connection made with `nvme-cli` that is going over the wrong interface (e.g. bad routing table entry), will now be accepted by `nvme-stas` as a valid connection.  
  - Second, a long term solution that involves a change to the kernel NVMe driver will allow being able to determine the host interface for any NVMe connections, even those made without specifying the `host-iface` parameter. The kernel driver will now expose the source address of all NVMe connections through the `sysfs`. This will be identified by the key=value pair "`src-addr=[ip-address]`" in the `address` attribute. And from the source address one can infer the actual host interface. This actually will solve the shortcomings of the "short term" solution discussed above. Unfortunately, it may take several months before this kernel addition is available in a stock Distribution OS. So, the short term solution will need to suffice for now.

## Changes with release 1.1.6

- Fix issues with I/O controller connection audits
  - Eliminate pcie devices from list of I/O controller connections to audit
  - Add soaking timer to workaround race condition between kernel and user-space applications on "add" uevents. When the kernel adds a new nvme device (e.g. `/dev/nvme7`) and sends a "add" uevent to notify user-space applications, the attributes associated with that device (e.g. `/sys/class/nvme/nvme7/cntrltype`) may not be fully initialized which can lead `stacd` to dismiss a device that should get audited. 
- Make `sticky-connections=enabled` the default (see `stacd.conf`) 

## Changes with release 1.1.5

- Fix issues introduced in 1.1.3 when enabling Fibre Channel (FC) support. 
  - Eliminate pcie devices from discovery log pages. When enabling FC, pcie was accidentally enabled as well.
  - Fix I/O controller scan and detect algorithm. Again, while adding support for FC, the I/O scan & detect algorithm was modified, but we accidentally made it detect Discovery Controllers as well as I/O controllers.


## ~~Changes with release 1.1.4~~ USE 1.1.5 INSTEAD.

- Fix issues for Fibre Channel (FC) support. 
- Add TESTING.md

## Changes with release 1.1.3

**stacd**: Add I/O controller connection audits. Audits are enabled when the configuration parameter "`sticky-connections`" is disabled.

**stafd**: Preserve and Reload last known configuration on restarts. This is for warm restarts of the `stafd` daemon. This does not apply to system reboots (cold restarts). This is needed to avoid deleting I/O controller (IOC) connections by mistake when restarting `stafd`. It prevents momentarily losing previously acquired Discovery Log Page Entries (DLPE). Since `stacd` relies on acquired DLPEs to determine which connection should be created or deleted, it's important that the list of DLPEs survives a `stafd` restart. Eventually, after `stafd` has restarted and reconnected to all Discovery Controllers (DC), the list will get refreshed and the DLPE cache will get updated. And as the cache gets updated, `stacd` will be able to determine which connections should remain and which one should get deleted.

**`stafd`/`stacd`**: Fixed crash caused by `stafd`/`stacd` calling the wrong callback function during the normal disconnect of a controller. There are two callback functions that can be called after a controller is disconnected, but one of them must only be called on a final disconnect just before the process (`stafd` or `stacd`) exits. The wrong callback was being called on a normal disconnect, which led the process to think it was shutting down.

## ~~Changes with release 1.1.2~~ USE 1.1.3 INSTEAD.

stacd: Bug fix. Check that self._cfg_soak_tmr is not None before dereferencing it.

## Changes with release 1.1.1

Make `sticky-connections=disabled` the default (see `stacd.conf`) 

## Changes with release 1.1

- Add `udev-rule` configuration parameter to `stacd.conf`.
- Add `sticky-connections` configuration parameter to `stacd.conf`.
- Add coverage testing (`make coverage`)
- Add `make uninstall`
- To `README.md`, add mDNS troubleshooting section.

## Changes with release 1.0.1

- Install staslib as pure python package instead of arch-specific.

## Changes with release 1.0

- First public release following TP8009 / TP8010 ratification and publication.

## Changes with release 0.1:

- Initial release

