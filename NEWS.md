# STorage Appliance Services (STAS)

## Changes with release 3.0

nvme-stas 3.0 is a **non-backward-compatible release**. It requires libnvme 3.0 and nvme-cli 3.0, its configuration files have moved and changed format, and several configuration keys, D-Bus argument names and command-line options were renamed. Nothing from 2.x is aliased: a stale value is meant to fail rather than silently change behaviour.

### Requires libnvme 3.0 and nvme-cli 3.0

libnvme 3.0 introduces significant API changes and drops compatibility with prior versions (≤ 1.x). nvme-stas 3.0 requires libnvme 3.0 at runtime and does not work with earlier releases. The Python bindings are now the `libnvme3` package (`from libnvme3 import nvme`).

nvme-stas also now depends on **nvme-cli** itself, which owns `/etc/nvme` and generates the host identity.

***Note**: the last release of libnvme prior to 3.0 was 1.16.1, and the last release of nvme-cli prior to 3.0 was 2.16. There is no libnvme 2.x — libnvme and nvme-cli were synchronized on 3.0.*

### All configuration now lives in /etc/nvme

`/etc/stas` is gone. `stafd.conf` and `stacd.conf` are now `/etc/nvme/stafd.conf` and `/etc/nvme/stacd.conf`, alongside `nvme-fabrics.conf` and `nvme-discoverd.conf`.

`sys.conf` and the `stasadm` tool are also gone. The host identity comes from the files the nvme-cli family already keeps it in — `/etc/nvme/hostnqn` and `/etc/nvme/hostid` — which `stas-config@.service` still generates when they are missing, using `nvme gen-hostnqn` and `uuidgen`.

### Which controllers to connect to moved to /etc/nvme/nvme-stas.conf

Which controllers to connect to, and with what parameters, moved out of `stafd.conf`/`stacd.conf` and into a new file, `/etc/nvme/nvme-stas.conf`, in **libnvme's INI format**, read by libnvme's own parser. One format, one parser: nvme-stas, the nvme-cli tools and nvme-discoverd all read the same thing. nvme-stas reads its *own* file, because a host must be able to run nvme-stas and nvme-discoverd side by side without either acting on the other's configuration. Drop-ins are read from `/etc/nvme/nvme-stas.conf.d/*.conf`, one host persona per file.

One file serves both daemons: stafd takes the `[Discovery Controller]` sections, stacd the `[Subsystem]` ones.

Concretely:

* The `controller=` keyword of the `[Controllers]` section is **gone from `stafd.conf`/`stacd.conf`**. A Discovery Controller is now a `[Discovery Controller]` section, and an I/O subsystem a `[Subsystem]` section with one `controller=` line per path. An entry left behind in the old files is reported in the log rather than silently ignored.
* The connection tunables are gone from `[Global]`: `kato`, `queue-size`, `reconnect-delay`, `ctrl-loss-tmo`, `nr-io-queues`, `nr-write-queues`, `nr-poll-queues`, `hdr-digest`, `data-digest`, `disable-sqflow` and the authentication keys are all set in `nvme-stas.conf` now, under their `nvme connect` names (`kato` is `keep-alive-tmo` there). `stafd.conf` and `stacd.conf` are left to daemon behaviour alone.
* The host symbolic name and the KX-HMAC-CHAP secrets are set in the `[Host]` section of `nvme-stas.conf`. An identity is taken whole or not at all — nvme-stas never pairs a configured host NQN with the system's host ID.
* `stafd` and `stacd` take a new `--conn-conf-file` (`-c`) option to point at a different connectivity configuration.
* A file that does not validate is rejected and the last known good one keeps running, so a fat-fingered edit never tears down working connections.

See the new `nvme-stas.conf(5)` man page.

### nvme-stas no longer disconnects connections it did not make

libnvme's **ownership registry** records who made each NVMe-oF connection. stafd and stacd consult it before adopting a connection, and a controller owned by somebody else is left alone. This closes a long-standing hazard: with `disconnect-scope=all-connections-matching-disconnect-trtypes`, stacd used to tear down connections made by nvme-discoverd, by a human running `nvme connect`, or by the initramfs from the NBFT — which is how it came to disconnect FC connections on hosts that used stacd for TCP only.

* `disconnect-scope` and `disconnect-trtypes` are **replaced** by a single `honor-fabric-zoning = yes | no` (default `yes`). `yes` is what `only-stas-connections` did; `no` is what `no-disconnect` did. The old values are not accepted.
* nvme-stas no longer shadows nvme-cli's `70-nvmf-autoconnect.rules` with an override in `/run/udev/rules.d`. The registry settles the race at the source: `nvme connect-all` reads the Discovery Controller's owner and does nothing when it belongs to somebody else. A stale override left by a 2.x installation is removed at startup.
* NBFT controllers are no longer folded into the set stafd and stacd manage — they were connected by the initramfs and are not nvme-stas' to manage. Note the consequence: stafd no longer connects to an NBFT discovery controller, so its log pages no longer reach stacd unless that controller is also configured or discovered.
* stacd no longer keeps a "last known config" file. On startup it asks the kernel what is connected and the registry who owns it. stacd no longer writes to `$RUNTIME_DIRECTORY` at all. stafd keeps its file, which holds the cached discovery log pages and each controller's origin.

### libnvme's host-wide exclusion list is honored

