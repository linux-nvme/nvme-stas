#!/usr/bin/python3
# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
''' STorage Appliance Finder Control Utility
'''
import sys
import json
import pprint
from argparse import ArgumentParser
import dasbus.error
from dasbus.connection import SystemMessageBus
from staslib import conf, defs


def tron(args):  # pylint: disable=unused-argument
    '''@brief Trace ON'''
    bus = SystemMessageBus()
    iface = bus.get_proxy(defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)
    iface.tron = True  # pylint: disable=assigning-non-slot
    print(f'tron = {iface.tron}')  # Read value back from stafd and print


def troff(args):  # pylint: disable=unused-argument
    '''@brief Trace OFF'''
    bus = SystemMessageBus()
    iface = bus.get_proxy(defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)
    iface.tron = False  # pylint: disable=assigning-non-slot
    print(f'tron = {iface.tron}')  # Read value back from stafd and print


def _extract_cid(ctrl):
    return (
        ctrl['transport'],
        ctrl['traddr'],
        ctrl['trsvcid'],
        ctrl['subsysnqn'],
        ctrl['host-traddr'],
        ctrl['host-iface'],
        ctrl['host-nqn'],
    )


def status(args):  # pylint: disable=unused-argument
    '''@brief retrieve stafd's status information'''
    bus = SystemMessageBus()
    iface = bus.get_proxy(defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)
    info = json.loads(iface.process_info())
    info['controllers'] = iface.list_controllers(True)
    for controller in info['controllers']:
        transport, traddr, trsvcid, subsysnqn, host_traddr, host_iface, host_nqn = _extract_cid(controller)
        controller['log_pages'] = iface.get_log_pages(
            transport, traddr, trsvcid, subsysnqn, host_traddr, host_iface, host_nqn
        )
        controller.update(
            json.loads(iface.controller_info(transport, traddr, trsvcid, subsysnqn, host_traddr, host_iface, host_nqn))
        )

    print(pprint.pformat(info, width=120))


def ls(args):
    '''@brief list the discovery controller's that stafd is
    connected (or trying to connect) to.
    '''
    bus = SystemMessageBus()
    iface = bus.get_proxy(defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)
    info = iface.list_controllers(args.detailed)
    print(pprint.pformat(info, width=120))


def dlp(args):
    '''@brief retrieve a controller's discovery log pages from stafd'''
    bus = SystemMessageBus()
    iface = bus.get_proxy(defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)
    info = iface.get_log_pages(
        args.transport,
        args.traddr,
        args.trsvcid,
        args.nqn,
        args.host_traddr,
        args.host_iface,
        args.host_nqn,
    )
    print(pprint.pformat(info, width=120))


def adlp(args):
    '''@brief retrieve all of the controller's discovery log pages from stafd'''
    bus = SystemMessageBus()
    iface = bus.get_proxy(defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)
    info = json.loads(iface.get_all_log_pages(args.detailed))
    print(pprint.pformat(info, width=120))


PARSER = ArgumentParser(description='STorage Appliance Finder (STAF)')
PARSER.add_argument('-v', '--version', action='store_true', help='Print version, then exit', default=False)

SUBPARSER = PARSER.add_subparsers(title='Commands')

PRSR = SUBPARSER.add_parser('tron', help='Trace ON')
PRSR.set_defaults(func=tron)

PRSR = SUBPARSER.add_parser('troff', help='Trace OFF')
PRSR.set_defaults(func=troff)

PRSR = SUBPARSER.add_parser('status', help='Show runtime status information about stafd')
PRSR.set_defaults(func=status)

PRSR = SUBPARSER.add_parser('ls', help='List discovery controllers')
PRSR.add_argument(
    '-d',
    '--detailed',
    action='store_true',
    help='Print detailed info (default: "%(default)s")',
    default=False,
)
PRSR.set_defaults(func=ls)

PRSR = SUBPARSER.add_parser('dlp', help='Show discovery log pages')
PRSR.add_argument(
    '-t',
    '--transport',
    metavar='<trtype>',
    action='store',
    help='NVMe-over-Fabrics fabric type (default: "%(default)s")',
    choices=['tcp', 'rdma', 'fc', 'loop'],
    default='tcp',
)
PRSR.add_argument(
    '-a',
    '--traddr',
    metavar='<traddr>',
    action='store',
    help='Discovery Controller\'s network address',
    required=True,
)
PRSR.add_argument(
    '-s',
    '--trsvcid',
    metavar='<trsvcid>',
    action='store',
    help='Transport service id (for IP addressing, e.g. tcp, rdma, this field is the port number)',
    required=True,
)
PRSR.add_argument(
    '-w',
    '--host-traddr',
    metavar='<traddr>',
    action='store',
    help='Network address used on the host to connect to the Controller (default: "%(default)s")',
    default='',
)
PRSR.add_argument(
    '-f',
    '--host-iface',
    metavar='<iface>',
    action='store',
    help='This field specifies the network interface used on the host to connect to the Controller (default: "%(default)s")',
    default='',
)
PRSR.add_argument(
    '-q',
    '--host-nqn',
    metavar='<nqn>',
    action='store',
    help='This field specifies the host NQN (default: "%(default)s")',
    default=conf.SysConf().hostnqn,
)
PRSR.add_argument(
    '-n',
    '--nqn',
    metavar='<nqn>',
    action='store',
    help='This field specifies the discovery controller\'s NQN. When not specified this option defaults to "%(default)s"',
    default=defs.WELL_KNOWN_DISC_NQN,
)
PRSR.set_defaults(func=dlp)

PRSR = SUBPARSER.add_parser('adlp', help='Show all discovery log pages')
PRSR.add_argument(
    '-d',
    '--detailed',
    action='store_true',
    help='Print detailed info (default: "%(default)s")',
    default=False,
)
PRSR.set_defaults(func=adlp)

ARGS = PARSER.parse_args()
if ARGS.version:
    print(f'nvme-stas {defs.VERSION}')
    sys.exit(0)

try:
    ARGS.func(ARGS)
except dasbus.error.DBusError:
    sys.exit('Unable to communicate with stafd over D-Bus. Is stafd running?')
