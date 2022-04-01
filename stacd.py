#!/usr/bin/python3
# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
''' STorage Appliance Connector Daemon
'''
import sys
from argparse import ArgumentParser
from staslib import defs

# pylint: disable=consider-using-f-string
DBUS_IDL = '''
<node>
    <interface name="%s.debug">
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

    <interface name="%s">
        <method name="list_controllers">
            <arg direction="in" type="b" name="detailed"/>
            <arg direction="out" type="aa{ss}" name="controller_list"/>
        </method>
    </interface>
</node>
''' % (defs.STACD_DBUS_NAME, defs.STACD_DBUS_NAME)

def parse_args(conf_file:str): # pylint: disable=missing-function-docstring
    parser = ArgumentParser(description=f'{defs.STAC_DESCRIPTION} ({defs.STAC_ACRONYM}). Must be root to run this program.')
    parser.add_argument('-f', '--conf-file', action='store', help='Configuration file (default: %(default)s)', default=conf_file, type=str, metavar='FILE')
    parser.add_argument('-s', '--syslog', action='store_true', help='Send messages to syslog instead of stdout. Use this when running %(prog)s as a daemon. (default: %(default)s)', default=False)
    parser.add_argument('--tron', action='store_true', help='Trace ON. (default: %(default)s)', default=False)
    parser.add_argument('-v', '--version', action='store_true', help='Print version, then exit', default=False)
    parser.add_argument('--idl', action='store', help='Print D-Bus IDL, then exit', type=str, metavar='FILE')
    return parser.parse_args()

ARGS = parse_args(defs.STACD_CONFIG_FILE)

if ARGS.version:
    print(f'{defs.PROJECT_NAME} {defs.VERSION}')
    sys.exit(0)

if ARGS.idl:
    with open(ARGS.idl, 'w') as f: # pylint: disable=unspecified-encoding
        print(f'{DBUS_IDL}', file=f)
    sys.exit(0)


# There is a reason for having this import here and not at the top of the file.
# We want to allow running stafd with the --version and --idl options and exit
# without having to import stas.
from staslib import stas # pylint: disable=wrong-import-position

# Before going any further, make sure the script is allowed to run.
stas.check_if_allowed_to_continue()


################################################################################
# Preliminary checks have passed. Let her rip!
# pylint: disable=wrong-import-position
# pylint: disable=wrong-import-order
import json
import systemd.daemon
import dasbus.error
import dasbus.client.observer
import dasbus.client.proxy
from libnvme import nvme
from gi.repository import GLib

LOG = stas.get_logger(ARGS.syslog, defs.STACD_PROCNAME)
CNF = stas.get_configuration(ARGS.conf_file)
stas.trace_control(ARGS.tron or CNF.tron)

SYS_CNF   = stas.get_sysconf() # Singleton
NVME_ROOT = nvme.root()        # Singleton
NVME_ROOT.log_level("debug" if (ARGS.tron or CNF.tron) else "err")
NVME_HOST = nvme.host(NVME_ROOT, SYS_CNF.hostnqn, SYS_CNF.hostid, SYS_CNF.hostsymname) # Singleton

def set_loglevel(tron): # pylint: disable=missing-function-docstring
    stas.trace_control(tron)
    NVME_ROOT.log_level("debug" if tron else "err")

#*******************************************************************************
class Ioc(stas.Controller):
    ''' @brief This object establishes a connection to one I/O Controller.
    '''
    def __init__(self, tid:stas.TransportId):
        super().__init__(NVME_ROOT, NVME_HOST, tid)

    def _on_udev_remove(self, udev):
        ''' Called when the associated nvme device (/dev/nvmeX) is removed
            from the system.
        '''
        super()._on_udev_remove(udev)

        # Defer removal of this object to the next main loop's idle period.
        GLib.idle_add(STAC.remove_controller, self.tid, udev.sys_name)

    def _find_existing_connection(self):
        return stas.UDEV.find_nvme_ioc_device(self.tid)

