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
import platform
from staslib.version import KernelVersion

VERSION         = '@VERSION@'
LICENSE         = '@LICENSE@'

STACD_DBUS_NAME = '@STACD_DBUS_NAME@'
STACD_DBUS_PATH = '@STACD_DBUS_PATH@'

STAFD_DBUS_NAME = '@STAFD_DBUS_NAME@'
STAFD_DBUS_PATH = '@STAFD_DBUS_PATH@'

KERNEL_VERSION = KernelVersion(platform.release())
KERNEL_IFACE_MIN_VERSION  = KernelVersion('@KERNEL_IFACE_MIN_VERSION@')
KERNEL_TP8013_MIN_VERSION = KernelVersion('@KERNEL_TP8013_MIN_VERSION@')

WELL_KNOWN_DISC_NQN = 'nqn.2014-08.org.nvmexpress.discovery'

PROG_NAME = os.path.basename(sys.argv[0])
SYS_CONF_FILE = '/etc/stas/sys.conf'
