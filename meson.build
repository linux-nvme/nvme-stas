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
    version: '2.0-rc3',
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
readthedocs = get_option('readthedocs')

if readthedocs
    want_html = true
endif

buildtime_modules = []
if want_man or want_html
    buildtime_modules += ['lxml']
endif

python3 = import('python').find_installation('python3', modules:buildtime_modules)
python_version = python3.language_version()
python_version_req = '>=3.6'
if not python_version.version_compare(python_version_req)
    error('Python @0@ required. Found @1@ instead'.format(python_version_req, python_version))
endif

# Check if the runtime Python modules are present. These are not needed
# to build nvme-stas, but will be needed to run the tests.
missing_modules = false
py_modules_reqd = [
    ['libnvme', 'Install python3-libnvme (deb/rpm)'],
    ['dasbus',  'Install python3-dasbus (deb/rpm) OR pip3 install dasbus'],
    ['pyudev',  'Install python3-pyudev (deb/rpm)'],
    ['systemd', 'Install python3-systemd (deb/rpm)'],
    ['gi',      'Install python3-gi (deb) OR python3-gobject (rpm)'],
]
foreach p : py_modules_reqd
    if run_command(python3, '-c', 'import @0@'.format(p[0]), check: false).returncode() != 0
        warning('Missing runtime module "@0@". @1@'.format(p[0], p[1]))
        missing_modules = true
    endif
endforeach

if missing_modules and get_option('rt_pymods_reqd')
    error('Please install missing runtime modules')
endif


#===============================================================================
conf = configuration_data()

conf.set('PROJECT_NAME', meson.project_name())
conf.set('VERSION', meson.project_version())
conf.set('LICENSE', meson.project_license()[0])
conf.set('KERNEL_IFACE_MIN_VERSION', '5.14')
conf.set('KERNEL_TP8013_MIN_VERSION', '5.16')
conf.set('BUILD_DIR', meson.current_build_dir())
conf.set('SRCE_ROOT', meson.current_source_dir())
conf.set('LIBNVME_VER_FOR_PLEO', '1.2')

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
stacd = configure_file(
    input: 'stacd.py',
    output: conf.get('STACD_PROCNAME'),
    install_dir: sbindir,
    copy: true,
)

stafctl = configure_file(
    input: 'stafctl.py',
    output: 'stafctl',
    install_dir: bindir,
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

#===========================================================================
install_subdir(
    'etc/stas',
    install_dir: etcdir,
)

#===========================================================================
foreach component : [ 'nvme-stas.spec', '.coveragerc', 'coverage.sh', ]
    configure_file(
        input:         component + '.in',
        output:        component,
        configuration: conf,
    )
endforeach

#===========================================================================
# Make a list of modules to lint
modules_to_lint = [stafd, stafctl, stacd, stacctl, stasadm]


# Point Python Path to Current Build Dir.
# This is used by other meson.build files.
PYTHON_SEARCH_PATHS = [
    conf.get('BUILD_DIR'),
    join_paths(conf.get('BUILD_DIR'), 'subprojects', 'libnvme')
]
PYTHONPATH = ':'.join(PYTHON_SEARCH_PATHS)

#===========================================================================
subdir('staslib')
subdir('etc/dbus-1/system.d')
subdir('usr/lib/systemd/system')
subdir('test')
subdir('doc')
subdir('doc/man')

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
