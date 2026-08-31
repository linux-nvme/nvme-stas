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
import logging
import pathlib
from itertools import filterfalse
import dasbus.error
import dasbus.client.observer
import dasbus.client.proxy

from gi.repository import GLib
from systemd.daemon import notify as sd_notify
from staslib import avahi, conf, ctrl, defs, gutil, stas, timeparse, trid, udev


# ******************************************************************************
class CtrlTerminator:
    '''The Controller Terminator is used to gracefully disconnect from
    controllers. All communications with controllers is handled by the kernel.
    Once we make a request to the kernel to perform an operation (e.g. connect),
    we have to wait for it to complete before requesting another operation. This
    is particularly important when we want to disconnect from a controller while
    there are pending operations, especially a pending connect.

    The "connect" operation is especially unpredictable because all connect
    requests are made through the blocking interface "/dev/nvme-fabrics". This
    means that once a "connect" operation has been submitted, and depending on
    how many connect requests are made concurrently, it can take several seconds
    for a connect to be processed by the kernel.

    While connect or other operations are being performed, it is possible
    that a disconnect may be requested (e.g. someone or something changes the
    configuration to remove a controller). Because it is not possible to
    terminate a pending operation request, we have to wait for it to complete
    before we can issue a disconnect. Failure to do that will result in
    operations being performed by the kernel in reverse order. For example,
    a disconnect may be executed before a pending connect has had a chance to
    complete. And this will result in controllers that are supposed to be
    disconnected to be connected without nvme-stas knowing about it.

    The Controller Terminator is used when we need to disconnect from a
    controller. It will make sure that there are no pending operations before
    issuing a disconnect.
    '''

    DISPOSAL_AUDIT_PERIOD_SEC = 30

    def __init__(self):
        self._udev = udev.UDEV
        self._controllers = list()  # The list of controllers to dispose of.
        self._audit_tmr = gutil.GTimer(self.DISPOSAL_AUDIT_PERIOD_SEC, self._on_disposal_check)

    def dispose(self, controller: ctrl.Controller, on_controller_removed_cb, keep_connection: bool):
        '''Invoked by a service (stafd or stacd) to dispose of a controller'''
        if not keep_connection and stas.protected(controller.tid, controller.device):
            # Backstop. stas.remove_protected() keeps us from adopting a
            # controller that isn't ours in the first place, but ownership can
            # still change under one we already hold: our cached device name
            # can end up naming somebody else's connection after a remove/add
            # cycle, and _load_last_known_config() re-adopts from the pickle
            # without going through the filter. Whatever the reason, we are
            # done with the object, but the connection is not ours to tear
            # down: let go of it and leave it up. This holds whatever
            # "honor-fabric-zoning" says.
            logging.info('%s | %s - Connection is not ours to remove. Keeping it.', controller.tid, controller.device)
            keep_connection = True

        if controller.all_ops_completed():
            logging.debug(
                'CtrlTerminator.dispose()           - %s | %s: Invoke disconnect()', controller.tid, controller.device
            )
            controller.disconnect(on_controller_removed_cb, keep_connection)
        else:
            logging.debug(
                'CtrlTerminator.dispose()           - %s | %s: Add controller to garbage disposal',
                controller.tid,
                controller.device,
            )
            self._controllers.append((controller, keep_connection, on_controller_removed_cb, controller.tid))

            self._udev.register_for_action_events('add', self._on_kernel_events)
            self._udev.register_for_action_events('remove', self._on_kernel_events)

            if self._audit_tmr.time_remaining() == 0:
                self._audit_tmr.start()

    def info(self):
        '''Return info about this object (used for debug).'''
        info = {
            'terminator.audit timer': str(self._audit_tmr),
        }
        for controller, _, _, tid in self._controllers:
            info[f'terminator.controller.{tid}'] = str(controller.info())
        return info

    def kill(self):
        '''Stop Controller Terminator and release resources.'''
        self._audit_tmr.stop()
        self._audit_tmr = None

        if self._udev:
            self._udev.unregister_for_action_events('add', self._on_kernel_events)
            self._udev.unregister_for_action_events('remove', self._on_kernel_events)
            self._udev = None

        for controller, keep_connection, on_controller_removed_cb, _ in self._controllers:
            controller.disconnect(on_controller_removed_cb, keep_connection)

        self._controllers.clear()

    def _on_kernel_events(self, udev_obj):
        logging.debug('CtrlTerminator._on_kernel_events() - %s event received', udev_obj.action)
        self._disposal_check()

    def _on_disposal_check(self, *_user_data):
        logging.debug('CtrlTerminator._on_disposal_check()- Periodic audit')
        return GLib.SOURCE_REMOVE if self._disposal_check() else GLib.SOURCE_CONTINUE

    @staticmethod
    def _keep_or_terminate(args):
        '''Return False if controller is to be kept. True if controller
        was terminated and can be removed from the list.'''
        controller, keep_connection, on_controller_removed_cb, tid = args
        if controller.all_ops_completed():
            logging.debug(
                'CtrlTerminator._keep_or_terminate()- %s | %s: Disconnecting controller',
                tid,
                controller.device,
            )
            controller.disconnect(on_controller_removed_cb, keep_connection)
            return True

        return False

    def _disposal_check(self):
        # Iterate over the list, terminating (disconnecting) those controllers
        # that have no pending operations, and remove those controllers from the
        # list (only keep controllers that still have operations pending).
        self._controllers[:] = filterfalse(self._keep_or_terminate, self._controllers)
        disposal_complete = len(self._controllers) == 0

        if disposal_complete:
            logging.debug('CtrlTerminator._disposal_check()   - Disposal complete')
            self._audit_tmr.stop()
            self._udev.unregister_for_action_events('add', self._on_kernel_events)
            self._udev.unregister_for_action_events('remove', self._on_kernel_events)
        else:
            self._audit_tmr.start()  # Restart timer

        return disposal_complete


