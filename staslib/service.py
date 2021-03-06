# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''This module defines the base Service object from
which the Staf and the Stac objects are derived.'''

import json
import pickle
import logging
import pathlib
import systemd.daemon
import dasbus.error
import dasbus.client.observer
import dasbus.client.proxy

from gi.repository import GLib
from libnvme import nvme
from staslib import avahi, conf, ctrl, defs, gutil, stas, trid, udev


# ******************************************************************************
class Service(stas.ServiceABC):
    '''@brief Base class used to manage a STorage Appliance Service'''

    def __init__(self, args, reload_hdlr):
        sysconf = conf.SysConf()
        self._root = nvme.root()
        self._host = nvme.host(self._root, sysconf.hostnqn, sysconf.hostid, sysconf.hostsymname)

        super().__init__(args, reload_hdlr)

        self._root.log_level("debug" if self._tron else "err")

    def _release_resources(self):
        logging.debug('Service._release_resources()')
        super()._release_resources()

        self._host = None
        self._root = None

    @stas.ServiceABC.tron.setter
    def tron(self, value):
        '''@brief Set Trace ON property'''
        super(__class__, self.__class__).tron.__set__(self, value)
        self._root.log_level("debug" if self._tron else "err")


# ******************************************************************************
def udev_rule_ctrl(enable):
    '''@brief We add an empty udev rule to /run/udev/rules.d to suppress
    nvme-cli's udev rule that is used to tell udevd to automatically
    connect to I/O controller. This is to avoid race conditions between
    stacd and udevd. This is configurable. See "udev-rule" in stacd.conf
    for details.
    '''
    udev_rule_suppress = pathlib.Path('/run/udev/rules.d', '70-nvmf-autoconnect.rules')
    if enable:
        try:
            udev_rule_suppress.unlink()
        except FileNotFoundError:
            pass
    else:
        if not udev_rule_suppress.exists():
            pathlib.Path('/run/udev/rules.d').mkdir(parents=True, exist_ok=True)
            udev_rule_suppress.symlink_to('/dev/null')


# ******************************************************************************
class Stac(Service):
    '''STorage Appliance Connector (STAC)'''

    CONF_STABILITY_LONG_SOAK_TIME_SEC = 10  # pylint: disable=invalid-name
    ADD_EVENT_SOAK_TIME_SEC = 1

    def __init__(self, args, dbus):
        super().__init__(args, self._reload_hdlr)

        self._udev = udev.UDEV

        self._add_event_soak_tmr = gutil.GTimer(self.ADD_EVENT_SOAK_TIME_SEC, self._on_add_event_soaked)

        self._config_connections_audit()

        # Create the D-Bus instance.
        self._config_dbus(dbus, defs.STACD_DBUS_NAME, defs.STACD_DBUS_PATH)

        # Connect to STAF D-Bus interface
        self._staf = None
        self._staf_watcher = dasbus.client.observer.DBusObserver(self._sysbus, defs.STAFD_DBUS_NAME)
        self._staf_watcher.service_available.connect(self._connect_to_staf)
        self._staf_watcher.service_unavailable.connect(self._disconnect_from_staf)
        self._staf_watcher.connect_once_available()

        # Suppress udev rule to auto-connect when AEN is received.
        udev_rule_ctrl(conf.SvcConf().udev_rule_enabled)

    def _release_resources(self):
        logging.debug('Stac._release_resources()')

        if self._add_event_soak_tmr:
            self._add_event_soak_tmr.kill()

        udev_rule_ctrl(True)

        if self._udev:
            self._udev.unregister_for_action_events('add')

        self._destroy_staf_comlink(self._staf_watcher)
        if self._staf_watcher is not None:
            self._staf_watcher.disconnect()

        super()._release_resources()

        self._udev = None
        self._staf = None
        self._staf_watcher = None
        self._add_event_soak_tmr = None

    def _audit_connections(self, tids):
        '''A host should only connect to I/O controllers that have been zoned
        for that host or a manual "controller" entry exists in stcd.conf.
        A host should disconnect from an I/O controller when that I/O controller
        is removed from the zone or a manual "controller" entry is removed from
        stacd.conf. stacd will audit connections if "sticky-connections=disabled".
        stacd will delete any connection that is not supposed to exist.
        '''
        logging.debug('Stac._audit_connections()          - tids = %s', tids)
        num_controllers = len(self._controllers)
        for tid in tids:
            if tid not in self._controllers:
                self._controllers[tid] = ctrl.Ioc(self, self._root, self._host, tid)

        if num_controllers != len(self._controllers):
            self._cfg_soak_tmr.start(self.CONF_STABILITY_SOAK_TIME_SEC)

    def _on_add_event(self, udev_obj):  # pylint: disable=unused-argument
        '''@brief This function is called when a "add" event is received from
        the kernel for an NVMe device. This is used to trigger an audit and make
        sure that the connection to an I/O controller is allowed.

        WARNING: There is a race condition with the "add" event from the kernel.
        The kernel sends the "add" event a bit early and the sysfs attributes
        associated with the nvme object are not always fully initialized.
        To workaround this problem we use a soaking timer to give time for the
        sysfs attributes to stabilize.
        '''
        self._add_event_soak_tmr.start()

    def _on_add_event_soaked(self):
        '''@brief After the add event has been soaking for ADD_EVENT_SOAK_TIME_SEC
        seconds, we can audit the connections.
        '''
        if not conf.SvcConf().sticky_connections:
            self._audit_connections(self._udev.get_nvme_ioc_tids())
        return GLib.SOURCE_REMOVE

    def _config_connections_audit(self):
        '''This function checks the "sticky_connections" parameter to determine
        whether audits should be performed. Audits are enabled when
        "sticky_connections" is disabled.
        '''
        if not conf.SvcConf().sticky_connections:
            if self._udev.get_registered_action_cback('add') is None:
                self._udev.register_for_action_events('add', self._on_add_event)
                self._audit_connections(self._udev.get_nvme_ioc_tids())
        else:
            self._udev.unregister_for_action_events('add')

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
        service_cnf = conf.SvcConf()
        service_cnf.reload()
        self.tron = service_cnf.tron
        self._config_connections_audit()
        self._cfg_soak_tmr.start(self.CONF_STABILITY_SOAK_TIME_SEC)
        udev_rule_ctrl(service_cnf.udev_rule_enabled)
        systemd.daemon.notify('READY=1')
        return GLib.SOURCE_CONTINUE

    def _get_log_pages_from_stafd(self):
        if self._staf:
            try:
                return json.loads(self._staf.get_all_log_pages(True))
            except dasbus.error.DBusError:
                pass

        return list()

    def _config_ctrls_finish(self, configured_ctrl_list):
        configured_ctrl_list = [
            ctrl_dict for ctrl_dict in configured_ctrl_list if 'traddr' in ctrl_dict and 'subsysnqn' in ctrl_dict
        ]
        logging.debug('Stac._config_ctrls_finish()        - configured_ctrl_list = %s', configured_ctrl_list)

        discovered_ctrl_list = list()
        for staf_data in self._get_log_pages_from_stafd():
            host_traddr = staf_data['discovery-controller']['host-traddr']
            host_iface = staf_data['discovery-controller']['host-iface']
            for dlpe in staf_data['log-pages']:
                if dlpe.get('subtype') == 'nvme':  # eliminate discovery controllers
                    discovered_ctrl_list.append(stas.cid_from_dlpe(dlpe, host_traddr, host_iface))

        logging.debug('Stac._config_ctrls_finish()        - discovered_ctrl_list = %s', discovered_ctrl_list)

        controllers = stas.remove_blacklisted(configured_ctrl_list + discovered_ctrl_list)
        controllers = stas.remove_invalid_addresses(controllers)

        new_controller_ids = {trid.TID(controller) for controller in controllers}
        cur_controller_ids = set(self._controllers.keys())
        controllers_to_add = new_controller_ids - cur_controller_ids
        controllers_to_del = cur_controller_ids - new_controller_ids

        logging.debug('Stac._config_ctrls_finish()        - controllers_to_add   = %s', list(controllers_to_add))
        logging.debug('Stac._config_ctrls_finish()        - controllers_to_del   = %s', list(controllers_to_del))

        for tid in controllers_to_del:
            controller = self._controllers.pop(tid, None)
            if controller is not None:
                controller.disconnect(self.remove_controller, conf.SvcConf().sticky_connections)

        for tid in controllers_to_add:
            self._controllers[tid] = ctrl.Ioc(self, self._root, self._host, tid)

    def _connect_to_staf(self, _):
        '''@brief Hook up DBus signal handlers for signals from stafd.'''
        try:
            self._staf = self._sysbus.get_proxy(defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)
            self._staf.log_pages_changed.connect(self._log_pages_changed)
            self._cfg_soak_tmr.start()

            # Make sure timer is set back to its normal value.
            self._cfg_soak_tmr.set_timeout(self.CONF_STABILITY_SOAK_TIME_SEC)
            logging.debug('Stac._connect_to_staf()            - Connected to staf')
        except dasbus.error.DBusError:
            logging.error('Failed to connect to staf')

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
            self._cfg_soak_tmr.set_timeout(self.CONF_STABILITY_LONG_SOAK_TIME_SEC)

        logging.debug('Stac._disconnect_from_staf()       - Disconnected from staf')

    def _log_pages_changed(  # pylint: disable=too-many-arguments
        self, transport, traddr, trsvcid, host_traddr, host_iface, subsysnqn, device
    ):
        logging.debug(
            'Stac._log_pages_changed()          - transport=%s, traddr=%s, trsvcid=%s, host_traddr=%s, host_iface=%s, subsysnqn=%s, device=%s',
            transport,
            traddr,
            trsvcid,
            host_traddr,
            host_iface,
            subsysnqn,
            device,
        )
        if self._cfg_soak_tmr:
            self._cfg_soak_tmr.start(self.CONF_STABILITY_SOAK_TIME_SEC)

    def _load_last_known_config(self):
        return dict()

    def _dump_last_known_config(self, controllers):
        pass


# ******************************************************************************
class Staf(Service):
    '''STorage Appliance Finder (STAF)'''

    def __init__(self, args, dbus):
        super().__init__(args, self._reload_hdlr)

        self._avahi = avahi.Avahi(self._sysbus, self._avahi_change)
        self._avahi.config_stypes(conf.SvcConf().get_stypes())

        # Create the D-Bus instance.
        self._config_dbus(dbus, defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)

    def info(self) -> dict:
        '''@brief Get the status info for this object (used for debug)'''
        info = super().info()
        info['avahi'] = self._avahi.info()
        return info

    def _release_resources(self):
        logging.debug('Staf._release_resources()')
        super()._release_resources()
        if self._avahi:
            self._avahi.kill()
            self._avahi = None

    def _load_last_known_config(self):
        try:
            with open(self._lkc_file, 'rb') as file:
                config = pickle.load(file)
        except (FileNotFoundError, AttributeError):
            return dict()

        logging.debug('Staf._load_last_known_config()     - DC count = %s', len(config))
        return {tid: ctrl.Dc(self, self._root, self._host, tid, log_pages) for tid, log_pages in config.items()}

    def _dump_last_known_config(self, controllers):
        try:
            with open(self._lkc_file, 'wb') as file:
                config = {tid: dc.log_pages() for tid, dc in controllers.items()}
                logging.debug('Staf._dump_last_known_config()     - DC count = %s', len(config))
                pickle.dump(config, file)
        except FileNotFoundError as ex:
            logging.error('Unable to save last known config: %s', ex)

    def _keep_connections_on_exit(self):
        '''@brief Determine whether connections should remain when the
        process exits.
        '''
        return conf.SvcConf().persistent_connections

    def _reload_hdlr(self):
        '''@brief Reload configuration file. This is triggered by the SIGHUP
        signal, which can be sent with "systemctl reload stafd".
        '''
        systemd.daemon.notify('RELOADING=1')
        service_cnf = conf.SvcConf()
        service_cnf.reload()
        self.tron = service_cnf.tron
        self._avahi.kick_start()  # Make sure Avahi is running
        self._avahi.config_stypes(service_cnf.get_stypes())
        self._cfg_soak_tmr.start()
        systemd.daemon.notify('READY=1')
        return GLib.SOURCE_CONTINUE

    def log_pages_changed(self, controller, device):
        '''@brief Function invoked when a controller's cached log pages
        have changed. This will emit a D-Bus signal to inform
        other applications that the cached log pages have changed.
        '''
        self._dbus_iface.log_pages_changed.emit(
            controller.tid.transport,
            controller.tid.traddr,
            controller.tid.trsvcid,
            controller.tid.host_traddr,
            controller.tid.host_iface,
            controller.tid.subsysnqn,
            device,
        )

    def referrals_changed(self):
        '''@brief Function invoked when a controller's cached referrals
        have changed.
        '''
        logging.debug('Staf.referrals_changed()')
        self._cfg_soak_tmr.start()

    def _referrals(self) -> list:
        return [
            stas.cid_from_dlpe(dlpe, controller.tid.host_traddr, controller.tid.host_iface)
            for controller in self.get_controllers()
            for dlpe in controller.referrals()
        ]

    def _config_ctrls_finish(self, configured_ctrl_list):
        '''@brief Finish discovery controllers configuration after
        hostnames (if any) have been resolved.
        '''
        configured_ctrl_list = [
            ctrl_dict
            for ctrl_dict in configured_ctrl_list
            if 'traddr' in ctrl_dict and ctrl_dict.setdefault('subsysnqn', defs.WELL_KNOWN_DISC_NQN)
        ]

        discovered_ctrl_list = self._avahi.get_controllers()
        referral_ctrl_list = self._referrals()
        logging.debug('Staf._config_ctrls_finish()        - configured_ctrl_list = %s', configured_ctrl_list)
        logging.debug('Staf._config_ctrls_finish()        - discovered_ctrl_list = %s', discovered_ctrl_list)
        logging.debug('Staf._config_ctrls_finish()        - referral_ctrl_list   = %s', referral_ctrl_list)

        controllers = stas.remove_blacklisted(configured_ctrl_list + discovered_ctrl_list + referral_ctrl_list)
        controllers = stas.remove_invalid_addresses(controllers)

        new_controller_ids = {trid.TID(controller) for controller in controllers}
        cur_controller_ids = set(self._controllers.keys())
        controllers_to_add = new_controller_ids - cur_controller_ids
        controllers_to_del = cur_controller_ids - new_controller_ids

        logging.debug('Staf._config_ctrls_finish()        - controllers_to_add   = %s', list(controllers_to_add))
        logging.debug('Staf._config_ctrls_finish()        - controllers_to_del   = %s', list(controllers_to_del))

        for tid in controllers_to_del:
            controller = self._controllers.pop(tid, None)
            if controller is not None:
                controller.disconnect(self.remove_controller, conf.SvcConf().persistent_connections)

        for tid in controllers_to_add:
            self._controllers[tid] = ctrl.Dc(self, self._root, self._host, tid)

    def _avahi_change(self):
        self._cfg_soak_tmr.start()
