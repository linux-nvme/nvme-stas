# Feature Comparison: nvme-stas vs. nvme-cli

| Feature | nvme-stas | nvme-cli |
| --- | --- | --- |
| IP address family filter | **Yes** – configured via `ip-family=[ipv4, ipv6, ipv4+ipv6]` in `/etc/stas/*.conf` | **No** |
| Automatic DIM registration with a Central Discovery Controller (CDC) per TP8010 | **Yes** | **No** – manual only via `nvme dim` |
| Automatic (zeroconf) discovery of Direct/Central Discovery Controllers (DDC/CDC) | **Yes** – registers with the Avahi daemon to receive mDNS notifications when CDCs or DDCs are detected, and connects to them automatically | **No** |
| Manual Discovery Controller (DC) configuration with explicit include/exclude | **Yes** – use `controller=` and `exclude=` in `/etc/stas/stafd.conf`; exclusions are useful for filtering out unwanted mDNS-discovered DCs | **Partial** – no way to exclude DCs (moot since mDNS is not supported); use `/etc/nvme/discovery.conf` to include controllers |
| Manual I/O Controller (IOC) configuration with explicit include/exclude | **Yes** – use `controller=` and `exclude=` in `/etc/stas/stacd.conf`; exclusions filter out unwanted IOCs from log pages (ideally handled via proper zone definitions at the DC) | **Partial** – JSON config files are supported, but excluding IOCs is not possible |
| AEN monitoring + automatic connection/disconnection for Fabric Zoning | **Yes** – responds to Fabric Zoning changes with connect and disconnect operations with retries (configurable via `/etc/stas/stacd.conf`) | **Partial** – responds to Fabric Zoning changes with connect-only, no retries (one-shot udev rule) |
| Use PLEO bit to retrieve only Port Local Entries from log pages | **Yes** | **No** |
| Automatic Layer 3 connectivity without static routes | **Yes** – configurable via `ignore-iface=` in `/etc/stas/*.conf` | **No** – manual only via `--host-iface` |
| Explicit exclusion of specific discovery interfaces | **Yes** – use `exclude = host-iface=<interface>` in `/etc/stas/*.conf` | **No** – not applicable without mDNS support |
| AVE client support | **Planned** (implementation TBD) | **No** |
| Human-friendly `nvme list` output | **No** – `stafctl` and `stacctl` output JSON only; not a significant gap since `nvme list -v` covers this well | **Yes** – via `nvme list -v` |
