# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
if meson.version().version_compare('>=0.56.0')
    TEST_DIR_ROOT = meson.project_build_root()
else
    TEST_DIR_ROOT = fs.parent(meson.current_build_dir())
endif

PYTHON_SEARCH_PATHS = [
    TEST_DIR_ROOT,
    join_paths(TEST_DIR_ROOT, 'subprojects', 'libnvme')
]

test_env = environment({'MALLOC_PERTURB_': '0'})
test_env.prepend('PYTHONPATH', ':'.join(PYTHON_SEARCH_PATHS))

if modules_to_lint.length() != 0
    pylint = find_program('pylint', required: false)
    pyflakes = find_program('pyflakes3', required: false)
    if not pyflakes.found()
        temp = find_program('pyflakes', required: false)
        if temp.found() and run_command(temp, '--version').stdout().contains('Python 3')
            pyflakes = temp
        endif
    endif

    rcfile = join_paths(meson.current_source_dir(), 'pylint.rc')

    if pylint.found()
        test('pylint', pylint, args: ['--rcfile=' + rcfile] + modules_to_lint, env: test_env)
    endif
    if pyflakes.found()
        test('pyflakes', pyflakes, args: modules_to_lint, env: test_env)
    endif
endif

foreach module: modules_to_test
    fname = fs.name('@0@'.format(module))
    test('Unit test ' + fname, python3, args: module, env: test_env)
endforeach
