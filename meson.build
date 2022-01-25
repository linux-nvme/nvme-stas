# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
project(
    'nvme-stas',
    meson_version: '>= 0.52.0',
    version: '1.0',
    license: 'Apache-2.0',
    default_options: [
        'buildtype=release',
        'prefix=/usr',
    ]
)

prefix  = get_option('prefix')
etcdir  = get_option('sysconfdir')
bindir  = join_paths(prefix, get_option('bindir'))
sbindir = join_paths(prefix, get_option('sbindir'))
docdir  = join_paths(prefix, get_option('datadir'), 'doc', 'nvme-stas')

want_man  = get_option('man')
want_html = get_option('html')

# Check that we have all the right Python3 dependencies
py_modules_reqd = ['libnvme', 'dasbus', 'pyudev', 'systemd']
if want_man or want_html
    py_modules_reqd += 'lxml'
endif

python3 = import('python').find_installation('python3', modules: py_modules_reqd)
python_version = python3.language_version()
python_version_req = '>=3.6'
if not python_version.version_compare(python_version_req)
    error('Python @0@ required. Found @1@ instead'.format(python_version_req, python_version))
endif

if run_command(python3, '-c', 'from gi.repository import GObject').returncode() != 0
    error('Required GObject python3 module not found. Usually comes from python3-gi (deb) OR python3-gobject (yum)')
endif

pylint = find_program('pylint', required: false)
pyflakes = find_program('pyflakes3', required: false)
if not pyflakes.found()
    temp = find_program('pyflakes', required: false)
    if temp.found() and run_command(temp, '--version').stdout().contains('Python 3')
        pyflakes = temp
    endif
endif

#===============================================================================
conf = configuration_data()

conf.set('KERNEL_REQD_MIN_VERSION', '5.14')
conf.set('KERNEL_TP8013_MIN_VERSION', '5.16')
conf.set('KERNEL_TP8010_MIN_VERSION', '5.17')

foreach component : [ ['staf', 'STorage Appliance Finder'],
                      ['stac', 'STorage Appliance Connector'] ]
    COMPONENT   = component[0].to_upper()
    daemon_name = component[0] + 'd'
    DAEMON_NAME = daemon_name.to_upper()
    conf.set(DAEMON_NAME + '_CONFIG_FILE', join_paths(etcdir, 'stas', daemon_name + '.conf'))
    conf.set(DAEMON_NAME + '_DBUS_NAME', 'org.nvmexpress.' + component[0])
    conf.set(DAEMON_NAME + '_DBUS_PATH', '/org/nvmexpress/' + component[0])
    conf.set(DAEMON_NAME + '_EXECUTABLE', join_paths(sbindir, daemon_name))
    conf.set(DAEMON_NAME + '_PROCNAME', daemon_name)
    conf.set(COMPONENT + '_ACRONYM', COMPONENT)
    conf.set(COMPONENT + '_DESCRIPTION', component[1])
    conf.set('VERSION', meson.project_version())
    conf.set('LICENSE', meson.project_license()[0])
    conf.set('PROJECT_NAME', meson.project_name())
endforeach

#===============================================================================
stafd = configure_file(
    input: 'stafd.py',
    output: conf.get('STAFD_PROCNAME'),
    install_dir: sbindir,
    copy: true,
)

stafctl = configure_file(
    input: 'stafctl.py',
    output: 'stafctl',
    install_dir: bindir,
    copy: true,
)

stacd = configure_file(
    input: 'stacd.py',
    output: conf.get('STACD_PROCNAME'),
    install_dir: sbindir,
    copy: true,
)

stacctl = configure_file(
    input: 'stacctl.py',
    output: 'stacctl',
    install_dir: bindir,
    copy: true,
)

stasadm = configure_file(
    input: 'stasadm.py',
    output: 'stasadm',
    install_dir: bindir,
    copy: true,
)

#===============================================================================
install_subdir(
    'etc/stas',
    install_dir: etcdir,
)

install_subdir(
    'usr/lib/modules-load.d',
    install_dir: join_paths(prefix, 'lib'),
)

#===============================================================================
test_env = environment({'MALLOC_PERTURB_': '0'})
test_env.prepend('PYTHONPATH', meson.current_build_dir())

rr = run_command([python3, '-c', 'from libnvme import nvme'], env: test_env)
libnvme_found = rr.returncode() == 0

if libnvme_found
    rcfile = join_paths(meson.current_source_dir(), 'test', 'pylint.rc')

    modules_to_test = [
        [ 'stafd',   stafd   ],
        [ 'stafctl', stafctl ],
        [ 'stacd',   stacd   ],
        [ 'stacctl', stacctl ],
        [ 'stasadm', stasadm ],
    ]
    foreach module: modules_to_test
        if pylint.found()
            test('pylint ' + module[0], pylint, args: ['--errors-only', '--rcfile=' + rcfile, module[1]], env: test_env)
        endif
        if pyflakes.found()
            test('pyflakes ' + module[0], pyflakes, args: [module[1]], env: test_env)
        endif
    endforeach
else
    warning('Install the libnvme Python package to run the tests.')
endif

#===============================================================================
substs = configuration_data()
substs.set('NAME',    meson.project_name())
substs.set('VERSION', meson.project_version())
substs.set('LICENSE', meson.project_license()[0])
configure_file(
    input:         'nvme-stas.spec.in',
    output:        'nvme-stas.spec',
    configuration: substs,
)

#===============================================================================
subdir('staslib')
subdir('etc/dbus-1/system.d')
subdir('usr/lib/systemd/system')
subdir('man')

if meson.version().version_compare('>=0.57.0')
    summary = [
        '',
        '------------------------------------------------------------',
    ]
    foreach key : conf.keys()
        summary += (key + ':  ' + conf.get(key))
    endforeach
    summary += [
        '------------------------------------------------------------',
        '',
    ]

    message('\n'.join(summary))
endif
