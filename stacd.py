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
''' % (
    defs.STACD_DBUS_NAME,
    defs.STACD_DBUS_NAME,
)


def parse_args(conf_file: str):  # pylint: disable=missing-function-docstring
    parser = ArgumentParser(
        description=f'{defs.STAC_DESCRIPTION} ({defs.STAC_ACRONYM}). Must be root to run this program.'
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


ARGS = parse_args(defs.STACD_CONFIG_FILE)

if ARGS.version:
    print(f'{defs.PROJECT_NAME} {defs.VERSION}')
    sys.exit(0)

if ARGS.idl:
    with open(ARGS.idl, 'w') as f:  # pylint: disable=unspecified-encoding
        print(f'{DBUS_IDL}', file=f)
    sys.exit(0)


# There is a reason for having this import here and not at the top of the file.
# We want to allow running stafd with the --version and --idl options and exit
# without having to import stas.
from staslib import stas  # pylint: disable=wrong-import-position

# Before going any further, make sure the script is allowed to run.
stas.check_if_allowed_to_continue()


################################################################################
# Preliminary checks have passed. Let her rip!
# pylint: disable=wrong-import-position
# pylint: disable=wrong-import-order
import json
import pathlib
import logging
import systemd.daemon
import dasbus.error
import dasbus.client.observer
import dasbus.client.proxy
from libnvme import nvme
from gi.repository import GLib

stas.LOG.addHandler(stas.get_log_handler(ARGS.syslog, defs.STACD_PROCNAME))
stas.LOG.setLevel(logging.INFO if ARGS.syslog else logging.DEBUG)
stas.CNF.conf_file = ARGS.conf_file
stas.trace_control(ARGS.tron or stas.CNF.tron)

NVME_ROOT = nvme.root()  # Singleton
NVME_ROOT.log_level("debug" if (ARGS.tron or stas.CNF.tron) else "err")
NVME_HOST = nvme.host(NVME_ROOT, stas.SYS_CNF.hostnqn, stas.SYS_CNF.hostid, stas.SYS_CNF.hostsymname)  # Singleton

UDEV_RULE_SUPPRESS = pathlib.Path('/run/udev/rules.d', '70-nvmf-autoconnect.rules')


def udev_rule_ctrl(enable):
    '''@brief We add an empty udev rule to /run/udev/rules.d to suppress
    nvme-cli's udev rule that is used to tell udevd to automatically
    connect to I/O controller. This is to avoid race conditions between
    stacd and udevd. This is configurable. See "udev-rule" in stacd.conf
    for details.
    '''
    if enable:
        try:
            UDEV_RULE_SUPPRESS.unlink()
        except FileNotFoundError:
            pass
    else:
        if not UDEV_RULE_SUPPRESS.exists():
            pathlib.Path('/run/udev/rules.d').mkdir(parents=True, exist_ok=True)
            UDEV_RULE_SUPPRESS.symlink_to('/dev/null')


def set_loglevel(tron):  # pylint: disable=missing-function-docstring
    stas.trace_control(tron)
    NVME_ROOT.log_level("debug" if tron else "err")


# ******************************************************************************
class Ioc(stas.Controller):
    '''@brief This object establishes a connection to one I/O Controller.'''

    def __init__(self, tid: stas.TransportId):
        super().__init__(NVME_ROOT, NVME_HOST, tid)

    def _on_udev_remove(self, udev):
        '''Called when the associated nvme device (/dev/nvmeX) is removed
        from the system.
        '''
        super()._on_udev_remove(udev)

        # Defer removal of this object to the next main loop's idle period.
        GLib.idle_add(STAC.remove_controller, self.tid, udev.sys_name)

    def _find_existing_connection(self):
        return stas.UDEV.find_nvme_ioc_device(self.tid)


# ******************************************************************************
class Stac(stas.Service):
    '''STorage Appliance Connector (STAC)'''

    CONF_STABILITY_SOAK_TIME_SEC = 1.5
    CONF_STABILITY_LONG_SOAK_TIME_SEC = 10  # pylint: disable=invalid-name

    class Dbus:
        '''This is the DBus interface that external programs can use to
        communicate with stacd.
        '''

        __dbus_xml__ = DBUS_IDL

        @property
        def tron(self):
            '''@brief Get Trace ON property'''
            return stas.TRON

        @tron.setter
        def tron(self, value):  # pylint: disable=no-self-use
            '''@brief Set Trace ON property'''
            set_loglevel(value)

        @property
        def log_level(self) -> str:
            '''@brief Get Log Level property'''
            return stas.log_level()

        def process_info(self) -> str:
            '''@brief Get status info (for debug)
            @return A string representation of a json object.
            '''
            info = {
                'tron': stas.TRON,
                'log-level': self.log_level,
            }
            info.update(STAC.info())
            return json.dumps(info)

        def controller_info(  # pylint: disable=too-many-arguments,no-self-use
            self, transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn
        ) -> str:
            '''@brief D-Bus method used to return information about a controller'''
            controller = STAC.get_controller(transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn)
            return json.dumps(controller.info()) if controller else '{}'

        def list_controllers(self, detailed) -> str:  # pylint: disable=no-self-use
            '''@brief Return the list of I/O controller IDs'''
            return [
                controller.details() if detailed else controller.controller_id_dict()
                for controller in STAC.get_controllers()
            ]

    # ==========================================================================
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

        self._config_connections_audit()

        # Create the D-Bus instance.
        self._config_dbus(Stac.Dbus(), defs.STACD_DBUS_NAME, defs.STACD_DBUS_PATH)

        # Connect to STAF D-Bus interface
        self._staf = None
        self._staf_watcher = dasbus.client.observer.DBusObserver(self._sysbus, defs.STAFD_DBUS_NAME)
        self._staf_watcher.service_available.connect(self._connect_to_staf)
        self._staf_watcher.service_unavailable.connect(self._disconnect_from_staf)
        self._staf_watcher.connect_once_available()

        # Suppress udev rule to auto-connect when AEN is received.
        udev_rule_ctrl(stas.CNF.udev_rule_enabled)

    def _release_resources(self):
        stas.LOG.debug('Stac._release_resources()')

        udev_rule_ctrl(True)

        stas.UDEV.unregister_for_action_events('add')

        self._destroy_staf_comlink(self._staf_watcher)
        if self._staf_watcher is not None:
            self._staf_watcher.disconnect()

        super()._release_resources()

        self._staf = None
        self._staf_watcher = None

    def _audit_connections(self, tids):
        '''A host should only connect to I/O controllers that have been zoned
        for that host or a manual "controller" entry exists in stcd.conf.
        A host should disconnect from an I/O controller when that I/O controller
        is removed from the zone or a manual "controller" entry is removed from
        stacd.conf. stacd will audit connections if "sticky-connections=disabled".
        stacd will delete any connection that is not supposed to exist.
        '''
        stas.LOG.debug('Stac._audit_connections()          - tids = %s', tids)
        num_controllers = len(self._controllers)
        for tid in tids:
            if tid not in self._controllers:
                self._controllers[tid] = Ioc(tid)

        if num_controllers != len(self._controllers):
            self._cfg_soak_tmr.start(Stac.CONF_STABILITY_SOAK_TIME_SEC)

    def _on_add_event(self, udev):
        '''@brief This function is called when a "add" event is received from
        the kernel for an NVMe device. This is used to trigger an audit and make
        sure that the connection to an I/O controller is allowed.
        '''
        if stas.UDEV.is_ioc_device(udev):
            stas.LOG.info('%s - Received "add" event', udev.sys_name)
            tid = stas.UDEV.get_tid(udev)
            stas.LOG.debug('Stac._on_add_event()               - tid=%s', tid)
            self._audit_connections([tid])

    def _config_connections_audit(self):
        '''This function checks the "sticky_connections" parameter to determine
        whether audits should be performed. Audits are enabled when
        "sticky_connections" is disabled.
        '''
        if not stas.CNF.sticky_connections:
            if stas.UDEV.get_registered_action_cback('add') is None:
                stas.UDEV.register_for_action_events('add', self._on_add_event)
                self._audit_connections(stas.UDEV.get_nvme_ioc_tids())
        else:
            stas.UDEV.unregister_for_action_events('add')

    def _keep_connections_on_exit(self):
        '''@brief Determine whether connections should remain when the
        process exits.
        '''
        return True

    def _reload_hdlr(self):
        '''@brief Reload configuration file. This is triggered by the SIGHUP
        signal, which can be sent with "systemctl reload stacd".
        '''
        systemd.daemon.notify('RELOADING=1')
        stas.CNF.reload()
        set_loglevel(stas.CNF.tron)
        self._config_connections_audit()
        self._cfg_soak_tmr.start(Stac.CONF_STABILITY_SOAK_TIME_SEC)
        udev_rule_ctrl(stas.CNF.udev_rule_enabled)
        systemd.daemon.notify('READY=1')
        return GLib.SOURCE_CONTINUE

    def _config_ctrls_finish(self, configured_ctrl_list):
        configured_ctrl_list = [
            ctrl_dict for ctrl_dict in configured_ctrl_list if 'traddr' in ctrl_dict and 'subsysnqn' in ctrl_dict
        ]
        stas.LOG.debug('Stac._config_ctrls_finish()        - configured_ctrl_list = %s', configured_ctrl_list)

        discovered_ctrl_list = list()
        if self._staf:
            for staf_data in json.loads(self._staf.get_all_log_pages(True)):
                host_traddr = staf_data['discovery-controller']['host-traddr']
                host_iface = staf_data['discovery-controller']['host-iface']
                for dlpe in staf_data['log-pages']:
                    if dlpe.get('subtype') == 'nvme':  # eliminate discovery controllers
                        discovered_ctrl_list.append(stas.cid_from_dlpe(dlpe, host_traddr, host_iface))
        stas.LOG.debug('Stac._config_ctrls_finish()        - discovered_ctrl_list = %s', discovered_ctrl_list)

        controllers = stas.remove_blacklisted(configured_ctrl_list + discovered_ctrl_list)
        controllers = stas.remove_invalid_addresses(controllers)

        new_controller_ids = {stas.TransportId(controller) for controller in controllers}
        cur_controller_ids = set(self._controllers.keys())
        controllers_to_add = new_controller_ids - cur_controller_ids
        controllers_to_del = cur_controller_ids - new_controller_ids

        stas.LOG.debug('Stac._config_ctrls_finish()        - controllers_to_add = %s', list(controllers_to_add))
        stas.LOG.debug('Stac._config_ctrls_finish()        - controllers_to_del = %s', list(controllers_to_del))

        for tid in controllers_to_del:
            controller = self._controllers.pop(tid, None)
            if controller is not None:
                controller.disconnect(self._on_ctrl_disconnected, stas.CNF.sticky_connections)

        for tid in controllers_to_add:
            self._controllers[tid] = Ioc(tid)

    def _connect_to_staf(self, _):
        '''@brief Hook up DBus signal handlers for signals from stafd.'''
        try:
            self._staf = self._sysbus.get_proxy(defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)
            self._staf.log_pages_changed.connect(self._log_pages_changed)
            self._cfg_soak_tmr.start()

            # Make sure timer is set back to its normal value.
            self._cfg_soak_tmr.set_timeout(Stac.CONF_STABILITY_SOAK_TIME_SEC)
            stas.LOG.debug('Stac._connect_to_staf()            - Connected to staf')
        except dasbus.error.DBusError:
            stas.LOG.error('Failed to connect to staf')

    def _destroy_staf_comlink(self, watcher):  # pylint: disable=unused-argument
        if self._staf:
            self._staf.log_pages_changed.disconnect(self._log_pages_changed)
            dasbus.client.proxy.disconnect_proxy(self._staf)
            self._staf = None

    def _disconnect_from_staf(self, watcher):
        self._destroy_staf_comlink(watcher)

        # When we lose connectivity with stafd, the most logical explanation
        # is that stafd restarted. In that case, it may take some time for stafd
        # to re-populate its log pages cache. So let's give stafd plenty of time
        # to update its log pages cache and send log pages change notifications
        # before triggering a stacd re-config. We do this by momentarily
        # increasing the config soak timer to a longer period.
        if self._cfg_soak_tmr:
            self._cfg_soak_tmr.set_timeout(Stac.CONF_STABILITY_LONG_SOAK_TIME_SEC)

        stas.LOG.debug('Stac._disconnect_from_staf()       - Disconnected from staf')

    def _log_pages_changed(  # pylint: disable=too-many-arguments
        self, transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn, device
    ):
        stas.LOG.debug(
            'Stac._log_pages_changed()          - transport=%s, traddr=%s, trsvcid=%s, host_traddr=%s, host_iface=%s, subsysnqn=%s, device=%s',
            transport,
            traddr,
            trsvcid,
            host_traddr,
            host_iface,
            subsysnqn,
            device,
        )
        self._cfg_soak_tmr.start(Stac.CONF_STABILITY_SOAK_TIME_SEC)

    def _load_last_known_config(self):
        pass

    def _dump_last_known_config(self, controllers):
        pass


# ******************************************************************************
if __name__ == '__main__':
    STAC = Stac()
    STAC.run()

    STAC = None
    ARGS = None
    stas.clean()
    logging.shutdown()
