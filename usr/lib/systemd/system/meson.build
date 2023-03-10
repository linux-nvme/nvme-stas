# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
sd_unit_dir = prefix / 'lib' / 'systemd' / 'system'

configure_file(
    input: 'stafd.in.service',
    output: 'stafd.service',
    install_dir: sd_unit_dir,
    configuration: conf,
)

configure_file(
    input: 'stacd.in.service',
    output: 'stacd.service',
    install_dir: sd_unit_dir,
    configuration: conf,
)

configure_file(
    input: 'stas-config@.service',
    output: 'stas-config@.service',
    install_dir: sd_unit_dir,
    copy: true,
)

configure_file(
    input: 'stas-config.target',
    output: 'stas-config.target',
    install_dir: sd_unit_dir,
    copy: true,
)
