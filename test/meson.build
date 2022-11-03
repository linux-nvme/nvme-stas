# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#

test_env = environment({'MALLOC_PERTURB_': '0'})
test_env.prepend('PYTHONPATH', PYTHONPATH)

subproject('libnvme')

# The libnvme subproject (see above) builds the python bindings conditionally.
# It depends whether the build platform has all the required tools like "swig".
# Therefore, we need to make sure that we can import the libnvme package before
# proceeding with the tests.
if run_command(python3, '-c', 'import libnvme', check: false, env: test_env).returncode() != 0
    warning('Missing runtime package needed to run the tests: python3-libnvme.')
else
    #---------------------------------------------------------------------------
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

    #---------------------------------------------------------------------------
    # Unit tests
    things_to_test = [
        ['Test Avahi',         'test-avahi.py',        []],
        ['Test Configuration', 'test-config.py',       []],
        ['Test Controller',    'test-controller.py',   ['pyfakefs']],
        ['Test GTimer',        'test-gtimer.py',       []],
        ['Test iputil',        'test-iputil.py',       []],
        ['Test KernelVersion', 'test-version.py',      []],
        ['Test log',           'test-log.py',          ['pyfakefs']],
        ['Test NvmeOptions',   'test-nvme_options.py', ['pyfakefs']],
        ['Test Service',       'test-service.py',      ['pyfakefs']],
        ['Test TID',           'test-transport_id.py', []],
        ['Test Udev',          'test-udev.py',         []],
    ]

    foreach thing: things_to_test
        msg = thing[0]

        # Check whether all dependencies can be found
        missing_deps = []
        deps = thing[2]
        foreach dep : deps
            if run_command(python3, '-c', 'import @0@'.format(dep), check: false).returncode() != 0
                missing_deps += [dep]
            endif
        endforeach

        if missing_deps.length() == 0
            # Allow the test to run if all dependencies are available
            script = join_paths(meson.current_source_dir(), thing[1])
            test(msg, python3, args: script, env: test_env)
        else
            warning('"@0@" requires python module "@1@"'.format(msg, missing_deps))
        endif
    endforeach
endif


#-------------------------------------------------------------------------------
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
