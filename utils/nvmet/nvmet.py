#!/usr/bin/python3
# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>

# PYTHON_ARGCOMPLETE_OK

import os
import sys
import pprint
import pathlib
import subprocess
from argparse import ArgumentParser

VERSION = 1.0
DEFAULT_CONFIG_FILE = './nvmet.conf'


class Fore:
    RED = '\033[31m'
    GREEN = '\033[32m'


class Style:
    RESET_ALL = '\033[0m'


def _runcmd(cmd: list, quiet=False):
    if not quiet:
        print(' '.join(cmd))
    if args.dry_run:
        return
    subprocess.run(cmd)


def _mkdir(dname: str):
    print(f'mkdir -p "{dname}"')
    if args.dry_run:
        return
    pathlib.Path(dname).mkdir(parents=True, exist_ok=True)


def _echo(value, fname: str):
    print(f'echo -n "{value}" > "{fname}"')
    if args.dry_run:
        return
    with open(fname, 'w') as f:
        f.write(str(value))


def _symlink(port: str, subsysnqn: str):
    print(
        f'$( cd "/sys/kernel/config/nvmet/ports/{port}/subsystems" && ln -s "../../../subsystems/{subsysnqn}" "{subsysnqn}" )'
    )
    if args.dry_run:
        return
    target = os.path.join('/sys/kernel/config/nvmet/subsystems', subsysnqn)
    link = pathlib.Path(os.path.join('/sys/kernel/config/nvmet/ports', port, 'subsystems', subsysnqn))
    link.symlink_to(target)


def _create_subsystem(subsysnqn: str) -> str:
    print(f'###{Fore.GREEN} Create subsystem: {subsysnqn}{Style.RESET_ALL}')
    dname = os.path.join('/sys/kernel/config/nvmet/subsystems/', subsysnqn)
    _mkdir(dname)
    _echo(1, os.path.join(dname, 'attr_allow_any_host'))
    return dname


def _create_namespace(subsysnqn: str, id: str, node: str) -> str:
    print(f'###{Fore.GREEN} Add namespace: {id}{Style.RESET_ALL}')
    dname = os.path.join('/sys/kernel/config/nvmet/subsystems/', subsysnqn, 'namespaces', id)
    _mkdir(dname)
    _echo(node, os.path.join(dname, 'device_path'))
    _echo(1, os.path.join(dname, 'enable'))
    return dname


def _args_valid(id, traddr, trsvcid, trtype, adrfam):
    if None in (id, trtype):
        return False

    if trtype != 'loop' and None in (traddr, trsvcid, adrfam):
        return False

    return True


def _create_port(port: str, traddr: str, trsvcid: str, trtype: str, adrfam: str):
    '''@param port: This is a nvmet port and not a tcp port.'''
    print(f'###{Fore.GREEN} Create port: {port} -> {traddr}:{trsvcid}{Style.RESET_ALL}')
    dname = os.path.join('/sys/kernel/config/nvmet/ports', port)
    _mkdir(dname)
    _echo(trtype, os.path.join(dname, 'addr_trtype'))
    if traddr:
        _echo(traddr, os.path.join(dname, 'addr_traddr'))
    if trsvcid:
        _echo(trsvcid, os.path.join(dname, 'addr_trsvcid'))
    if adrfam:
        _echo(adrfam, os.path.join(dname, 'addr_adrfam'))


def _map_subsystems_to_ports(subsystems: list):
    print(f'###{Fore.GREEN} Map subsystems to ports{Style.RESET_ALL}')
    for subsystem in subsystems:
        subsysnqn, port = subsystem.get('subsysnqn'), str(subsystem.get('port'))
        if None not in (subsysnqn, port):
            _symlink(port, subsysnqn)


def _read_config(fname: str) -> dict:
    try:
        with open(fname) as f:
            return eval(f.read())
    except Exception as e:
        sys.exit(f'Error reading config file. {e}')


def _read_attr_from_file(fname: str) -> str:
    try:
        with open(fname, 'r') as f:
            return f.read().strip('\n')
    except Exception as e:
        sys.exit(f'Error reading attribute. {e}')


################################################################################


