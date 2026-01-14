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
    from staslib import log, service, stas, udev  # pylint: disable=ungrouped-imports

    # Before going any further, make sure the script is allowed to run.
    stas.check_if_allowed_to_continue()

    class Dbus:
        '''This is the DBus interface that external programs can use to
        communicate with stacd.
        '''

        __dbus_xml__ = stas.load_idl('stacd.idl')

        @property
        def tron(self):
            '''@brief Get Trace ON property'''
            return STAC.tron

        @tron.setter
        def tron(self, value):
            '''@brief Set Trace ON property'''
            STAC.tron = value

        @property
        def log_level(self) -> str:
            '''@brief Get Log Level property'''
            return log.level()

        def process_info(self) -> str:
            '''@brief Get status info (for debug)
            @return A string representation of a json object.
            '''
            info = {
                'tron': STAC.tron,
                'log-level': self.log_level,
            }
            info.update(STAC.info())
            return json.dumps(info)

        def controller_info(  # pylint: disable=too-many-arguments
            self, transport, traddr, trsvcid, subsysnqn, host_traddr, host_iface, host_nqn
        ) -> str:
            '''@brief D-Bus method used to return information about a controller'''
            controller = STAC.get_controller(transport, traddr, trsvcid, subsysnqn, host_traddr, host_iface, host_nqn)
            return json.dumps(controller.info()) if controller else '{}'

        def list_controllers(self, detailed) -> list:
            '''@brief Return the list of I/O controller IDs'''
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
