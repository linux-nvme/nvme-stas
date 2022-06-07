# STorage Appliance Services (STAS)

## Changes with release 1.1.3

stacd: Add I/O controller connection audits. Audits are enabled when
the configuration parameter "sticky-connections" is disabled.

stafd: Preserve and Reload last known configuration on restarts. This is for
warm restarts of the stafd daemon. This does not apply to system reboots (cold
restarts). This is needed to avoid deleting I/O controller (IOC) connections by
mistake when restarting stafd. It prevents momentarily losing previously
acquired Discovery Log Page Entries (DLPE). Since stacd relies on acquired DLPEs
to determine which connection should be created or deleted, it's important that
the list of DLPEs survives a stafd restart. Eventually, the list will get
refreshed as stafd reconnects with all the Discovery Controllers (DC) and
updates its DLPE cache. And as the cache gets refreshed, stacd will be able
to determine which connections should remain and which one should ge deleted.

## Changes with release 1.1.2

stacd: Bug fix. Check that self._cfg_soak_tmr is not None before dereferencing it.

## Changes with release 1.1.1

Make `sticky-connections-disabled` by default

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

