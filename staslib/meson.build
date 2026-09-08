# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#

files_to_configure = [ 'defs.py', '__init__.py' ]
configured_files = []
foreach file : files_to_configure
    configured_files += configure_file(
        input: file,
        output: file,
        configuration: conf
    )
endforeach

# The D-Bus IDLs are also configured, but are kept in variables of their own
# because doc/meson.build generates the D-Bus DocBooks from them.
stafd_idl = configure_file(
    input: 'stafd.idl',
    output: 'stafd.idl',
    configuration: conf
)
stacd_idl = configure_file(
    input: 'stacd.idl',
    output: 'stacd.idl',
    configuration: conf
)
configured_files += [ stafd_idl, stacd_idl ]

files_to_copy = [
    'avahi.py',
    'conf.py',
    'ctrl.py',
    'gutil.py',
    'iputil.py',
    'log.py',
    'nbft.py',
    'service.py',
    'singleton.py',
    'stas.py',
    'timeparse.py',
    'trid.py',
    'udev.py',
    'version.py'
]
copied_files = []
foreach file : files_to_copy
    copied_files += configure_file(
        input: file,
        output: file,
        copy: true,
    )
endforeach

files_to_install = copied_files + configured_files
python3.install_sources(
    files_to_install,
    pure: true,
    subdir: 'staslib',
)

packages_to_lint += meson.current_build_dir()
