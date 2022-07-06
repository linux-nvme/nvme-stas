# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
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

files_to_copy = [
    'avahi.py',
    'conf.py',
    'ctrl.py',
    'glibudev.py',
    'gutil.py',
    'log.py',
    'service.py',
    'singleton.py',
    'stas.py',
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

#===============================================================================
# Make a list of modules to lint
skip = ['__init__.py', 'defs.py', 'glibudev.py']
foreach file: files_to_install
    fname = fs.name('@0@'.format(file))
    if fname not in skip
        modules_to_lint += file
    endif
endforeach

