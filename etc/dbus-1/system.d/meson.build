# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
dbus_conf_dir = join_paths(etcdir, 'dbus-1', 'system.d')

configure_file(
    input: 'org.nvmexpress.staf.in.conf',
    output: 'org.nvmexpress.staf.conf',
    configuration: conf,
    install_dir: dbus_conf_dir,
)

configure_file(
    input: 'org.nvmexpress.stac.in.conf',
    output: 'org.nvmexpress.stac.conf',
    configuration: conf,
    install_dir: dbus_conf_dir,
)
