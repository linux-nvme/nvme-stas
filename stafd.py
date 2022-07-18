#!/usr/bin/python3
# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
''' STorage Appliance Finder Daemon
'''
import sys
from argparse import ArgumentParser
from staslib import defs

DBUS_IDL = f'''
<node>
    <interface name="{defs.STAFD_DBUS_NAME}.debug">
        <property name="tron" type="b" access="readwrite"/>
        <property name="log_level" type="s" access="read"/>
        <method name="process_info">
            <arg direction="out" type="s" name="info_json"/>
        </method>
        <method name="controller_info">
            <arg direction="in" type="s" name="transport"/>
            <arg direction="in" type="s" name="traddr"/>
            <arg direction="in" type="s" name="trsvcid"/>
            <arg direction="in" type="s" name="host_traddr"/>
            <arg direction="in" type="s" name="host_iface"/>
            <arg direction="in" type="s" name="subsysnqn"/>
            <arg direction="out" type="s" name="info_json"/>
        </method>
    </interface>

    <interface name="{defs.STAFD_DBUS_NAME}">
        <method name="list_controllers">
            <arg direction="in" type="b" name="detailed"/>
            <arg direction="out" type="aa{{ss}}" name="controller_list"/>
        </method>
        <method name="get_log_pages">
            <arg direction="in" type="s" name="transport"/>
            <arg direction="in" type="s" name="traddr"/>
            <arg direction="in" type="s" name="trsvcid"/>
            <arg direction="in" type="s" name="host_traddr"/>
            <arg direction="in" type="s" name="host_iface"/>
            <arg direction="in" type="s" name="subsysnqn"/>
            <arg direction="out" type="aa{{ss}}" name="log_pages"/>
        </method>
        <method name="get_all_log_pages">
            <arg direction="in" type="b" name="detailed"/>
            <arg direction="out" type="s" name="log_pages_json"/>
        </method>
        <signal name="log_pages_changed">
          <arg direction="out" type="s" name="transport"/>
          <arg direction="out" type="s" name="traddr"/>
          <arg direction="out" type="s" name="trsvcid"/>
          <arg direction="out" type="s" name="host_traddr"/>
          <arg direction="out" type="s" name="host_iface"/>
          <arg direction="out" type="s" name="subsysnqn"/>
          <arg direction="out" type="s" name="device"/>
        </signal>
    </interface>
</node>
'''


# ******************************************************************************
def parse_args(conf_file: str):  # pylint: disable=missing-function-docstring
    parser = ArgumentParser(
        description=f'{defs.STAF_DESCRIPTION} ({defs.STAF_ACRONYM}). Must be root to run this program.'
    )
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
    parser.add_argument('--idl', action='store', help='Print D-Bus IDL, then exit', type=str, metavar='FILE')
    return parser.parse_args()


ARGS = parse_args(defs.STAFD_CONFIG_FILE)

if ARGS.version:
    print(f'{defs.PROJECT_NAME} {defs.VERSION}')
    try:
        import libnvme

        print(f'libnvme {libnvme.__version__}')
    except (AttributeError, ModuleNotFoundError):
        pass
    sys.exit(0)

if ARGS.idl:
    with open(ARGS.idl, 'w') as f:  # pylint: disable=unspecified-encoding
        print(f'{DBUS_IDL}', file=f)
    sys.exit(0)


# ******************************************************************************
if __name__ == '__main__':
    import json
    import logging
    import dasbus.server.interface
    from staslib import log, service, stas, udev  # pylint: disable=ungrouped-imports

    # Before going any further, make sure the script is allowed to run.
    stas.check_if_allowed_to_continue()

    class Dbus:
        '''This is the DBus interface that external programs can use to
        communicate with stafd.
        '''

        __dbus_xml__ = DBUS_IDL

        @dasbus.server.interface.dbus_signal
        def log_pages_changed(  # pylint: disable=too-many-arguments
            self,
            transport: str,
            traddr: str,
            trsvcid: str,
            host_traddr: str,
            host_iface: str,
            subsysnqn: str,
            device: str,
        ):
            '''@brief Signal sent when log pages have changed.'''

        @property
        def tron(self):
            '''@brief Get Trace ON property'''
            return STAF.tron

        @tron.setter
        def tron(self, value):  # pylint: disable=no-self-use
            '''@brief Set Trace ON property'''
            STAF.tron = value

        @property
        def log_level(self) -> str:
            '''@brief Get Log Level property'''
            return log.level()

        def process_info(self) -> str:
            '''@brief Get status info (for debug)
            @return A string representation of a json object.
            '''
            info = {
                'tron': STAF.tron,
                'log-level': self.log_level,
            }
            info.update(STAF.info())
            return json.dumps(info)

        def controller_info(  # pylint: disable=no-self-use,too-many-arguments
            self, transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn
        ) -> str:
            '''@brief D-Bus method used to return information about a controller'''
            controller = STAF.get_controller(transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn)
            return json.dumps(controller.info()) if controller else '{}'

        def get_log_pages(  # pylint: disable=no-self-use,too-many-arguments
            self, transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn
        ) -> list:
            '''@brief D-Bus method used to retrieve the discovery log pages from one controller'''
            controller = STAF.get_controller(transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn)
            return controller.log_pages() if controller else list()

        def get_all_log_pages(self, detailed) -> str:  # pylint: disable=no-self-use
            '''@brief D-Bus method used to retrieve the discovery log pages from all controllers'''
            log_pages = list()
            for controller in STAF.get_controllers():
                log_pages.append(
                    {
                        'discovery-controller': controller.details() if detailed else controller.controller_id_dict(),
                        'log-pages': controller.log_pages(),
                    }
                )
            return json.dumps(log_pages)

        def list_controllers(self, detailed) -> list:  # pylint: disable=no-self-use
            '''@brief Return the list of discovery controller IDs'''
            return [
                controller.details() if detailed else controller.controller_id_dict()
                for controller in STAF.get_controllers()
            ]

    log.init(ARGS.syslog)
    STAF = service.Staf(ARGS, Dbus())
    STAF.run()

    STAF = None
    ARGS = None

    udev.shutdown()

    logging.shutdown()
