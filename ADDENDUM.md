# **nvme-stas Addendum**

## **D-Bus Interface**

Both **`stafd`** and **`stacd`** expose D-Bus interfaces that allow external programs—including **`stafctl`** and **`stacctl`**—to communicate with the daemons. Third-party applications can also integrate with *nvme-stas* via these APIs. For example, a graphical utility could display available discovery controllers or present discovery log pages in a visual format.

**D-Bus Service Names**

| Component | D-Bus Service Name             |
| --------- | ------------------------------ |
| `stafd`   | **`org.nvmexpress.staf.conf`** |
| `stacd`   | **`org.nvmexpress.stac.conf`** |

------

## **Troubleshooting Service Discovery with Avahi**

**`stafd`** can automatically discover and connect to Discovery Controllers using mDNS/DNS-SD via the [Avahi](https://www.avahi.org/) daemon. Controllers advertising the `_nvme-disc._tcp` service type will be detected by Avahi and forwarded to **`stafd`**.

### **Not Receiving mDNS Packets?**

If **`stafd`** is not detecting any discovery controllers via Avahi, the firewall may be filtering mDNS packets. If you know that Discovery Controllers are actively advertising, check whether Avahi is receiving the packets:

```
avahi-browse -t -r _nvme-disc._tcp
```

If no services appear, verify that your firewall allows UDP multicast on port **5353** (mDNS).

### **Why Avahi Fails on Some Interfaces**

Linux limits the number of multicast group memberships per socket. The default (`igmp_max_memberships`) is **20**. Avahi joins one multicast group per network interface—whether physical or logical. For example, adding multiple VLANs increases the number of logical interfaces.

If the total interface count exceeds this limit, Avahi will be unable to listen on all of them, causing incomplete service discovery.

To increase the limit, update the `igmp_max_memberships` sysctl parameter. Useful references:

- Kernel documentation: https://sysctl-explorer.net/net/ipv4/igmp_max_memberships/
- Discussion and examples: https://unix.stackexchange.com/questions/23832/is-there-a-way-to-increase-the-20-multicast-group-limit-per-socket

------

## **Testing**

For information on executing or writing tests, refer to:
 **[TESTING.md](./TESTING.md)**

------

## **Make Wrappers**

To streamline Meson workflows, several operations are wrapped in convenient `make` targets:

| Make Target                   | Description                                                  |
| ----------------------------- | ------------------------------------------------------------ |
| **`make`**                    | Builds the project. Automatically runs `.configure` with default parameters if necessary. |
| **`make install`**            | Installs the software (requires root privileges).            |
| **`make uninstall`**          | Removes installed files (requires root privileges).          |
| **`make test`**               | Executes the unit test suite.                                |
| **`make clean`**              | Removes build artifacts but preserves the Meson configuration in `.build`. |
| **`make purge`**              | Removes *all* build artifacts, including the `.build` directory. |
| **`make update-subprojects`** | Updates subprojects such as `nvme-cli`.                      |
| **`make black`**              | Verifies compliance with `black` coding style.               |

------

## **Generating Documentation**

*nvme-stas* uses external tools to generate man pages and HTML documentation:

- **`xsltproc`** — Converts DocBook XML into man and HTML formats.
- **`gdbus-codegen`** — Converts D-Bus IDL files into DocBook XML.

### **Document Generation Dependencies**

Install the following packages depending on your distribution:

**Debian-based systems (tested on Ubuntu 20.04 and 22.04):**

```
sudo apt-get install -y docbook-xml docbook-xsl xsltproc libglib2.0-dev
```

**RPM-based systems (tested on Fedora 34–37 and SLES15):**

```
sudo dnf install -y docbook-style-xsl libxslt glib2-devel
```

------

### **Building Man and HTML Pages**

Documentation generation is disabled by default. To enable it, reconfigure Meson with the appropriate flags. If necessary, purge any previous build configuration:

```
make purge
./configure -Dman=true -Dhtml=true
make
```