Exclusions could previously only be configured with the `exclude=` keyword. nvme-stas now also honors libnvme's host-wide exclusion list — `/etc/nvme/exclusions.conf` and `/etc/nvme/exclusions.conf.d/`, managed with `nvme exclusion` — so an administrator's exclusions apply to every NVMe-oF tool on the host, and `nvme disconnect --exclude` is no longer undone by the next reconnect. The list is re-read on every connection attempt, so an entry takes effect with no reload.

A controller is excluded if it matches either source. `exclude=` still works but is **deprecated** and will be removed in a future release.

Exclusions are now also checked on the connect path, not only when the list of managed controllers is rebuilt. A controller excluded while the daemons were running could previously still be reconnected by the retry timer.

### Discovery controller connection management

Whether a Discovery Controller's connection is held open is now the `persistent` key of the connectivity configuration, settable per DC. It defaults to `auto` — hold it open wherever the DC reports through the EPCSD flag that it supports one. That differs from libnvme, whose unset value behaves as `no`, because a daemon that exists to be told when discovery log pages change cannot default to disconnecting; it is the same choice nvme-discoverd makes.

A DC that does not support a persistent connection is *parked*: nvme-stas disconnects, keeps its log pages, and re-reads them on a timer, since the DC cannot report that they changed. The new `epcsd-poll-interval-minutes` in `stafd.conf` sets how often (default 15; 0 is not valid, as the poll is the only way back).

* `persistent-connections` is gone. What is kept on exit is now simply whatever is still held open.
* `zeroconf-connections-persistence` is renamed **`dc-giveup-timeout`**, and nvme-discoverd takes the same key with the same encoding. The old `-1` is gone: use `infinity` to never give up, and a negative value is now rejected.

### Time spans are parsed the way systemd parses them

`dc-giveup-timeout` is a time span, and a span a user writes once has to mean one thing in both nvme-stas and nvme-discoverd. The parser was a vendored copy of pytimeparse with a grammar of its own; it now implements systemd's, as documented in `systemd.time(7)`.

Spans that only pytimeparse accepted — `hrs`/`secs`/`mins`/`dy`, uppercase units, comma-separated terms, colon notation, `inf`/`1e5`/`nan` — now fall back to the default with a warning. Spans that only systemd accepts — `500ms`, `1week`, `1y` — now work. **One value keeps parsing and changes meaning: `1M` was 60 seconds and is now one month** (`m` is minutes, `M` is months).

### Renamed

* **`dhchap` → `kxchap`**, following TP4201, which renames the crypto-related fields. The configuration keys are `kxchap-secret` and `kxchap-ctrl-secret`. The kernel option names in `/dev/nvme-fabrics` and the nvmet configfs attributes are unchanged.
* **`host-nqn` → `hostnqn`**, the spelling libnvme, nvme-cli and the kernel all use. This changes the key in the controller-identifier dicts published over D-Bus, the D-Bus method and signal argument names, and `stafctl`'s `--host-nqn` option, now `--hostnqn`. **The D-Bus data format shared by stafd, stacd, stafctl and stacctl is not compatible with 2.x.**
* Discovery Log Page Entry subtypes and TREQ are now spelled the way libnvme's own decoders spell them, so `stafctl dlp` reports, for example, `nvme subsystem` rather than `nvme`.

### Bug fixes

* **stacd no longer disconnects everything when it cannot reach stafd.** `_get_log_pages_from_stafd()` returned an empty list both when stafd said "nothing is discovered" and when it could not be reached at all, so no information read as negative information and, with `honor-fabric-zoning` on, every discovered controller was disconnected. Nothing orders stacd after stafd, so this needed no outage — only stafd being slow to claim its bus name.
* **An IPv4-mapped address is an IPv4 address.** A target listening on the IPv6 wildcard reports `::ffff:1.2.3.4` where another would report `1.2.3.4`. A host configured with `ip-family=ipv4` discarded those controllers, and `exclude=1.2.3.4` did not exclude them.
* **A Discovery Controller that cannot answer Get Supported Log Pages now gets its log pages read anyway.** The failure used to be retried forever, so the discovery log pages were never retrieved and stacd learned of no I/O controllers — which is what a plain nvmet target did with the default `pleo=enabled`. PLEOS is only consulted to decide whether to set PLEO, so it is assumed to be 0.
* A parked Discovery Controller is no longer talked to. The disconnect leaves a wake of udev events that used to start a log page retrieval against a controller that was no longer there.
* A bare `exclude=` line, which sets no field, used to exclude every controller. It is now dropped.
* Exclusion matching compares addresses in normalized form, so `fe80::1` and its expanded spelling designate the same controller.

### Development and packaging

* **ruff** replaces pylint, pyflakes and black. `make check-format` verifies the code before submitting a pull request.
* CodeQL static analysis was added to CI, the workflows were reworked, and the linters now actually see `staslib` — a `.gitignore` interaction meant they never had.
* Unit test coverage grew substantially; the automated `make coverage` run now stands at 95%, and runs the daemons against a `/etc/nvme` the script writes itself so a run does not depend on what the machine happens to have.
* Running stafd and stacd in containers is documented as an unsupported deployment model, and the Docker artifacts were removed. See `CONTAINERS.md`.

## Changes with release 2.4.1


Bug fix:

* Restore backward compatibility with libnvme 1.11 and earlier. The controller attribute `discovery_ctrl` was added in libnvme 1.12. Prior to this version, the method `discovery_ctrl_set()` is to be used.

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

