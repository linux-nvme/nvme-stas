Installation
============

Debian / Ubuntu:
----------------

.. code-block:: sh

    $ apt-get install nvme-stas

Fedora / Red Hat:
-----------------

.. code-block:: sh

    $ dnf install nvme-stas

Python Version
--------------

The latest Python 3 version is always recommended, since it has all the latest bells and
whistles. nvme-stas works with Python 3.6 and above.

Dependencies
------------

nvme-stas is built on top of libnvme, which is used to interact with the kernel's NVMe driver (i.e. drivers/nvme/host/). To support all the features of nvme-stas, several changes to the Linux kernel are required. nvme-stas can also operate with older kernels, but with limited functionality. Kernel 5.18 provides all the features needed by nvme-stas. nvme-stas can also work with older kernels that include back-ported changes to the NVMe driver.

