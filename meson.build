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
    meson_version: '>= 0.53.0',
    version: '1.1.7',
    license: 'Apache-2.0',
    default_options: [
        'buildtype=release',
        'prefix=/usr',
    ]
)

fs = import('fs')

#===============================================================================
prefix  = get_option('prefix')
etcdir  = get_option('sysconfdir')
datadir = get_option('datadir')
bindir  = join_paths(prefix, get_option('bindir'))
sbindir = join_paths(prefix, get_option('sbindir'))
docdir  = join_paths(prefix, datadir, 'doc', 'nvme-stas')
cnfdir  = join_paths(etcdir, 'stas')

want_man  = get_option('man')
want_html = get_option('html')

# Check for libnvme availability
libnvme_dep = dependency('libnvme', fallback : ['libnvme', 'libnvme_dep'])

# Check that we have all the right Python3 dependencies
python3 = import('python').find_installation('python3')
python_version = python3.language_version()
python_version_req = '>=3.6'
if not python_version.version_compare(python_version_req)
    error('Python @0@ required. Found @1@ instead'.format(python_version_req, python_version))
endif

check_pymodules = get_option('check_pymodules')
if check_pymodules
    py_modules_reqd = [
        ['dasbus',    'Install python3-dasbus (rpm) OR pip3 install dasbus'],
        ['pyudev',    'Install python3-pyudev (deb/rpm)'],
        ['systemd',   'Install python3-systemd (deb/rpm)'],
        ['gi',        'Install python3-gi (deb) OR python3-gobject (rpm)'],
    ]
    if want_man or want_html
        py_modules_reqd += [['lxml', 'Install python3-lxml (deb/rpm)']]
    endif
    foreach p : py_modules_reqd
        if run_command(python3, '-c', 'import @0@'.format(p[0]), check: false).returncode() != 0
            error('Required python3 module "@0@" not found. @1@'.format(p[0], p[1]))
        endif
    endforeach
endif

#===============================================================================
conf = configuration_data()

conf.set('PROJECT_NAME', meson.project_name())
conf.set('VERSION', meson.project_version())
conf.set('LICENSE', meson.project_license()[0])
conf.set('KERNEL_IFACE_MIN_VERSION', '5.14')
conf.set('KERNEL_TP8013_MIN_VERSION', '5.16')
conf.set('BUILD_DIR', meson.current_build_dir())

foreach component : [ ['staf', 'STorage Appliance Finder'],
                      ['stac', 'STorage Appliance Connector'] ]
    COMPONENT   = component[0].to_upper()
    daemon_name = component[0] + 'd'
    ctl_name    = component[0] + 'ctl'
    DAEMON_NAME = daemon_name.to_upper()
    conf.set(DAEMON_NAME + '_CONFIG_FILE', join_paths(cnfdir, daemon_name + '.conf'))
    conf.set(DAEMON_NAME + '_DBUS_NAME', 'org.nvmexpress.' + component[0])
    conf.set(DAEMON_NAME + '_DBUS_PATH', '/org/nvmexpress/' + component[0])
    conf.set(DAEMON_NAME + '_EXECUTABLE', join_paths(sbindir, daemon_name))
    conf.set(DAEMON_NAME + '_CTL', join_paths(bindir, ctl_name))
    conf.set(DAEMON_NAME + '_PROCNAME', daemon_name)
    conf.set(DAEMON_NAME + '_CTLNAME', ctl_name)
    conf.set(COMPONENT + '_ACRONYM', COMPONENT)
    conf.set(COMPONENT + '_DESCRIPTION', component[1])
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

#===============================================================================
# Make a list of modules to lint
if libnvme_dep.found()
    modules_to_lint = [stafd, stafctl, stacd, stacctl, stasadm]
else
    warning('Install the libnvme Python package to run the tests.')
    modules_to_lint = []
endif

#===============================================================================
foreach component : [ 'nvme-stas.spec', '.coveragerc', 'coverage.sh', ]
    configure_file(
        input:         component + '.in',
        output:        component,
        configuration: conf,
    )
endforeach

#===============================================================================
subdir('staslib')
subdir('etc/dbus-1/system.d')
subdir('usr/lib/systemd/system')
subdir('doc/man')
subdir('test')

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
        'prefix:              ' + prefix,
        'etcdir:              ' + etcdir,
        'datadir:             ' + datadir,
        'bindir:              ' + bindir,
        'sbindir:             ' + sbindir,
        'docdir:              ' + docdir,
        'cnfdir:              ' + cnfdir,
        'want_man:            ' + want_man.to_string(),
        'want_html:           ' + want_html.to_string(),
        'dbus_conf_dir:       ' + dbus_conf_dir,
        'sd_service_file_dir: ' + sd_service_file_dir,
        '------------------------------------------------------------',
        '',
    ]

    message('\n'.join(summary))
endif
