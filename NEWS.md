# STorage Appliance Services (STAS)

## Changes with release 2.4

New features:

Support for authentication

Bug fix:

* Various fixes related to unit testing and GitHub Actions

## Changes with release 2.3.1

Bug fix:

* Properly handle big-endian data in `iputils.py`. This fix ensures that `struct.[pack|unpack]` is invoked with the CPU's native endianness. This fix is required for nvme-stas to work properly on big-endian CPUs (little-endian CPUs are not affected).

## Changes with release 2.3

New features:

- Support for nBFT (NVMe-oF Boot Table). 
- The Avahi driver will now verify reachability of services discovered through mDNS to make sure all discovered IP addresses can be connected to. This avoids invoking the NVMe kernel driver with invalid IP addresses and getting error messages in the syslog. While testing this feature, we found that the CDC may advertise itself (using mDNS) before it is actually ready to receive connections from the host. If a host reacting to mDNS advertisements tries to connect to the CDC before the CDC is listening for connections, a "Connection refused" will happen and the host may conclude that the CDC is not reachable. For that reason the host will keep trying to connect in the background. Retries will initially happen at a face pace and gradually be done at a slower pace. 
- The Avahi driver will now print an error message if the same IP address is found on multiple interfaces. This indicates a misconfiguration of the network.
- Simplify algorithm that determines if an existing connection (is sysfs) can be reused by stafd/stacd instead of creating a duplicate connection.
- Improve scalability. First, the algorithm that handles kernel events was reworked to handle events faster. Second, limit the amount of times that the netlink kernel interface is invoked. Instead invoke netlink once and cache & reuse the data for the whole duration of the scanning loop.

Bug fixes:

* For TCP transport: use `sysfs` controller  `src_addr` attribute when matching to a configured "candidate" controller. This is to determine when an existing controller (located under the `sysfs`) can be reused instead of creating a new one. This avoids creating unnecessary duplicate connections.
* Udev event handling: use `systemctl restart` instead of `systemctl start`. There is a small chance that a `start` operation has not completed when a new `start` is required. Issuing a `start` while a `start` is being performed has no effect. However, a `restart` will be handled properly.
* `stafd`: Do not delete and recreate DC objects on kernel events indicating that an nvme device associated to a discovery controller was removed by the kernel. This was done to kick start the reconnect process, but was also causing the DLPE (Discovery Log Page Entries) cache to be lost. This could potentially result in `stacd` disconnecting from I/O controllers. Instead, keep the existing DC object which contains a valid DLPE cache and simply restart the "retry to connect" timer. This way the DLPE cache is maintained throughout the reconnect to DC process.
* While testing Boot from SAN (BFS) and using a Host NQN during boot that is different from the Host NQN used after boot (i.e. the Host NQN defined in `/etc/nvme/hostnqn`), we found that nvme-stas and libnvme are reusing existing connections even if the Host NQN doesn't match. nvme-stas will now take a connection's Host NQN into consideration before deciding if a connection can be reused. A similar fix will be provided in libnvme as well.
* `Udev._cid_matches_tid()` - When checking `subsysnqn`, take well-known NQN (`nqn.2014-08.org.nvmexpress.discovery`) into account. Per TP8013, Discovery Controllers may use a unique NQN instead of the well-known NQN. This can cause a discrepancy between the candidate connection DC and existing connections and cause a matching existing connection to fail to match the candidate connection. 

## Changes with release 2.2.3

Bug fixes:

* When processing kernel nvme events, only react to `rediscover` and not to `connected` events. The `connected` event happens too early (before the nvme device has been fully identified).

## Changes with release 2.2.2

Bug fixes:

* Fix migration of old "last known config" to new format. Old TID objects did not contain a `_cfg` member. Therefore, one needs to check for its existence (through introspection) before blindly trying to access it.

## Changes with release 2.2.1

Added a few more unit and coverage tests. Fixed the following bugs.

Bug fixes:

