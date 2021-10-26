# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
sd_service_file_dir = join_paths(prefix, 'lib', 'systemd', 'system')

configure_file(
    input: 'stafd.in.service',
    output: 'stafd.service',
    configuration: conf,
    install_dir: sd_service_file_dir,
)

configure_file(
    input: 'stacd.in.service',
    output: 'stacd.service',
    configuration: conf,
    install_dir: sd_service_file_dir,
)