#*******************************************************************************
class Stac(stas.Service):
    ''' STorage Appliance Connector (STAC)
    '''

    CONF_STABILITY_SOAK_TIME_SEC = 1.5
    CONF_STABILITY_LONG_SOAK_TIME_SEC = 10  # pylint: disable=invalid-name

    class Dbus:
        ''' This is the DBus interface that external programs can use to
            communicate with stacd.
        '''
        __dbus_xml__ = DBUS_IDL

        @property
        def tron(self):
            ''' @brief Get Trace ON property '''
            return stas.TRON

        @tron.setter
        def tron(self, value): # pylint: disable=no-self-use
            ''' @brief Set Trace ON property '''
            set_loglevel(value)

        @property
        def log_level(self) -> str:
            ''' @brief Get Log Level property '''
            return stas.log_level()

        def process_info(self) -> str:
            ''' @brief Get status info (for debug)
                @return A string representation of a json object.
            '''
            info = {
                'tron': stas.TRON,
                'log-level': self.log_level,
            }
            info.update(STAC.info())
            return json.dumps(info)

        def controller_info(self, transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn) -> str: # pylint: disable=too-many-arguments,no-self-use
            ''' @brief D-Bus method used to return information about a controller
            '''
            controller = STAC.get_controller(transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn)
            return json.dumps(controller.info()) if controller else '{}'

        def list_controllers(self, detailed) -> str: # pylint: disable=no-self-use
            ''' @brief Return the list of I/O controller IDs
            '''
            return [ controller.details() if detailed else controller.controller_id_dict() for controller in STAC.get_controllers() ]


    #===========================================================================
    def __init__(self):
        super().__init__(self._reload_hdlr)

        # We don't want to apply configuration changes to nvme-cli right away.
        # Often, multiple changes will occur in a short amount of time (sub-second).
        # We want to wait until there are no more changes before applying them
        # to the system. The following timer acts as a "soak period". Changes
        # will be applied by calling self._on_config_ctrls() at the end of
        # the soak period.
        self._cfg_soak_tmr = stas.GTimer(Stac.CONF_STABILITY_SOAK_TIME_SEC, self._on_config_ctrls)
        self._cfg_soak_tmr.start()

        # Create the D-Bus instance.
        self._config_dbus(Stac.Dbus(), defs.STACD_DBUS_NAME, defs.STACD_DBUS_PATH)

        # Connect to STAF D-Bus interface
        self._staf = None
        self._staf_watcher = dasbus.client.observer.DBusObserver(self._sysbus, defs.STAFD_DBUS_NAME)
        self._staf_watcher.service_available.connect(self._connect_to_staf)
        self._staf_watcher.service_unavailable.connect(self._disconnect_from_staf)
        self._staf_watcher.connect_once_available()

    def _release_resources(self):
        LOG.debug('Stac._release_resources()')
        self._disconnect_from_staf(self._staf_watcher)
        if self._staf_watcher is not None:
            self._staf_watcher.disconnect()

        super()._release_resources()

        self._staf         = None
        self._staf_watcher = None

    def _reload_hdlr(self):
        ''' @brief Reload configuration file. This is triggered by the SIGHUP
                   signal, which can be sent with "systemctl reload stacd".
        '''
        systemd.daemon.notify('RELOADING=1')
        CNF.reload()
        set_loglevel(CNF.tron)
        self._cfg_soak_tmr.start(Stac.CONF_STABILITY_SOAK_TIME_SEC)
        systemd.daemon.notify('READY=1')
        return GLib.SOURCE_CONTINUE

    def _config_ctrls_finish(self, configured_ctrl_list):
        configured_ctrl_list = [ ctrl_dict for ctrl_dict in configured_ctrl_list if 'traddr' in ctrl_dict and 'subsysnqn' in ctrl_dict ]
        LOG.debug('Stac._config_ctrls_finish()        - configured_ctrl_list = %s', configured_ctrl_list)

        discovered_ctrl_list = list()
        if self._staf:
            for staf_data in json.loads(self._staf.get_all_log_pages(True)):
                host_traddr = staf_data['discovery-controller']['host-traddr']
                host_iface  = staf_data['discovery-controller']['host-iface']
                for dlpe in staf_data['log-pages']:
                    if dlpe.get('subtype') == 'nvme': # eliminate discovery controllers
                        discovered_ctrl_list.append(stas.cid_from_dlpe(dlpe, host_traddr, host_iface))
        LOG.debug('Stac._config_ctrls_finish()        - discovered_ctrl_list = %s', discovered_ctrl_list)

        controllers = stas.remove_blacklisted(configured_ctrl_list + discovered_ctrl_list)
        controllers = stas.remove_invalid_addresses(controllers)

        new_controller_ids = { stas.TransportId(controller) for controller in controllers }
        cur_controller_ids = set(self._controllers.keys())
        controllers_to_add = new_controller_ids - cur_controller_ids
        controllers_to_rm  = cur_controller_ids - new_controller_ids

        LOG.debug('Stac._config_ctrls_finish()        - controllers_to_add = %s', list(controllers_to_add))
        LOG.debug('Stac._config_ctrls_finish()        - controllers_to_rm  = %s', list(controllers_to_rm))

        for tid in controllers_to_rm:
            controller = self._controllers.pop(tid, None)
            if controller is not None:
                controller.kill()

        for tid in controllers_to_add:
            self._controllers[tid] = Ioc(tid)

    def _connect_to_staf(self, _):
        ''' @brief Hook up DBus signal handlers for signals from stafd.
        '''
        try:
            self._staf = self._sysbus.get_proxy(defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)
            self._staf.log_pages_changed.connect(self._log_pages_changed)
            self._cfg_soak_tmr.start()

            # Make sure timer is set back to its normal value.
            self._cfg_soak_tmr.set_timeout(Stac.CONF_STABILITY_SOAK_TIME_SEC)
            LOG.debug('Stac._connect_to_staf()            - Connected to staf')
        except dasbus.error.DBusError:
            LOG.error('Failed to connect to staf')

    def _disconnect_from_staf(self, _):
        if self._staf:
            self._staf.log_pages_changed.disconnect(self._log_pages_changed)
            dasbus.client.proxy.disconnect_proxy(self._staf)
            self._staf = None
        # When we lose connectivity with stafd, the most logical explanation
        # is that stafd restarted. In that case, it may take some time for stafd
        # to re-populate its log pages cache. So let's give stafd plenty of time
        # to update its log pages cache and send log pages change notifications
        # before triggering a stacd re-config. We do this by momentarily
        # increasing the config soak timer to a longer period.
        self._cfg_soak_tmr.set_timeout(Stac.CONF_STABILITY_LONG_SOAK_TIME_SEC)
        LOG.debug('Stac._disconnect_from_staf()       - Disconnected from staf')

    def _log_pages_changed(self, transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn, device): # pylint: disable=too-many-arguments
        LOG.debug('Stac._log_pages_changed()          - transport=%s, traddr=%s, trsvcid=%s, host_traddr=%s, host_iface=%s, subsysnqn=%s, device=%s',
                  transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn, device)
        self._cfg_soak_tmr.start(Stac.CONF_STABILITY_SOAK_TIME_SEC)

#*******************************************************************************
STAC = Stac()
STAC.run()

STAC = None
CNF  = None
LOG  = None
ARGS = None
