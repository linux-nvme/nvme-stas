#!/usr/bin/python3
# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''STorage Appliance Connector Daemon'''

import sys
from argparse import ArgumentParser
from staslib import defs


# ******************************************************************************
def parse_args(conf_file: str):
    '''Parse command line options'''
    parser = ArgumentParser(description='STorage Appliance Connector (STAC). Must be root to run this program.')
    parser.add_argument(
        '-f',
        '--conf-file',
        action='store',
        help='Configuration file (default: %(default)s)',
        default=conf_file,
        type=str,
        metavar='FILE',
    )
    parser.add_argument(
        '-c',
        '--conn-conf-file',
        action='store',
        help='Connectivity configuration file (default: %(default)s)',
        default=defs.NVME_STAS_CONF_FILE,
        type=str,
        metavar='FILE',
    )
    parser.add_argument(
        '-s',
        '--syslog',
        action='store_true',
        help='Send messages to syslog instead of stdout. Use this when running %(prog)s as a daemon. (default: %(default)s)',
        default=False,
    )
    parser.add_argument('--tron', action='store_true', help='Trace ON. (default: %(default)s)', default=False)
    parser.add_argument('-v', '--version', action='store_true', help='Print version, then exit', default=False)
    return parser.parse_args()


ARGS = parse_args(defs.STACD_CONF_FILE)

if ARGS.version:
    print(f'nvme-stas {defs.VERSION}')
    print(f'libnvme {defs.LIBNVME_VERSION}')
    sys.exit(0)


# ******************************************************************************
if __name__ == '__main__':
    import json
    import logging
    from staslib import log, service, stas, udev

    # Before going any further, make sure the script is allowed to run.
    stas.check_if_allowed_to_continue()

    class Dbus:
        '''This is the DBus interface that external programs can use to
        communicate with stacd.
        '''

        __dbus_xml__ = stas.load_idl('stacd.idl')

        @property
        def tron(self):
            '''Return the Trace ON (tron) flag.'''
            return STAC.tron

        @tron.setter
        def tron(self, value):
            '''Set the Trace ON (tron) flag.'''
            STAC.tron = value

        @property
        def log_level(self) -> str:
            '''Return the current log level.'''
            return log.level()

        def process_info(self) -> str:
            '''Return a JSON string with the daemon's runtime status info (used for debug).'''
            info = {
                'tron': STAC.tron,
                'log-level': self.log_level,
            }
            info.update(STAC.info())
            return json.dumps(info)

        def controller_info(self, transport, traddr, trsvcid, subsysnqn, host_traddr, host_iface, hostnqn) -> str:
            '''Return a JSON string with information about the specified controller.'''
            controller = STAC.get_controller(transport, traddr, trsvcid, subsysnqn, host_traddr, host_iface, hostnqn)
            return json.dumps(controller.info()) if controller else '{}'

        def list_controllers(self, detailed) -> list:
            '''Return the list of I/O controller IDs.'''
            return [
                controller.details() if detailed else controller.controller_id_dict()
                for controller in STAC.get_controllers()
            ]

    log.init(ARGS.syslog)
    STAC = service.Stac(ARGS, Dbus())
    STAC.run()

    STAC = None
    ARGS = None

    udev.shutdown()

    logging.shutdown()
