# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#

pandoc = find_program('pandoc', required: true)

components = [
    'conf.py',
    'Makefile',
    'make.bat',
    'index.rst',
    'environment.txt',
    'installation.rst',
    'nvme-stas.rst',
    conf.get('STACD_DBUS_NAME') + '.debug.rst',
    conf.get('STACD_DBUS_NAME') + '.rst',
    conf.get('STAFD_DBUS_NAME') + '.debug.rst',
    conf.get('STAFD_DBUS_NAME') + '.rst',
    'stacctl.rst',
    'stacd-index.rst',
    'stacd.conf.rst',
    'stacd.rst',
    'stacd.service.rst',
    'stafctl.rst',
    'stafd-index.rst',
    'stafd.conf.rst',
    'stafd.rst',
    'stafd.service.rst',
    'stas-config.target.rst',
    'stas-config@.service.rst',
    'stasadm.rst',
    'sys.conf.rst',
]
foreach component : components
    configure_file(
        input:         component,
        output:        component,
        configuration: conf,
    )
endforeach

foreach tuple: html_files
    stem = tuple[0]
    html_file = tuple[1]
    rst = '_' + stem + '.rst'
    custom_target(
        rst,
        input: html_file,
        output: rst,
        build_by_default: true,
        command: [
            pandoc,
            '-f', 'html',
            '-t', 'rst',
            '-o', '@OUTPUT@',
            '@INPUT@'
        ]
    )
endforeach
