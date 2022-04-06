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

python3.install_sources(
    copied_files + configured_files,
    pure: false,
    subdir: 'staslib',
)

#===============================================================================
if libnvme_dep.found()
    modules_to_lint = [
        [ 'staslib.avahi',   'avahi.py'   ],
        [ 'staslib.stas',    'stas.py'    ],
        [ 'staslib.version', 'version.py' ],
    ]

    foreach module: modules_to_lint
        file = join_paths(meson.current_source_dir(), module[1])
        if pylint.found()
            test('pylint ' + module[0], pylint, args: ['--rcfile=' + rcfile, file], env: stas_test_env)
        endif
        if pyflakes.found()
            test('pyflakes ' + module[0], pyflakes, args: [file], env: stas_test_env)
        endif
    endforeach


    modules_to_test = [
        [ 'staslib.stas',    'stas.py'    ],
        [ 'staslib.version', 'version.py' ],
    ]

    foreach module: modules_to_test
        file = join_paths(meson.current_source_dir(), module[1])
        test('Unit test ' + module[0], python3, args: [file, ], env: stas_test_env)
    endforeach
endif
