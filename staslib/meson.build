# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#

files_to_configure = [ 'defs.py' ]
configured_files = []
foreach file : files_to_configure
    configured_files += configure_file(
        input: file,
        output: file,
        configuration: conf
    )
endforeach

files_to_copy = [ '__init__.py', 'avahi.py', 'glibudev.py', 'stas.py', 'version.py' ]
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
    pure: false,
    subdir: 'staslib',
)

#===============================================================================
if libnvme_dep.found()
    fs = import('fs')

    modules_to_skip = ['__init__.py', 'defs.py', 'glibudev.py']
    modules_to_test = []
    foreach file: files_to_install
        fname = fs.name('@0@'.format(file))
        if fname not in modules_to_skip
            modules_to_test += file
        endif
    endforeach

    if pylint.found()
        test('pylint staslib/*.py', pylint, args: ['--rcfile=' + rcfile] + modules_to_test, env: stas_test_env)
    endif
    if pyflakes.found()
        test('pyflakes staslib/*.py', pyflakes, args: modules_to_test, env: stas_test_env)
    endif

    foreach module: modules_to_test
        test('Unit test @0@'.format(module), python3, args: module, env: stas_test_env)
    endforeach
endif
