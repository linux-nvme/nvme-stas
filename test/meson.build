# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#

srce_dir = meson.current_source_dir()
test_env = environment({'MALLOC_PERTURB_': '0'})
test_env.append('PYTHONMALLOC', 'malloc')
test_list = modules_to_lint + packages_to_lint

libnvme_location = '?'

# We require libnvme in order to run the tests. We have two choices, either
# run the tests using a pre-installed version of libnvme (i.e. from /usr) or
# build libnvme as a meson subproject and run the tests using that version
# of libnvme. The decision to use one method over the other is controlled
# by the option "libnvme-sel". Note that if a pre-intalled libnvme is selected
# but one cannot be found, then we fall back to using the subproject libnvme.
if get_option('libnvme-sel') == 'pre-installed'
    # Check if a pre-installed libnvme can be found
    rr = run_command(python3, '-c', 'import libnvme; print(f"{libnvme.__path__[0]}")', check: false, env: test_env)
    if rr.returncode() == 0
        libnvme_location = rr.stdout().strip()
        libnvme_path = fs.parent(libnvme_location)
        PYTHONPATH = ':'.join([libnvme_path, PYTHONPATH])
        test_env.prepend('PYTHONPATH', PYTHONPATH)
    endif
endif

if libnvme_location == '?'
    # Second, if libnvme is not already installed or "libnvme-sel" is not
    # set to "pre-installed", let's fallback to using the subproject.
    libnvme_dep = dependency('python3-libnvme', fallback: ['libnvme', 'libnvme_dep'], required: false)

    test_env.prepend('PYTHONPATH', PYTHONPATH) # This sets the path to look in the build directory
    rr = run_command(python3, '-c', 'import libnvme; print(f"{libnvme.__path__[0]}")', check: false, env: test_env)
    if rr.returncode() == 0
        libnvme_location = rr.stdout().strip()
    endif
endif

if libnvme_location == '?'
    warning('Missing runtime package needed to run the tests: python3-libnvme.')
else
    #---------------------------------------------------------------------------
    # pylint and pyflakes
    if test_list.length() != 0
        pylint = find_program('pylint', required: false)
        pyflakes = find_program('pyflakes3', required: false)
        if not pyflakes.found()
            temp = find_program('pyflakes', required: false)
            if temp.found() and run_command(temp, '--version', check: false).stdout().contains('Python 3')
                pyflakes = temp
            endif
        endif

        rcfile = srce_dir / 'pylint.rc'

        if pylint.found()
            test('pylint', pylint, args: ['--rcfile=' + rcfile] + test_list, env: test_env)
        else
            warning('Skiping some of the tests because "pylint" is missing.')
        endif
        if pyflakes.found()
            test('pyflakes', pyflakes, args: test_list, env: test_env)
        else
            warning('Skiping some of the tests because "pyflakes" is missing.')
        endif
    endif

    #---------------------------------------------------------------------------
    # Check dependencies
    dbus_is_active = false
    avahi_is_active = false
    systemctl = find_program('systemctl', required: false)
    if systemctl.found()
        rr = run_command(systemctl, 'is-active', 'dbus.service', check: false)
        dbus_is_active = rr.returncode() == 0 and rr.stdout().strip() == 'active'
        if not dbus_is_active
            warning('Dbus daemon is not running')
        endif

        rr = run_command(systemctl, 'is-active', 'avahi-daemon.service', check: false)
        avahi_is_active = rr.returncode() == 0 and rr.stdout().strip() == 'active'
        if not avahi_is_active
            warning('Avahi daemon is not running')
        endif
    endif

    want_avahi_test = dbus_is_active and avahi_is_active

    #---------------------------------------------------------------------------
    # Unit tests
    things_to_test = [
        ['Test Configuration', [],           [srce_dir / 'test-config.py',       ]],
        ['Test Controller',    ['pyfakefs'], [srce_dir / 'test-controller.py',   ]],
        ['Test GTimer',        [],           [srce_dir / 'test-gtimer.py',       ]],
        ['Test iputil',        [],           [srce_dir / 'test-iputil.py',       ]],
        ['Test KernelVersion', [],           [srce_dir / 'test-version.py',      ]],
        ['Test log',           ['pyfakefs'], [srce_dir / 'test-log.py',          ]],
        ['Test NBFT',          [],           [srce_dir / 'test-nbft.py',         ]],
        ['Test NbftConf',      [],           [srce_dir / 'test-nbft_conf.py',    ]],
        ['Test NvmeOptions',   ['pyfakefs'], [srce_dir / 'test-nvme_options.py', ]],
        ['Test Service',       ['pyfakefs'], [srce_dir / 'test-service.py',      ]],
        ['Test TID',           [],           [srce_dir / 'test-transport_id.py', ]],
        ['Test defs.py',       [],           [srce_dir / 'test-defs.py',         ]],
        ['Test gutil.py',      [],           [srce_dir / 'test-gutil.py',        ]],
        ['Test Udev',          [],           [srce_dir / 'test-udev.py',         ]],
        ['Test timeparse',     [],           [srce_dir / 'test-timeparse.py',    ]],
    ]

    # The Avahi test requires the Avahi and the Dbus daemons to be running.
    if want_avahi_test
        things_to_test += [['Test Avahi', [], [srce_dir / 'test-avahi.py']]]
    else
        warning('Skip Avahi Test due to missing dependencies')
    endif

    foreach thing: things_to_test
        msg = thing[0]
        deps = thing[1]
        args = thing[2]

        # Check whether all dependencies can be found
        missing_deps = []
        foreach dep : deps
            rr = run_command(python3, '-c', 'import @0@'.format(dep), check: false)
            if rr.returncode() != 0
                missing_deps += [dep]
            endif
        endforeach

        if missing_deps.length() == 0
            # Allow the test to run if all dependencies are available
            test(msg, python3, args: args, env: test_env)
        else
            warning('"@0@" requires python module "@1@"'.format(msg, missing_deps))
        endif
    endforeach
endif


#-------------------------------------------------------------------------------
# Make sure code complies with minimum Python version requirement.
tools = [
    srce_dir / '../doc',
    srce_dir / '../utils',
]
vermin = find_program('vermin', required: false)
if vermin.found()
    if test_list.length() != 0
        test('vermin code', vermin, args: ['--config-file', srce_dir / 'vermin.conf'] + test_list, env: test_env)
    endif
    test('vermin tools', vermin, args: ['--config-file', srce_dir / 'vermin-tools.conf'] + tools, env: test_env)
else
    warning('Skiping some of the tests because "vermin" is missing.')
endif
