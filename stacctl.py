#!/usr/bin/python3
# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
''' STorage Appliance Connector Control Utility
'''
import sys
import json
import pprint
from argparse import ArgumentParser
import dasbus.error
from dasbus.connection import SystemMessageBus
from staslib import defs


def tron(args):  # pylint: disable=unused-argument
    '''@brief Trace ON'''
    bus = SystemMessageBus()
    iface = bus.get_proxy(defs.STACD_DBUS_NAME, defs.STACD_DBUS_PATH)
    iface.tron = True  # pylint: disable=assigning-non-slot
    print(f'tron = {iface.tron}')  # Read value back from stacd and print


def troff(args):  # pylint: disable=unused-argument
    '''@brief Trace OFF'''
    bus = SystemMessageBus()
    iface = bus.get_proxy(defs.STACD_DBUS_NAME, defs.STACD_DBUS_PATH)
    iface.tron = False  # pylint: disable=assigning-non-slot
    print(f'tron = {iface.tron}')  # Read value back from stacd and print


def _extract_cid(ctrl):  # pylint: disable=missing-function-docstring
    return (
        ctrl['transport'],
        ctrl['traddr'],
        ctrl['trsvcid'],
        ctrl['host-traddr'],
        ctrl['host-iface'],
        ctrl['subsysnqn'],
    )


def status(args):  # pylint: disable=unused-argument
    '''@brief retrieve stacd's status information'''
    bus = SystemMessageBus()
    iface = bus.get_proxy(defs.STACD_DBUS_NAME, defs.STACD_DBUS_PATH)
    info = json.loads(iface.process_info())
    info['controllers'] = iface.list_controllers(True)
    for controller in info['controllers']:
        transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn = _extract_cid(controller)
        controller.update(
            json.loads(iface.controller_info(transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn))
        )

    print(pprint.pformat(info, width=120))


def ls(args):
    '''@brief list the I/O controller's that stacd is
    connected (or trying to connect) to.
    '''
    bus = SystemMessageBus()
    iface = bus.get_proxy(defs.STACD_DBUS_NAME, defs.STACD_DBUS_PATH)
    info = iface.list_controllers(args.detailed)
    print(pprint.pformat(info, width=120))


PARSER = ArgumentParser(description=f'{defs.STAC_DESCRIPTION} ({defs.STAC_ACRONYM})')
PARSER.add_argument('-v', '--version', action='store_true', help='Print version, then exit', default=False)

SUBPARSER = PARSER.add_subparsers(title='Commands')

PRSR = SUBPARSER.add_parser('tron', help='Trace ON')
PRSR.set_defaults(func=tron)

PRSR = SUBPARSER.add_parser('troff', help='Trace OFF')
PRSR.set_defaults(func=troff)

PRSR = SUBPARSER.add_parser('status', help=f'Show runtime status information about {defs.STACD_PROCNAME}')
PRSR.set_defaults(func=status)

PRSR = SUBPARSER.add_parser('ls', help='List I/O controllers')
PRSR.add_argument(
    '-d', '--detailed', action='store_true', help='Print detailed info (default: "%(default)s")', default=False
)
PRSR.set_defaults(func=ls)

ARGS = PARSER.parse_args()
if ARGS.version:
    print(f'{defs.PROJECT_NAME} {defs.VERSION}')
    sys.exit(0)

try:
    ARGS.func(ARGS)
except dasbus.error.DBusError:
    sys.exit(f'Unable to communicate with {defs.STACD_PROCNAME} over D-Bus. Is {defs.STACD_PROCNAME} running?')
except AttributeError:
    PARSER.print_help()
    sys.exit()