# ******************************************************************************
class Service(stas.ServiceABC):
    '''Base class for managing a STorage Appliance Service.'''

    def __init__(self, args, default_conf, reload_hdlr):
        self._udev = udev.UDEV
        self._terminator = CtrlTerminator()

        super().__init__(args, default_conf, reload_hdlr)

    def _release_resources(self):
        logging.debug('Service._release_resources()')
        super()._release_resources()

        if self._terminator:
            self._terminator.kill()

        self._udev = None
        self._terminator = None

    def _disconnect_all(self):
        '''Tell all controller objects to disconnect'''
        keep_connections = self._keep_connections_on_exit()
        controllers = self._controllers.values()
        logging.debug(
            'Service._stop_hdlr()               - Controller count = %s, keep_connections = %s',
            len(controllers),
            keep_connections,
        )
        for controller in controllers:
            self._terminator.dispose(controller, self._on_final_disconnect, keep_connections)

    def info(self) -> dict:
        '''Return the status info for this object (used for debug).'''
        info = super().info()
        if self._terminator:
            info.update(self._terminator.info())
        return info

    @stas.ServiceABC.tron.setter
    def tron(self, value):
        '''Set the Trace ON (tron) flag.'''
        super(__class__, self.__class__).tron.__set__(self, value)


# ******************************************************************************
class Stac(Service):
    '''STorage Appliance Connector (STAC)'''

    CONFIGURES_DCS = False

    CONF_STABILITY_LONG_SOAK_TIME_SEC = 10

    def __init__(self, args, dbus):
        default_conf = {
            ('Global', 'tron'): False,
            ('Global', 'ignore-iface'): False,
            ('Global', 'ip-family'): (4, 6),
            ('Controllers', 'exclude'): list(),
            ('I/O controller connection management', 'honor-fabric-zoning'): True,
            ('I/O controller connection management', 'connect-attempts-on-ncc'): 0,
        }

        super().__init__(args, default_conf, self._reload_hdlr)

        # Create the D-Bus instance.
        self._config_dbus(dbus, defs.STACD_DBUS_NAME, defs.STACD_DBUS_PATH)

        # Connect to STAF D-Bus interface
        self._staf = None
        self._staf_watcher = dasbus.client.observer.DBusObserver(self._sysbus, defs.STAFD_DBUS_NAME)
        self._staf_watcher.service_available.connect(self._connect_to_staf)
        self._staf_watcher.service_unavailable.connect(self._disconnect_from_staf)
        self._staf_watcher.connect_once_available()

    def _release_resources(self):
        logging.debug('Stac._release_resources()')

        self._destroy_staf_comlink(self._staf_watcher)
        if self._staf_watcher is not None:
            self._staf_watcher.disconnect()

        super()._release_resources()

        self._staf = None
        self._staf_watcher = None

    def _dump_last_known_config(self, controllers):
        config = list(controllers.keys())
        logging.debug('Stac._dump_last_known_config()     - IOC count = %s', len(config))
        self._write_lkc(config)

    def _load_last_known_config(self):
        config = self._read_lkc() or list()
        logging.debug('Stac._load_last_known_config()     - IOC count = %s', len(config))

        controllers = {}
        for tid in config:
            # Only create Ioc objects if there is already a connection in the kernel
            # First, regenerate the TID (in case of soft. upgrade and TID object
            # has changed internally)
            tid = trid.TID(tid.as_dict())
            if udev.UDEV.find_nvme_ioc_device(tid) is not None:
                controllers[tid] = ctrl.Ioc(self, tid)

        return controllers

    def _keep_connections_on_exit(self):
        '''Return True if connections should persist when stacd exits.'''
        return True

    def _reload_hdlr(self):
        '''Reload the configuration file. Triggered by SIGHUP (systemctl reload stacd).'''
        if not self._alive():
            return GLib.SOURCE_REMOVE

        sd_notify('RELOADING=1')
        service_cnf = conf.SvcConf()
        service_cnf.reload()
        self._conn_conf.reload()
        self.tron = service_cnf.tron
        self._cfg_soak_tmr.start(self.CONF_STABILITY_SOAK_TIME_SEC)

        for controller in self._controllers.values():
            controller.reload_hdlr()

        sd_notify('READY=1')
        return GLib.SOURCE_CONTINUE

    def _get_log_pages_from_stafd(self):
        if self._staf:
            try:
                return json.loads(self._staf.get_all_log_pages(True))
            except dasbus.error.DBusError as ex:
                logging.debug('Stac._get_log_pages_from_stafd()   - %s', ex)

        return list()

    def _config_ctrls_finish(self, configured_ctrl_list: list):
        '''Finish I/O controller configuration after hostname resolution, then reconcile running controllers.'''
        # This is a callback function, which may be called after the service
        # has been signalled to stop. So let's make sure the service is still
        # alive and well before continuing.
        if not self._alive():
            logging.debug('Stac._config_ctrls_finish()        - Exiting because service is no longer alive')
            return

        # Eliminate invalid entries from stacd.conf "controller list".
        configured_ctrl_list = [
            tid for tid in configured_ctrl_list if '' not in (tid.transport, tid.traddr, tid.trsvcid, tid.subsysnqn)
        ]

        logging.debug('Stac._config_ctrls_finish()        - configured_ctrl_list = %s', configured_ctrl_list)

        discovered_ctrls = dict()
        for staf_data in self._get_log_pages_from_stafd():
            host_traddr = staf_data['discovery-controller']['host-traddr']
            host_iface = staf_data['discovery-controller']['host-iface']
            hostnqn = staf_data['discovery-controller']['hostnqn']
            for dlpe in staf_data['log-pages']:
                if dlpe.get('subtype') == 'nvme':  # eliminate discovery controllers
                    tid = stas.tid_from_dlpe(dlpe, host_traddr, host_iface, hostnqn)
                    discovered_ctrls[tid] = dlpe

        discovered_ctrl_list = list(discovered_ctrls.keys())
        logging.debug('Stac._config_ctrls_finish()        - discovered_ctrl_list = %s', discovered_ctrl_list)

        controllers = stas.remove_excluded(configured_ctrl_list + discovered_ctrl_list)
        controllers = stas.remove_invalid_addresses(controllers)
        controllers = stas.remove_protected(controllers, self._udev.find_nvme_ioc_device)

        new_controller_tids = set(controllers)
        cur_controller_tids = set(self._controllers.keys())
        controllers_to_add = new_controller_tids - cur_controller_tids
        controllers_to_del = cur_controller_tids - new_controller_tids

        logging.debug('Stac._config_ctrls_finish()        - controllers_to_add   = %s', list(controllers_to_add))
        logging.debug('Stac._config_ctrls_finish()        - controllers_to_del   = %s', list(controllers_to_del))

        # A controller we no longer want is disconnected when we honor fabric
        # zoning, which is what "no longer zoned for this host" is telling us.
        # Otherwise we let go of the controller object but leave the connection
        # up.
        keep_connection = not conf.SvcConf().honor_fabric_zoning
        logging.debug('Stac._config_ctrls_finish()        - keep_connection      = %s', keep_connection)
        for tid in controllers_to_del:
            controller = self._controllers.pop(tid, None)
            if controller is not None:
                self._terminator.dispose(controller, self.remove_controller, keep_connection)

        for tid in controllers_to_add:
            self._controllers[tid] = ctrl.Ioc(self, tid)

        for tid, controller in self._controllers.items():
            if tid in discovered_ctrls:
                dlpe = discovered_ctrls[tid]
                controller.update_dlpe(dlpe)

        self._dump_last_known_config(self._controllers)

    def _connect_to_staf(self, _):
        '''Connect to the stafd D-Bus interface and hook up signal handlers.'''
        if not self._alive():
            return

        try:
            self._staf = self._sysbus.get_proxy(defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)
            self._staf.log_pages_changed.connect(self._log_pages_changed)
            self._staf.dc_removed.connect(self._dc_removed)
            self._cfg_soak_tmr.start()

            # Make sure timer is set back to its normal value.
            self._cfg_soak_tmr.set_timeout(self.CONF_STABILITY_SOAK_TIME_SEC)
            logging.debug('Stac._connect_to_staf()            - Connected to staf')
        except dasbus.error.DBusError:
            logging.error('Failed to connect to staf')

    def _destroy_staf_comlink(self, watcher):
        if self._staf:
            self._staf.log_pages_changed.disconnect(self._log_pages_changed)
            self._staf.dc_removed.disconnect(self._dc_removed)
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

    def _log_pages_changed(self, transport, traddr, trsvcid, subsysnqn, host_traddr, host_iface, hostnqn, device):
        if not self._alive():
            return

        logging.debug(
            'Stac._log_pages_changed()          - transport=%s, traddr=%s, trsvcid=%s, subsysnqn=%s, host_traddr=%s, host_iface=%s, hostnqn=%s, device=%s',
            transport,
            traddr,
            trsvcid,
            subsysnqn,
            host_traddr,
            host_iface,
            hostnqn,
            device,
        )
        if self._cfg_soak_tmr:
            self._cfg_soak_tmr.start(self.CONF_STABILITY_SOAK_TIME_SEC)

    def _dc_removed(self):
        if not self._alive():
            return

        logging.debug('Stac._dc_removed()')
        if self._cfg_soak_tmr:
            self._cfg_soak_tmr.start(self.CONF_STABILITY_SOAK_TIME_SEC)


