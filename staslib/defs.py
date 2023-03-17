# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>

''' @brief This file gets automagically configured by meson at build time.
'''
import os
import sys
import shutil
import platform
from staslib.version import KernelVersion

try:
    import libnvme

    LIBNVME_VERSION = libnvme.__version__
except (AttributeError, ModuleNotFoundError):
    LIBNVME_VERSION = '?.?'

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

WELL_KNOWN_DISC_NQN = 'nqn.2014-08.org.nvmexpress.discovery'

PROG_NAME = os.path.basename(sys.argv[0])

NVME_HOSTID = '/etc/nvme/hostid'
NVME_HOSTNQN = '/etc/nvme/hostnqn'
NVME_HOSTKEY = '/etc/nvme/hostkey'

SYS_CONF_FILE = '/etc/stas/sys.conf'
STAFD_CONF_FILE = '/etc/stas/stafd.conf'
STACD_CONF_FILE = '/etc/stas/stacd.conf'

SYSTEMCTL = shutil.which('systemctl')
