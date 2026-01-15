# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>

'''@brief This file gets automagically configured by meson at build time.'''

import os
import sys
import shutil
import platform
import libnvme
from staslib.version import KernelVersion

LIBNVME_VERSION = libnvme.__version__

VERSION = '@VERSION@'
LICENSE = '@LICENSE@'

STACD_DBUS_NAME = '@STACD_DBUS_NAME@'
STACD_DBUS_PATH = '@STACD_DBUS_PATH@'

STAFD_DBUS_NAME = '@STAFD_DBUS_NAME@'
STAFD_DBUS_PATH = '@STAFD_DBUS_PATH@'

KERNEL_VERSION = KernelVersion(platform.release())
KERNEL_IFACE_MIN_VERSION = KernelVersion('5.14')
KERNEL_TP8013_MIN_VERSION = KernelVersion('5.16')
KERNEL_HOSTKEY_MIN_VERSION = KernelVersion('5.20')
KERNEL_CTRLKEY_MIN_VERSION = KernelVersion('5.20')
KERNEL_ALL_MIN_VERSION = max(
    # Minimum version required to have support for all
    KERNEL_IFACE_MIN_VERSION,
    KERNEL_TP8013_MIN_VERSION,
    KERNEL_HOSTKEY_MIN_VERSION,
    KERNEL_CTRLKEY_MIN_VERSION,
)

WELL_KNOWN_DISC_NQN = 'nqn.2014-08.org.nvmexpress.discovery'

PROG_NAME = os.path.basename(sys.argv[0])

NVME_HOSTID = '@ETC@/nvme/hostid'
NVME_HOSTNQN = '@ETC@/nvme/hostnqn'
NVME_HOSTKEY = '@ETC@/nvme/hostkey'

SYS_CONF_FILE = '@ETC@/stas/sys.conf'
STAFD_CONF_FILE = '@ETC@/stas/stafd.conf'
STACD_CONF_FILE = '@ETC@/stas/stacd.conf'

NBFT_SYSFS_PATH = "/sys/firmware/acpi/tables"
NBFT_SYSFS_FILENAME = "NBFT*"

SYSTEMCTL = shutil.which('systemctl')
