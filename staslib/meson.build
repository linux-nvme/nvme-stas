# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#

defs_py = configure_file(
    input: 'defs.py',
    output: 'defs.py',
    configuration: conf
)

configured_files   = [ defs_py ]
unconfigured_files = [ '__init__.py', 'avahi.py', 'glibudev.py', 'stas.py', 'version.py' ]

python3.install_sources(
    unconfigured_files + configured_files,
    pure: false,
    subdir: 'staslib',
)

# In order to run the tests, we need to be able to load the Python modules from
# the build directory. All the files except "defs.py" can be soft linked in
# the build directory as follows.
ln = find_program('ln')
foreach file : unconfigured_files
    run_command(ln, ['-s', '../../staslib' / file, meson.current_build_dir() / file])
endforeach

#===============================================================================
if libnvme_dep.found()
    modules_to_test = [
        [ 'staslib.avahi',   'avahi.py'   ],
        [ 'staslib.stas',    'stas.py'    ],
        [ 'staslib.version', 'version.py' ],
    ]

    foreach module: modules_to_test
        file = join_paths(meson.current_source_dir(), module[1])
        if pylint.found()
            test('pylint ' + module[0], pylint, args: ['--rcfile=' + rcfile, file], env: test_env)
        endif
        if pyflakes.found()
            test('pyflakes ' + module[0], pyflakes, args: [file], env: test_env)
        endif
    endforeach
endif
