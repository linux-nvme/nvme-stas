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
import libnvme
from pkg_resources import parse_version
from staslib.version import KernelVersion

VERSION           = '@VERSION@'
LICENSE           = '@LICENSE@'
PROJECT_NAME      = '@PROJECT_NAME@'

STAC_DESCRIPTION  = '@STAC_DESCRIPTION@'
STAC_ACRONYM      = '@STAC_ACRONYM@'
STACD_PROCNAME    = '@STACD_PROCNAME@'
STACD_DBUS_NAME   = '@STACD_DBUS_NAME@'
STACD_DBUS_PATH   = '@STACD_DBUS_PATH@'
STACD_EXECUTABLE  = '@STACD_EXECUTABLE@'
STACD_CONFIG_FILE = '@STACD_CONFIG_FILE@'


STAF_DESCRIPTION  = '@STAF_DESCRIPTION@'
STAF_ACRONYM      = '@STAF_ACRONYM@'
STAFD_PROCNAME    = '@STAFD_PROCNAME@'
STAFD_DBUS_NAME   = '@STAFD_DBUS_NAME@'
STAFD_DBUS_PATH   = '@STAFD_DBUS_PATH@'
STAFD_EXECUTABLE  = '@STAFD_EXECUTABLE@'
STAFD_CONFIG_FILE = '@STAFD_CONFIG_FILE@'

KERNEL_VERSION = KernelVersion(platform.release())
KERNEL_IFACE_MIN_VERSION  = KernelVersion('@KERNEL_IFACE_MIN_VERSION@')
KERNEL_TP8013_MIN_VERSION = KernelVersion('@KERNEL_TP8013_MIN_VERSION@')

LIBNVME_VERSION = parse_version(libnvme.__version__)
LIBNVME_VERSION_PLEO_SUPPORT = parse_version('@LIBNVME_VER_FOR_PLEO@')
PLEO_SUPPORTED = LIBNVME_VERSION >= LIBNVME_VERSION_PLEO_SUPPORT

WELL_KNOWN_DISC_NQN = 'nqn.2014-08.org.nvmexpress.discovery'

PROG_NAME = os.path.basename(sys.argv[0])
SYS_CONF_FILE = '/etc/stas/sys.conf'