def create(args):
    # Need to be root to run this script
    if not args.dry_run and os.geteuid() != 0:
        sys.exit(f'Permission denied. You need root privileges to run {os.path.basename(__file__)}.')

    config = _read_config(args.conf_file)

    print('')

    # Create a dummy null block device (if one doesn't already exist)
    dev_node = '/dev/nullb0'
    _runcmd(['/usr/sbin/modprobe', 'null_blk', 'nr_devices=1'])

    ports = config.get('ports')
    if ports is None:
        sys.exit(f'Config file "{args.conf_file}" missing a "ports" section')

    subsystems = config.get('subsystems')
    if subsystems is None:
        sys.exit(f'Config file "{args.conf_file}" missing a "subsystems" section')

    # Extract the list of transport types found in the
    # config file and load the corresponding kernel module.
    _runcmd(['/usr/sbin/modprobe', 'nvmet'])
    trtypes = {port.get('trtype') for port in ports if port.get('trtype') is not None}
    for trtype in trtypes:
        if trtype in ('tcp', 'fc', 'rdma'):
            _runcmd(['/usr/sbin/modprobe', f'nvmet-{trtype}'])
        elif trtype == 'loop':
            _runcmd(['/usr/sbin/modprobe', f'nvme-loop'])

    for port in ports:
        print('')
        id, traddr, trsvcid, trtype, adrfam = (
            str(port.get('id')),
            port.get('traddr'),
            port.get('trsvcid'),
            port.get('trtype'),
            port.get('adrfam'),
        )
        if _args_valid(id, traddr, trsvcid, trtype, adrfam):
            _create_port(id, traddr, trsvcid, trtype, adrfam)
        else:
            print(
                f'{Fore.RED}### Config file "{args.conf_file}" error in "ports" section: id={id}, traddr={traddr}, trsvcid={trsvcid}, trtype={trtype}, adrfam={adrfam}{Style.RESET_ALL}'
            )

    for subsystem in subsystems:
        print('')
        subsysnqn, port, namespaces = (
            subsystem.get('subsysnqn'),
            str(subsystem.get('port')),
            subsystem.get('namespaces'),
        )
        if None not in (subsysnqn, port, namespaces):
            _create_subsystem(subsysnqn)
            for id in namespaces:
                _create_namespace(subsysnqn, str(id), dev_node)
        else:
            print(
                f'{Fore.RED}### Config file "{args.conf_file}" error in "subsystems" section: subsysnqn={subsysnqn}, port={port}, namespaces={namespaces}{Style.RESET_ALL}'
            )

    print('')
    _map_subsystems_to_ports(subsystems)

    print('')


def clean(args):
    # Need to be root to run this script
    if not args.dry_run and os.geteuid() != 0:
        sys.exit(f'Permission denied. You need root privileges to run {os.path.basename(__file__)}.')

    print('rm -f /sys/kernel/config/nvmet/ports/*/subsystems/*')
    for dname in pathlib.Path('/sys/kernel/config/nvmet/ports').glob('*/subsystems/*'):
        _runcmd(['rm', '-f', str(dname)], quiet=True)

    print('rmdir /sys/kernel/config/nvmet/ports/*')
    for dname in pathlib.Path('/sys/kernel/config/nvmet/ports').glob('*'):
        _runcmd(['rmdir', str(dname)], quiet=True)

    print('rmdir /sys/kernel/config/nvmet/subsystems/*/namespaces/*')
    for dname in pathlib.Path('/sys/kernel/config/nvmet/subsystems').glob('*/namespaces/*'):
        _runcmd(['rmdir', str(dname)], quiet=True)

    print('rmdir /sys/kernel/config/nvmet/subsystems/*')
    for dname in pathlib.Path('/sys/kernel/config/nvmet/subsystems').glob('*'):
        _runcmd(['rmdir', str(dname)], quiet=True)

    _runcmd(['/usr/sbin/modprobe', '--remove', 'nvmet-tcp'])
    _runcmd(['/usr/sbin/modprobe', '--remove', 'nvmet-rdma'])
    _runcmd(['/usr/sbin/modprobe', '--remove', 'nvmet-fc'])
    _runcmd(['/usr/sbin/modprobe', '--remove', 'null_blk'])


def link(args):
    port = str(args.port)
    subsysnqn = str(args.subnqn)
    if not args.dry_run:
        if os.geteuid() != 0:
            # Need to be root to run this script
            sys.exit(f'Permission denied. You need root privileges to run {os.path.basename(__file__)}.')

        symlink = os.path.join('/sys/kernel/config/nvmet/ports', port, 'subsystems', subsysnqn)
        if os.path.exists(symlink):
            sys.exit(f'Symlink already exists: {symlink}')

    _symlink(port, subsysnqn)


def unlink(args):
    port = str(args.port)
    subsysnqn = str(args.subnqn)
    symlink = os.path.join('/sys/kernel/config/nvmet/ports', port, 'subsystems', subsysnqn)
    if not args.dry_run:
        if os.geteuid() != 0:
            # Need to be root to run this script
            sys.exit(f'Permission denied. You need root privileges to run {os.path.basename(__file__)}.')

        if not os.path.exists(symlink):
            sys.exit(f'No such symlink: {symlink}')

    _runcmd(['rm', symlink])


