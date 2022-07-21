# STorage Appliance Services (STAS)

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

