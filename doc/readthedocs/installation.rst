Installation
============

Debian / Ubuntu:
----------------

.. code-block:: sh

    $ sudo apt-get install nvme-stas

Fedora / Red Hat:
-----------------

.. code-block:: sh

    $ sudo dnf install nvme-stas

openSUSE / SLES:
----------------

.. code-block:: sh

    $ sudo zypper install nvme-stas

Building from Source:
---------------------

.. code-block:: sh

    $ git clone https://github.com/linux-nvme/nvme-stas.git
    $ cd nvme-stas
    $ meson setup .build
    $ meson compile -C .build
    $ sudo meson install -C .build

For more details on building from source and distro-specific packaging guidelines,
see `DISTROS.md <https://github.com/linux-nvme/nvme-stas/blob/main/DISTROS.md>`_.

Python Version
--------------

The latest Python 3 version is always recommended, since it has all the latest bells and
whistles. nvme-stas works with Python 3.6 and above.

Dependencies
------------

nvme-stas is built on top of libnvme, which is used to interact with the kernel's NVMe driver (i.e. drivers/nvme/host/). To support all the features of nvme-stas, several changes to the Linux kernel are required. nvme-stas can also operate with older kernels, but with limited functionality. Kernel 5.18 provides all the features needed by nvme-stas. nvme-stas can also work with older kernels that include back-ported changes to the NVMe driver.

Key runtime dependencies:

* **libnvme 3.0+** - NVMe userspace library (Python bindings)
* **python3-dasbus** - D-Bus bindings
* **python3-pyudev** - udev integration
* **python3-systemd** - systemd/journald integration
* **python3-gi** - GObject introspection
* **avahi-daemon** - mDNS service discovery (required for stafd)