* Fix errors with some debug commands (e.g. `stafctl ls --detailed`)
* Fix setting controller DHCHAP key (this requires [corresponding changes in libnvme](https://github.com/linux-nvme/libnvme/pull/597)) 

## Changes with release 2.2

Support for in-band authentication. 

## Changes with release 2.1.3

This release is all about `udev rules`. As explained in [DISTROS.md](./DISTROS.md), `nvme-stas` and `nvme-cli` compete for the same kernel events (a.k.a. uevents or udev events). Those are events generated by the kernel related to Discovery Controller (DC) state changes. For example, an AEN indicating a change of Discovery Log Page (DLP), or an event indicating that the the connection to a DC was restored (event = `connected` or  `rediscover`), which means that the DLP needs to be refreshed and connections to controllers listed in the DLP need to be updated.

When both `nvme-stas` and `nvme-cli` are allowed to react and process these events, we have a race condition where both processes try to perform the same connections at the same time. Since the kernel will not allow duplicate connections, then one process will get an error. This is not a real problem since the connection does succeed, but the kernel will log an error and this can be irritating to users.

We tried different ways to fix this issue. The simplest was to disable the `udev rules` installed by `nvme-cli`. This prevents `nvme-cli` from reacting to udev events and only `nvme-stas` gets to process the events. The downside to this is that `nvme-stas`   only expects udev events from DCs that it manages. If a DC connection is made outside of `nvme-stas` (e.g. using `nvme-cli`) and `nvme-stas` receives an event for that DC, it won't know what to do with it and will simply ignore it.

To solve this issue, and to eliminate the race condition, this release of `nvme-stas` includes changes that allows `nvme-stas` to react and process events even for DCs that are not managed by `nvme-stas`. In that case, `nvme-stas` invokes `nvme-cli's` standard event handler. While `nvme-stas` is running, `nvme-cli's`  `udev rules` will be disabled and all event handling will be performed by `nvme-stas`.  `nvme-cli's` `udev rules` are restored when `nvme-stas` is stopped.

With this change we no longer need to provide the configuration parameter `udev-rule=[enabled|disabled]` in `stacd.conf`. This parameter is therefore deprecated.

This release also adds the "[black](https://github.com/psf/black)" code formatter to the GitHub actions. From now on, code submitted as a pull request with GitHub must comply to black's code format. A new command, `make black`, has been added to allow users to verify their code before submitting a pull request.

## Changes with release 2.1.2

* Bug fixes:
  * Add support for RoCE and iWARP protocols in mDNS TXT field (i.e. `p=roce`, `p=iwarp`)
  * Add `_nvme-disc._udp` to the list of supported mDNS service types (stype)

## Changes with release 2.1.1

* Bug fixes:
  * Fix handling of unresponsive zeroconf-discovered Discovery Controllers.  Sometimes we could have a timeout during twice as long as normal.
  * Set default value of legacy "[Global] persistent-connections=false"
  * Add `ControllerTerminator` entity to deal with potential (rare) cases where Connect/Disconnect operations could be performed in reverse order.
* Add more unit tests
* Increase code coverage
* Improve name resolution algorithm
* Set udev event priority to high (for faster handling) 

## Changes with release 2.1

* Bug fixes:
  * Immediately remove existing connection to Discovery Controllers (DC) discovered through zeroconf (mDNS) when added to `exclude=` in `stafd.conf`. Previously, adding DCs to `exclude=` would only take effect on new connections and would not apply to existing connections.
  * When handling "key=value" pairs in the TXT field from Avahi, "keys" need to be case insensitive.
  * Strip spaces from Discovery Log Page Entries (DLPE). Some DCs may append extra spaces to DLPEs (e.g. IP addresses with trailing spaces). The kernel driver does not expect extra spaces and therefore they need to be removed.
* In `stafd.conf` and `stacd.conf`, added new configuration parameters to provide parity with `nvme-cli`:
  * `nr-io-queues`, `nr-write-queues`, `nr-poll-queues`, `queue-size`, `reconnect-delay`, `ctrl-loss-tmo`, `duplicate-connect`, `disable-sqflow`
* Changes to `stafd.conf`:
  * Move  `persistent-connections` from the `[Global]` section to a new section named `[Discovery controller connection management]`.  `persistent-connections` will still be recognized from the `[Global]` section, but will be deprecated over time.
  * Add new configuration parameter `zeroconf-connections-persistence` to section `[Discovery controller connection management]`. This parameter allows one to age Discovery Controllers discovered through zeroconf (mDNS) when they are no longer reachable and should be purged from the configuration. 
* Added more configuration validation to identify invalid Sections and Options in configuration files (`stafd.conf` and `stacd.conf`).
* Improve dependencies in meson build environment so that missing subprojects won't prevent distros from packaging the `nvme-stas` (i.e. needed when invoking meson with the `--wrap-mode=nodownload`  option)
* Improve Read-The-Docs documentation format.

## Changes with release 2.0

Because of incompatibilities between 1.1.6 and 1.2 (ref. `sticky-connections`), it was decided to skip release 1.2 and have a 2.0 release instead. Release 2.0 contains everything listed in 1.2 (below) plus the following:

* Add support for PLEO - Port-Local Entries Only, see TP8010.
  * Add new configuration parameter to stafd.conf: `pleo=[enabled|disabled]`
  * This requires `libnvme` 1.2 or later although nvme-stas can still operate with 1.1 (but PLEO will not be supported).
  * Although `blacklist=` is deprecated, keep supporting it for a while.
  * Target `udev-rule=` at TCP connections only.
  * Read-the-docs will now build directly from source (instead of using a possibly stale copy)
  * More unit tests were added
  * Refactored the code that handles pyudev events in an effort to fix spurious lost events.

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