def ls(args):
    ports = list()
    for port_path in pathlib.Path('/sys/kernel/config/nvmet/ports').glob('*'):
        id = port_path.parts[-1]
        port = {
            'id': int(id),
            'traddr': _read_attr_from_file(os.path.join('/sys/kernel/config/nvmet/ports', id, 'addr_traddr')),
            'trsvcid': _read_attr_from_file(os.path.join('/sys/kernel/config/nvmet/ports', id, 'addr_trsvcid')),
            'adrfam': _read_attr_from_file(os.path.join('/sys/kernel/config/nvmet/ports', id, 'addr_adrfam')),
            'trtype': _read_attr_from_file(os.path.join('/sys/kernel/config/nvmet/ports', id, 'addr_trtype')),
        }

        ports.append(port)

    subsystems = dict()
    for subsystem_path in pathlib.Path('/sys/kernel/config/nvmet/subsystems').glob('*'):
        subsysnqn = subsystem_path.parts[-1]
        namespaces_path = pathlib.Path(os.path.join('/sys/kernel/config/nvmet/subsystems', subsysnqn, 'namespaces'))
        subsystems[subsysnqn] = {
            'port': None,
            'subsysnqn': subsysnqn,
            'namespaces': sorted([int(namespace_path.parts[-1]) for namespace_path in namespaces_path.glob('*')]),
        }

    # Find the port that each subsystem is mapped to
    for subsystem_path in pathlib.Path('/sys/kernel/config/nvmet/ports').glob('*/subsystems/*'):
        subsysnqn = subsystem_path.parts[-1]
        if subsysnqn in subsystems:
            subsystems[subsysnqn]['port'] = int(subsystem_path.parts[-3])

    output = {
        'ports': ports,
        'subsystems': list(subsystems.values()),
    }

    if sys.version_info < (3, 8):
        print(pprint.pformat(output, width=70))
    else:
        print(pprint.pformat(output, width=70, sort_dicts=False))

    print('')


################################################################################

parser = ArgumentParser(description="Create NVMe-oF Storage Subsystems")
parser.add_argument('-v', '--version', action='store_true', help='Print version, then exit', default=False)

subparser = parser.add_subparsers(title='Commands', description='valid commands')

prsr = subparser.add_parser('create', help='Create nvme targets')
prsr.add_argument(
    '-f',
    '--conf-file',
    action='store',
    help='Configuration file (default: %(default)s)',
    default=DEFAULT_CONFIG_FILE,
    type=str,
    metavar='FILE',
)
prsr.add_argument(
    '-d', '--dry-run', action='store_true', help='Just print what would be done. (default: %(default)s)', default=False
)
prsr.set_defaults(func=create)

prsr = subparser.add_parser('clean', help='Remove all previously created nvme targets')
prsr.add_argument(
    '-d', '--dry-run', action='store_true', help='Just print what would be done. (default: %(default)s)', default=False
)
prsr.set_defaults(func=clean)

prsr = subparser.add_parser('ls', help='List ports and subsystems')
prsr.set_defaults(func=ls)

prsr = subparser.add_parser('link', help='Map a subsystem to a port')
prsr.add_argument(
    '-d', '--dry-run', action='store_true', help='Just print what would be done. (default: %(default)s)', default=False
)
prsr.add_argument('-p', '--port', action='store', type=int, help='nvmet port', required=True)
prsr.add_argument('-s', '--subnqn', action='store', type=str, help='nvmet subsystem NQN', required=True, metavar='NQN')
prsr.set_defaults(func=link)

prsr = subparser.add_parser('unlink', help='Unmap a subsystem from a port')
prsr.add_argument(
    '-d', '--dry-run', action='store_true', help='Just print what would be done. (default: %(default)s)', default=False
)
prsr.add_argument('-p', '--port', action='store', type=int, help='nvmet port', required=True)
prsr.add_argument('-s', '--subnqn', action='store', type=str, help='nvmet subsystem NQN', required=True, metavar='NQN')
prsr.set_defaults(func=unlink)


# =============================
# Tab-completion.
# MUST BE CALLED BEFORE parser.parse_args() BELOW.
# Ref: https://kislyuk.github.io/argcomplete/
#
# If you do have argcomplete installed, you also need to run
# "sudo activate-global-python-argcomplete3" to globally activate
# auto-completion. Ref: https://pypi.python.org/pypi/argcomplete#global-completion
try:
    import argcomplete

    argcomplete.autocomplete(parser)
except ModuleNotFoundError:
    # auto-complete is not necessary for the operation of this script. Just nice to have
    pass

args = parser.parse_args()

if args.version:
    print(f'{os.path.basename(__file__)}  {VERSION}')
    sys.exit(0)

# Invoke the sub-command
args.func(args)
