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

PYTHONPATH = ':'.join(PYTHON_SEARCH_PATHS)

test_env = environment({'MALLOC_PERTURB_': '0'})
test_env.prepend('PYTHONPATH', PYTHONPATH)

# pylint and pyflakes
if modules_to_lint.length() != 0
    pylint = find_program('pylint', required: false)
    pyflakes = find_program('pyflakes3', required: false)
    if not pyflakes.found()
        temp = find_program('pyflakes', required: false)
        if temp.found() and run_command(temp, '--version', check: false).stdout().contains('Python 3')
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


# Unit tests
things_to_test = [
    ['Test Configuration', 'test-config.py',       []],
    ['Test KernelVersion', 'test-version.py',      []],
    ['Test NvmeOptions',   'test-nvme_options.py', ['pyfakefs']],
    ['Test Controller',    'test-controller.py',   ['pyfakefs']],
    ['Test Service',       'test-service.py',      ['pyfakefs']],
    ['Test Udev',          'test-udev.py',         []],
    ['Test GTimer',        'test-gtimer.py',       []],
    ['Test Avahi',         'test-avahi.py',        []],
    ['Test TransportId',   'test-transport_id.py', []],
]

foreach thing: things_to_test
    msg = thing[0]

    # Check whether all dependencies can be found
    deps_found = true
    deps = thing[2]
    foreach dep : deps
        if run_command(python3, '-c', 'import @0@'.format(dep), check: false).returncode() != 0
            deps_found = false
            warning('"@0@" requires python module "@1@"'.format(msg, dep))
            break
        endif
    endforeach

    # Run the test if all dependencies are available
    if deps_found
        script = join_paths(meson.current_source_dir(), thing[1])
        test(msg, python3, args: script, env: test_env)
    endif
endforeach

# Make sure code complies with minimum Python version requirement.
tools = [
    join_paths(meson.current_source_dir(), '../man'),
    join_paths(meson.current_source_dir(), '../utils'),
]
vermin = find_program('vermin', required: false)
if vermin.found()
    if modules_to_lint.length() != 0
        test('vermin code', vermin, args: ['--config-file', join_paths(meson.current_source_dir(), 'vermin.conf')] + modules_to_lint, env: test_env)
    endif
    test('vermin tools', vermin, args: ['--config-file', join_paths(meson.current_source_dir(), 'vermin-tools.conf')] + tools, env: test_env)
endif
