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
    meson_version: '>= 0.62.0',
    version: '3.0',
    license: 'Apache-2.0',
    default_options: [
        'buildtype=release',
        'prefix=/usr',
        'sysconfdir=/etc',
    ]
)

# Minimum version of the libnvme python bindings required
python3_libnvme_version = '>=3.0'

fs = import('fs')

#===============================================================================
prefix  = get_option('prefix')
datadir = prefix / get_option('datadir')
etcdir  = prefix / get_option('sysconfdir')
bindir  = prefix / get_option('bindir')
sbindir = prefix / get_option('sbindir')
mandir  = prefix / get_option('mandir')
docdir  = datadir / 'doc' / 'nvme-stas'
cnfdir  = etcdir / 'stas'

want_man  = get_option('man')
want_html = get_option('html')
want_readthedocs = get_option('readthedocs')

buildtime_modules = []
if want_man or want_html or want_readthedocs
    buildtime_modules += ['lxml']
endif

pymod = import('python')
python3 = pymod.find_installation('python3', modules:buildtime_modules, required:false)
if not python3.found()
    python3 = pymod.find_installation('python', modules:buildtime_modules)
endif
python_version = python3.language_version()
python_version_req = '>=3.6'
if not python_version.version_compare(python_version_req)
    error('Python @0@ required. Found @1@ instead'.format(python_version_req, python_version))
endif

# Check if the runtime Python modules are present. These are not needed
# to build nvme-stas, but will be needed to run the tests.
missing_runtime_mods = false
py_modules_reqd = [
    ['libnvme', 'Install python3-libnvme (deb/rpm)'],
    ['dasbus',  'Install python3-dasbus (deb/rpm) OR pip install dasbus'],
    ['pyudev',  'Install python3-pyudev (deb/rpm)'],
    ['systemd', 'Install python3-systemd (deb/rpm)'],
    ['gi',      'Install python3-gi (deb) OR python3-gobject (rpm)'],
]
foreach p : py_modules_reqd
    if run_command(python3, '-c', 'import @0@'.format(p[0]), check: false).returncode() != 0
        warning('Missing runtime module "@0@". @1@'.format(p[0], p[1]))
        missing_runtime_mods = true
    endif
endforeach

if missing_runtime_mods and get_option('rt_pymods_reqd')
    error('Please install missing runtime modules')
endif


#===============================================================================
conf = configuration_data()

conf.set('VERSION', meson.project_version())
conf.set('LICENSE', meson.project_license()[0])
conf.set('BUILD_DIR', meson.current_build_dir())
conf.set('STAFD_DBUS_NAME', 'org.nvmexpress.staf')
conf.set('STAFD_DBUS_PATH', '/org/nvmexpress/staf')
conf.set('STACD_DBUS_NAME', 'org.nvmexpress.stac')
conf.set('STACD_DBUS_PATH', '/org/nvmexpress/stac')
conf.set('ETC', etcdir)

#===========================================================================
# Let's try to locate the libnvme python bindings. We'll need libnvme to run
# the tests. We have two choices:
#
# 1) Use a pre-installed version of libnvme (i.e. from /usr/lib/...)
# 2) Build libnvme as a meson subproject
#
# The decision to use one method over the other is controlled by the option
# "libnvme-sel=['subproject', 'pre-installed']". The default is to use the
# subproject. Note that if a pre-intalled libnvme is selected but one cannot
# be found, then the subproject is used as a fallback.
libnvme_location = '?'
if get_option('libnvme-sel') == 'pre-installed'
    # Check if a pre-installed libnvme can be found
    rr = run_command(python3, '-c', 'import libnvme; print(f"{libnvme.__version__}")', check: false)
    if rr.returncode() == 0
        libnvme_version = rr.stdout().strip()
        if libnvme_version.version_compare(python3_libnvme_version)
            rr = run_command(python3, '-c', 'import libnvme; print(f"{libnvme.__path__[0]}")', check: false)
            if rr.returncode() == 0
                libnvme_location = rr.stdout().strip()
            endif
        else
            warning('libnvme version is @0@ but [@1@] required. Will try nvme-cli subproject...'.format(libnvme_version, python3_libnvme_version))
        endif
    endif
endif

if libnvme_location == '?'
    # fallback to subproject
    nvme_cli_subproject = subproject(
        'nvme-cli',
        default_options: [
            'buildtype=release',
            'prefix=/usr',
            'sysconfdir=/etc',
            'nvme=disabled',
            'python=enabled',
        ],
        required: false,
        version: python3_libnvme_version,
    )
    if nvme_cli_subproject.found()
        python3_libnvme_dep = nvme_cli_subproject.get_variable('python3_libnvme_dep')
        libnvme_location = fs.parent(fs.parent(python3_libnvme_dep.get_variable('nvme_py_path')))
    endif
endif

PYTHONPATH = conf.get('BUILD_DIR')
if libnvme_location != '?'
    PYTHONPATH = ':'.join([libnvme_location, PYTHONPATH])
endif
conf.set('PYTHONPATH', PYTHONPATH)

#===============================================================================
stafd = configure_file(
    input: 'stafd.py',
    output: 'stafd',
    install_dir: sbindir,
    copy: true,
)
stacd = configure_file(
    input: 'stacd.py',
    output: 'stacd',
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
packages_to_lint = []

#===========================================================================
subdir('staslib')
subdir('etc/dbus-1/system.d')
subdir('usr/lib/systemd/system')
subdir('test')
subdir('doc')


#===========================================================================
summary_dict = {
    'prefix ':              prefix,
    'etcdir ':              etcdir,
    'cnfdir ':              cnfdir,
    'bindir ':              bindir,
    'sbindir ':             sbindir,
    'datadir ':             datadir,
    'mandir ':              mandir,
    'docdir ':              docdir,
    'dbus_conf_dir ':       dbus_conf_dir,
    'sd_unit_dir ':         sd_unit_dir,
    'build location ':      meson.current_build_dir(),
    'libnvme location ':    libnvme_location,
}
summary(summary_dict, section: 'Directories')

summary_dict = {
    'want_man ':            want_man,
    'want_html ':           want_html,
    'want_readthedocs ':    want_readthedocs,
}

foreach key : conf.keys()
    if key not in ['BUILD_DIR', 'VERSION', 'LICENSE']
        summary_dict += { key + ' ': conf.get(key) }
    endif
endforeach

summary(summary_dict, section: 'Configuration', bool_yn: true)