# ******************************************************************************
def _remove_stale_udev_rule_override():
    '''Remove the udev rule override that nvme-stas used to install.

    Until 3.0, stafd shadowed nvme-cli's 70-nvmf-autoconnect.rules with a copy
    in /run/udev/rules.d that kept only the legacy FC rule. udevd is written in
    C and stafd in Python, so udevd always won the race to react to a Discovery
    Log Page AEN, and "nvme connect-all" would connect controllers behind our
    back. The ownership registry settles that race at the source: connect-all
    reads the Discovery Controller's owner and does nothing at all when the
    controller belongs to somebody else.

    /run is a tmpfs, so a reboot disposes of the file on its own, but an
    upgrade without a reboot does not, and the code that used to remove it is
    gone. Drop it here instead. This can go once upgrades from 3.0 are a
    distant memory.
    '''
    try:
        pathlib.Path('/run/udev/rules.d', '70-nvmf-autoconnect.rules').unlink()
    except FileNotFoundError:
        pass
    except OSError as ex:
        logging.warning('Unable to remove the stale udev rule override: %s', ex)


# ******************************************************************************
class Staf(Service):
    '''STorage Appliance Finder (STAF)'''

    CONFIGURES_DCS = True

    def __init__(self, args, dbus):
        default_conf = {
            ('Global', 'tron'): False,
            ('Discovery controller connection management', 'persistent-connections'): True,
            ('Discovery controller connection management', 'dc-giveup-timeout'): timeparse.timeparse('72hours'),
            ('Global', 'ignore-iface'): False,
            ('Global', 'ip-family'): (4, 6),
            ('Global', 'pleo'): True,
            ('Service Discovery', 'zeroconf'): True,
            ('Controllers', 'exclude'): list(),
        }

        super().__init__(args, default_conf, self._reload_hdlr)

        self._avahi = avahi.Avahi(self._sysbus, self._avahi_change)
        self._avahi.config_stypes(conf.SvcConf().stypes)

        # Create the D-Bus instance.
        self._config_dbus(dbus, defs.STAFD_DBUS_NAME, defs.STAFD_DBUS_PATH)

        _remove_stale_udev_rule_override()

    def info(self) -> dict:
        '''Return the status info for this object (used for debug).'''
        info = super().info()
        info['avahi'] = self._avahi.info()
        return info

    def _release_resources(self):
        logging.debug('Staf._release_resources()')
        super()._release_resources()

        if self._avahi:
            self._avahi.kill()
            self._avahi = None

    def _dump_last_known_config(self, controllers):
        config = {tid: {'log_pages': dc.log_pages(), 'origin': dc.origin} for tid, dc in controllers.items()}
        logging.debug('Staf._dump_last_known_config()     - DC count = %s', len(config))
        self._write_lkc(config)

    def _load_last_known_config(self):
        config = self._read_lkc() or dict()
        logging.debug('Staf._load_last_known_config()     - DC count = %s', len(config))

        controllers = {}
        for tid, data in config.items():
            if isinstance(data, dict):
                log_pages = data.get('log_pages')
                origin = data.get('origin')
            else:
                log_pages = data
                origin = None

            # Regenerate the TID (in case of soft. upgrade and TID object
            # has changed internally)
            tid = trid.TID(tid.as_dict())
            controllers[tid] = ctrl.Dc(self, tid, log_pages, origin)

        return controllers

    def _keep_connections_on_exit(self):
        '''Return True if connections should persist when stafd exits.'''
        return conf.SvcConf().persistent_connections

    def _reload_hdlr(self):
        '''Reload the configuration file. Triggered by SIGHUP (systemctl reload stafd).'''
        if not self._alive():
            return GLib.SOURCE_REMOVE

        sd_notify('RELOADING=1')
        service_cnf = conf.SvcConf()
        service_cnf.reload()
        self._conn_conf.reload()
        self.tron = service_cnf.tron
        self._avahi.kick_start()  # Make sure Avahi is running
        self._avahi.config_stypes(service_cnf.stypes)
        self._cfg_soak_tmr.start()

        for controller in self._controllers.values():
            controller.reload_hdlr()

        sd_notify('READY=1')
        return GLib.SOURCE_CONTINUE

    def is_avahi_reported(self, tid):
        '''Return True if tid is currently being reported by the Avahi daemon.'''
        for cid in self._avahi.get_controllers():
            if trid.TID(cid) == tid:
                return True
        return False

    def log_pages_changed(self, controller, device):
        '''Emit the log_pages_changed D-Bus signal when a controller's cached log pages have changed.'''
        self._dbus_iface.log_pages_changed.emit(
            controller.tid.transport,
            controller.tid.traddr,
            controller.tid.trsvcid,
            controller.tid.subsysnqn,
            controller.tid.host_traddr,
            controller.tid.host_iface,
            controller.tid.hostnqn,
            device,
        )

    def dc_removed(self):
        '''Emit the dc_removed D-Bus signal when one or more discovery controllers have been removed.'''
        self._dbus_iface.dc_removed.emit()

    def _referrals(self) -> list:
        return [
            stas.tid_from_dlpe(
                dlpe,
                controller.tid.host_traddr,
                controller.tid.host_iface,
                controller.tid.hostnqn,
            )
            for controller in self.get_controllers()
            for dlpe in controller.referrals()
        ]

    def _config_ctrls_finish(self, configured_ctrl_list: list):
        '''Finish discovery controller configuration after hostname resolution.
        All creation/deletion logic for discovery controllers is here. Called
        after the self._cfg_soak_tmr soak period expires.
        '''
        # This is a callback function, which may be called after the service
        # has been signalled to stop. So let's make sure the service is still
        # alive and well before continuing.
        if not self._alive():
            logging.debug('Staf._config_ctrls_finish()        - Exiting because service is no longer alive')
            return

        # Eliminate invalid entries from stafd.conf "controller list".
        controllers = list()
        for tid in configured_ctrl_list:
            if '' in (tid.transport, tid.traddr, tid.trsvcid):
                continue
            if not tid.subsysnqn:
                cid = tid.as_dict()
                cid['subsysnqn'] = defs.WELL_KNOWN_DISC_NQN
                controllers.append(trid.TID(cid))
            else:
                controllers.append(tid)
        configured_ctrl_list = controllers

        # Get the Avahi-discovered list and the referrals.
        discovered_ctrl_list = [trid.TID(cid) for cid in self._avahi.get_controllers()]
        referral_ctrl_list = self._referrals()
        logging.debug('Staf._config_ctrls_finish()        - configured_ctrl_list = %s', configured_ctrl_list)
        logging.debug('Staf._config_ctrls_finish()        - discovered_ctrl_list = %s', discovered_ctrl_list)
        logging.debug('Staf._config_ctrls_finish()        - referral_ctrl_list   = %s', referral_ctrl_list)

        all_ctrls = configured_ctrl_list + discovered_ctrl_list + referral_ctrl_list
        controllers = stas.remove_excluded(all_ctrls)
        controllers = stas.remove_invalid_addresses(controllers)
        controllers = stas.remove_protected(controllers, self._udev.find_nvme_dc_device)

        new_controller_tids = set(controllers)
        cur_controller_tids = set(self._controllers.keys())
        controllers_to_add = new_controller_tids - cur_controller_tids
        controllers_to_del = cur_controller_tids - new_controller_tids

        # Make a list list of excluded and invalid controllers
        must_remove_list = set(all_ctrls) - new_controller_tids

        # Find "discovered" controllers that have not responded
        # in a while and add them to controllers that must be removed.
        must_remove_list.update({tid for tid, controller in self._controllers.items() if controller.is_unresponsive()})

        # Do not remove Avahi-discovered DCs from controllers_to_del unless
        # marked as "must-be-removed" (must_remove_list). This is to account for
        # the case where mDNS discovery is momentarily disabled (e.g. Avahi
        # daemon restarts). We don't want to delete connections because of
        # temporary mDNS impairments. Removal of Avahi-discovered DCs will be
        # handled differently and only if the connection cannot be established
        # for a long period of time.
        logging.debug('Staf._config_ctrls_finish()        - must_remove_list     = %s', list(must_remove_list))
        controllers_to_del = {
            tid
            for tid in controllers_to_del
            if tid in must_remove_list or self._controllers[tid].origin != 'discovered'
        }

        logging.debug('Staf._config_ctrls_finish()        - controllers_to_add   = %s', list(controllers_to_add))
        logging.debug('Staf._config_ctrls_finish()        - controllers_to_del   = %s', list(controllers_to_del))

        # Delete controllers
        for tid in controllers_to_del:
            controller = self._controllers.pop(tid, None)
            if controller is not None:
                self._terminator.dispose(controller, self.remove_controller, keep_connection=False)

        if len(controllers_to_del) > 0:
            self.dc_removed()  # Let other apps (e.g. stacd) know that discovery controllers were removed.

        # Add controllers
        for tid in controllers_to_add:
            self._controllers[tid] = ctrl.Dc(self, tid)

        # Update "origin" on all DC objects
        for tid, controller in self._controllers.items():
            origin = (
                'configured'
                if tid in configured_ctrl_list
                else 'referral'
                if tid in referral_ctrl_list
                else 'discovered'
                if tid in discovered_ctrl_list
                else None
            )
            if origin is not None:
                controller.origin = origin

        self._dump_last_known_config(self._controllers)

    def _avahi_change(self):
        if self._alive() and self._cfg_soak_tmr is not None:
            self._cfg_soak_tmr.start()

    def controller_unresponsive(self, tid):
        '''Called when a controller becomes unresponsive and needs to be removed.'''
        if self._alive() and self._cfg_soak_tmr is not None:
            logging.debug('Staf.controller_unresponsive()     - tid = %s', tid)
            self._cfg_soak_tmr.start()

    def referrals_changed(self):
        '''Called when a controller's cached referrals have changed.'''
        if self._alive() and self._cfg_soak_tmr is not None:
            logging.debug('Staf.referrals_changed()')
            self._cfg_soak_tmr.start()
