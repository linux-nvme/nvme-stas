# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''Library for staf/stac'''

import os
import sys
import signal
import ipaddress
import systemd.daemon
import dasbus.connection

from gi.repository import Gio, GLib
from libnvme import nvme
from staslib import defs, conf, log, gutil, trid, udev


NVME_ROOT = nvme.root()  # Singleton
DC_KATO_DEFAULT = 30  # seconds
TRON = False  # Singleton
UDEV = udev.Udev()

# ******************************************************************************
def check_if_allowed_to_continue():
    '''@brief Let's perform some basic checks before going too far. There are
           a few pre-requisites that need to be met before this program
           is allowed to proceed:

             1) The program needs to have root privileges
             2) The nvme-tcp kernel module must be loaded

    @return This function will only return if all conditions listed above
            are met. Otherwise the program exits.
    '''
    # 1) Check root privileges
    if os.geteuid() != 0:
        sys.exit(f'Permission denied. You need root privileges to run {defs.PROG_NAME}.')

    # 2) Check that nvme-tcp kernel module is running
    if not os.path.exists('/dev/nvme-fabrics'):
        # There's no point going any further if the kernel module hasn't been loaded
        sys.exit('Fatal error: missing nvme-tcp kernel module')


# ******************************************************************************
def trace_control(tron: bool):
    '''@brief Allows changing debug level in real time. Setting tron to True
    enables full tracing.
    '''
    global TRON  # pylint: disable=global-statement
    TRON = tron
    log.set_level_from_tron(TRON)
    NVME_ROOT.log_level("debug" if TRON else "err")


# ******************************************************************************
def cid_from_dlpe(dlpe, host_traddr, host_iface):
    '''@brief Take a Discovery Log Page Entry and return a Controller ID as a dict.'''
    return {
        'transport':   dlpe['trtype'],
        'traddr':      dlpe['traddr'],
        'trsvcid':     dlpe['trsvcid'],
        'host-traddr': host_traddr,
        'host-iface':  host_iface,
        'subsysnqn':   dlpe['subnqn'],
    }


# ******************************************************************************
def _blacklisted(blacklisted_ctrl_list, controller):
    '''@brief Check if @controller is black-listed.'''
    for blacklisted_ctrl in blacklisted_ctrl_list:
        test_results = [val == controller.get(key, None) for key, val in blacklisted_ctrl.items()]
        if all(test_results):
            return True
    return False


# ******************************************************************************
def remove_blacklisted(controllers: list):
    '''@brief Remove black-listed controllers from the list of controllers.'''
    blacklisted_ctrl_list = conf.PROCESS.get_blacklist()
    if blacklisted_ctrl_list:
        log.LOG.debug('remove_blacklisted()               - blacklisted_ctrl_list = %s', blacklisted_ctrl_list)
        controllers = [controller for controller in controllers if not _blacklisted(blacklisted_ctrl_list, controller)]
    return controllers


# ******************************************************************************
def remove_invalid_addresses(controllers: list):
    '''@brief Remove controllers with invalid addresses from the list of controllers.'''
    valid_controllers = list()
    for controller in controllers:
        if controller.get('transport') in ('tcp', 'rdma'):
            # Let's make sure that traddr is
            # syntactically a valid IPv4 or IPv6 address.
            traddr = controller.get('traddr')
            try:
                ip = ipaddress.ip_address(traddr)
            except ValueError:
                log.LOG.warning('%s IP address is not valid', trid.TID(controller))
                continue

            if ip.version not in conf.PROCESS.ip_family:
                log.LOG.debug(
                    '%s ignored because IPv%s is disabled in %s',
                    trid.TID(controller),
                    ip.version,
                    conf.PROCESS.conf_file,
                )
                continue

        # At some point, need to validate FC addresses as well...

        valid_controllers.append(controller)

    return valid_controllers


# ******************************************************************************
class Controller:  # pylint: disable=too-many-instance-attributes
    '''@brief Base class used to manage the connection to a controller.'''

    CONNECT_RETRY_PERIOD_SEC = 60
    FAST_CONNECT_RETRY_PERIOD_SEC = 3

    def __init__(self, root, host, tid: trid.TID, discovery_ctrl=False):
        self._root              = root
        self._host              = host
        self._tid               = tid
        self._cancellable       = Gio.Cancellable()
        self._connect_op        = None
        self._connect_attempts  = 0
        self._retry_connect_tmr = gutil.GTimer(Controller.CONNECT_RETRY_PERIOD_SEC, self._on_try_to_connect)
        self._device            = None
        self._ctrl              = None
        self._discovery_ctrl    = discovery_ctrl
        self._try_to_connect_deferred = gutil.Deferred(self._try_to_connect)
        self._try_to_connect_deferred.schedule()

    def _release_resources(self):
        log.LOG.debug('Controller._release_resources()    - %s', self.id)

        # Remove pending deferred from main loop
        if self._try_to_connect_deferred:
            self._try_to_connect_deferred.cancel()
        self._try_to_connect_deferred = None

        device = self.device
        if device:
            UDEV.unregister_for_device_events(self._on_udev_notification)

        if self._retry_connect_tmr is not None:
            self._retry_connect_tmr.kill()

        if self._cancellable and not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        self._kill_ops()

        self._tid = None
        self._ctrl = None
        self._device = None
        self._retry_connect_tmr = None
        self._cancellable = None

    def _alive(self):
        '''There may be race condition where a queued event gets processed
        after the object is no longer configured (i.e. alive). This method
        can be used by callback functions to make sure the object is still
        alive before processing further.
        '''
        return self._cancellable and not self._cancellable.is_cancelled()

    def _kill_ops(self):
        if self._connect_op:
            self._connect_op.kill()
            self._connect_op = None

    def _on_udev_notification(self, udev_obj):
        if self._alive():
            if udev_obj.action == 'change':
                nvme_aen = udev_obj.get("NVME_AEN")
                nvme_event = udev_obj.get("NVME_EVENT")
                if isinstance(nvme_aen, str):
                    log.LOG.info('%s | %s - Received AEN: %s', self.id, udev_obj.sys_name, nvme_aen)
                    self._on_aen(udev_obj, int(nvme_aen, 16))
                if isinstance(nvme_event, str):
                    self._on_nvme_event(udev_obj, nvme_event)
            elif udev_obj.action == 'remove':
                log.LOG.info('%s | %s - Received "remove" event', self.id, udev_obj.sys_name)
                self._on_udev_remove(udev_obj)
            else:
                log.LOG.debug(
                    'Controller._on_udev_notification() - %s | %s - Received "%s" notification.',
                    self.id,
                    udev_obj.sys_name,
                    udev_obj.action,
                )
        else:
            log.LOG.debug(
                'Controller._on_udev_notification() - %s | %s - Received event on dead object. udev_obj %s: %s',
                self.id,
                self.device,
                udev_obj.action,
                udev_obj.sys_name,
            )

    def _on_aen(self, udev_obj, aen: int):
        pass

    def _on_nvme_event(self, udev_obj, nvme_event):
        pass

    def _on_udev_remove(self, udev_obj):  # pylint: disable=unused-argument
        UDEV.unregister_for_device_events(self._on_udev_notification)
        self._kill_ops()  # Kill all pending operations
        self._ctrl = None

    def _find_existing_connection(self):
        raise NotImplementedError()

    def _on_try_to_connect(self):
        self._try_to_connect_deferred.schedule()
        return GLib.SOURCE_REMOVE

    def _try_to_connect(self):
        # This is a deferred function call. Make sure
        # the source of the deferred is still good.
        source = GLib.main_current_source()
        if source and source.is_destroyed():
            return

        self._connect_attempts += 1

        host_iface = (
            self.tid.host_iface
            if (self.tid.host_iface and not conf.PROCESS.ignore_iface and conf.NvmeOptions().host_iface_supp)
            else None
        )
        self._ctrl = nvme.ctrl(
            self._root,
            subsysnqn=self.tid.subsysnqn,
            transport=self.tid.transport,
            traddr=self.tid.traddr,
            trsvcid=self.tid.trsvcid if self.tid.trsvcid else None,
            host_traddr=self.tid.host_traddr if self.tid.host_traddr else None,
            host_iface=host_iface,
        )
        self._ctrl.discovery_ctrl_set(self._discovery_ctrl)

        # Audit existing nvme devices. If we find a match, then
        # we'll just borrow that device instead of creating a new one.
        udev_obj = self._find_existing_connection()
        if udev_obj is not None:
            # A device already exists.
            self._device = udev_obj.sys_name
            log.LOG.debug(
                'Controller._try_to_connect()       - %s Found existing control device: %s', self.id, udev_obj.sys_name
            )
            self._connect_op = gutil.AsyncOperationWithRetry(
                self._on_connect_success, self._on_connect_fail, self._ctrl.init, self._host, int(udev_obj.sys_number)
            )
        else:
            self._device = None
            cfg = { 'hdr_digest':  conf.PROCESS.hdr_digest,
                    'data_digest': conf.PROCESS.data_digest }
            if conf.PROCESS.kato is not None:
                cfg['keep_alive_tmo'] = conf.PROCESS.kato
            elif self._discovery_ctrl:
                # All the connections to Controllers (I/O and Discovery) are
                # persistent. Persistent connections MUST configure the KATO.
                # The kernel already assigns a default 2-minute KATO to I/O
                # controller connections, but it doesn't assign one to
                # Discovery controller (DC) connections. Here we set the default
                # DC connection KATO to match the default set by nvme-cli on
                # persistent DC connections (i.e. 30 sec).
                cfg['keep_alive_tmo'] = DC_KATO_DEFAULT

            log.LOG.debug(
                'Controller._try_to_connect()       - %s Connecting to nvme control with cfg=%s', self.id, cfg
            )
            self._connect_op = gutil.AsyncOperationWithRetry(
                self._on_connect_success, self._on_connect_fail, self._ctrl.connect, self._host, cfg
            )

        self._connect_op.run_async()

    # --------------------------------------------------------------------------
    def _on_connect_success(self, op_obj, data):
        '''@brief Function called when we successfully connect to the
        Controller.
        '''
        op_obj.kill()
        self._connect_op = None

        if self._alive():
            if not self._device:
                self._device = self._ctrl.name
            log.LOG.info('%s | %s - Connection established!', self.id, self.device)
            self._connect_attempts = 0
            UDEV.register_for_device_events(self.device, self._on_udev_notification)
        else:
            log.LOG.debug(
                'Controller._on_connect_success()   - %s | %s Received event on dead object. data=%s',
                self.id,
                self.device,
                data,
            )

    def _on_connect_fail(self, op_obj, err, fail_cnt):  # pylint: disable=unused-argument
        '''@brief Function called when we fail to connect to the Controller.'''
        op_obj.kill()
        if self._alive():
            if self._connect_attempts == 1:
                # Do a fast re-try on the first failure.
                # A race condition between "nvme connect-all" and "stacd" can result
                # in a failed connection message even when the connection is successful.
                # More precisely, nvme-cli's "connect-all" command relies on udev rules
                # to trigger a "nvme connect" command when an AEN indicates that the
                # Discovery Log Page Entries (DPLE) have changed. And since stacd also
                # reacts to AENs to set up I/O controller connections, we end up having
                # both stacd and udevd trying to connect to the same I/O controllers at
                # the same time. This is perfectly fine, except that we may get a bogus
                # failed to connect error. By doing a fast re-try, stacd can quickly
                # verify that the connection was actually successful.
                self._retry_connect_tmr.set_timeout(Controller.FAST_CONNECT_RETRY_PERIOD_SEC)
            elif self._connect_attempts == 2:
                # If the fast connect re-try fails, then we can print a message to
                # indicate the failure, and start a slow re-try period.
                self._retry_connect_tmr.set_timeout(Controller.CONNECT_RETRY_PERIOD_SEC)
                log.LOG.error('%s Failed to connect to controller. %s', self.id, getattr(err, 'message', err))

            log.LOG.debug(
                'Controller._on_connect_fail()      - %s %s. Retry in %s sec.',
                self.id,
                err,
                self._retry_connect_tmr.get_timeout(),
            )
            self._retry_connect_tmr.start()
        else:
            log.LOG.debug(
                'Controller._on_connect_fail()      - %s Received event on dead object. %s',
                self.id,
                getattr(err, 'message', err),
            )

    @property
    def id(self) -> str:  # pylint: disable=missing-function-docstring
        return str(self.tid)

    @property
    def tid(self):  # pylint: disable=missing-function-docstring
        return self._tid

    @property
    def device(self) -> str:  # pylint: disable=missing-function-docstring
        return self._device if self._device else ''

    def controller_id_dict(self) -> dict:
        '''@brief return the controller ID as a dict.'''
        cid = self.tid.as_dict()
        cid['device'] = self.device
        return cid

    def details(self) -> dict:
        '''@brief return detailed debug info about this controller'''
        details = self.controller_id_dict()
        details.update(UDEV.get_attributes(self.device, ('hostid', 'hostnqn', 'model', 'serial')))
        details['connect attempts'] = str(self._connect_attempts)
        details['retry connect timer'] = str(self._retry_connect_tmr)
        return details

    def info(self) -> dict:
        '''@brief Get the controller info for this object'''
        info = self.details()
        if self._connect_op:
            info['connect operation'] = self._connect_op.as_dict()
        return info

    def cancel(self):
        '''@brief Used to cancel pending operations.'''
        if self._cancellable and not self._cancellable.is_cancelled():
            log.LOG.debug('Controller.cancel()                - %s', self.id)
            self._cancellable.cancel()

        if self._connect_op:
            self._connect_op.cancel()

    def kill(self):
        '''@brief Used to release all resources associated with this object.'''
        log.LOG.debug('Controller.kill()                  - %s', self.id)
        self._release_resources()

    def disconnect(self, disconnected_cb, keep_connection):
        '''@brief Issue an asynchronous disconnect command to a Controller.
        Once the async command has completed, the callback 'disconnected_cb'
        will be invoked. If a controller is already disconnected, then the
        callback will be added to the main loop's next idle slot to be executed
        ASAP.
        '''
        log.LOG.debug('Controller.disconnect()            - %s | %s', self.id, self.device)
        self._kill_ops()
        if self._ctrl and self._ctrl.connected() and not keep_connection:
            log.LOG.info('%s | %s - Disconnect initiated', self.id, self.device)
            op = gutil.AsyncOperationWithRetry(self._on_disconn_success, self._on_disconn_fail, self._ctrl.disconnect)
            op.run_async(disconnected_cb)
        else:
            # Defer callback to the next main loop's idle period. The callback
            # cannot be called directly as the current Controller object is in the
            # process of being disconnected and the callback will in fact delete
            # the object. This would invariably lead to unpredictable outcome.
            GLib.idle_add(disconnected_cb, self)

    def _on_disconn_success(self, op_obj, data, disconnected_cb):  # pylint: disable=unused-argument
        log.LOG.debug('Controller._on_disconn_success()   - %s | %s', self.id, self.device)
        op_obj.kill()
        # Defer callback to the next main loop's idle period. The callback
        # cannot be called directly as the current Controller object is in the
        # process of being disconnected and the callback will in fact delete
        # the object. This would invariably lead to unpredictable outcome.
        GLib.idle_add(disconnected_cb, self)

    def _on_disconn_fail(self, op_obj, err, fail_cnt, disconnected_cb):  # pylint: disable=unused-argument
        log.LOG.debug('Controller._on_disconn_fail()      - %s | %s: %s', self.id, self.device, err)
        op_obj.kill()
        # Defer callback to the next main loop's idle period. The callback
        # cannot be called directly as the current Controller object is in the
        # process of being disconnected and the callback will in fact delete
        # the object. This would invariably lead to unpredictable outcome.
        GLib.idle_add(disconnected_cb, self)


# ******************************************************************************
class Service:  # pylint: disable=too-many-instance-attributes
    '''@brief Base class used to manage a STorage Appliance Service'''

    def __init__(self, reload_hdlr):
        self._lkc_file     = os.path.join(os.environ.get('RUNTIME_DIRECTORY', os.path.join('/run', defs.PROG_NAME)), 'last-known-config.pickle')
        self._loop         = GLib.MainLoop()
        self._cancellable  = Gio.Cancellable()
        self._resolver     = gutil.NameResolver()
        self._controllers  = self._load_last_known_config()
        self._dbus_iface   = None
        self._cfg_soak_tmr = None
        self._sysbus       = dasbus.connection.SystemMessageBus()

        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, self._stop_hdlr)  # CTRL-C
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self._stop_hdlr)  # systemctl stop stafd
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGHUP, reload_hdlr)  # systemctl reload stafd

        nvme_options = conf.NvmeOptions()
        if not nvme_options.host_iface_supp or not nvme_options.discovery_supp:
            log.LOG.warning(
                'Kernel does not appear to support all the options needed to run this program. Consider updating to a later kernel version.'
            )

    def _release_resources(self):
        log.LOG.debug('Service._release_resources()')

        if self._cancellable and not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        if self._cfg_soak_tmr is not None:
            self._cfg_soak_tmr.kill()

        self._controllers.clear()

        self._sysbus.disconnect()

        self._cfg_soak_tmr = None
        self._cancellable = None
        self._resolver = None
        self._lkc_file = None
        self._sysbus = None

    def _config_dbus(self, iface_obj, bus_name: str, obj_name: str):
        self._dbus_iface = iface_obj
        self._sysbus.publish_object(obj_name, iface_obj)
        self._sysbus.register_service(bus_name)

    def run(self):
        '''@brief Start the main loop execution'''
        try:
            self._loop.run()
        except Exception as ex:  # pylint: disable=broad-except
            log.LOG.critical('exception: %s', ex)

        self._loop = None

    def info(self) -> dict:
        '''@brief Get the status info for this object (used for debug)'''
        nvme_options = conf.NvmeOptions()
        return {
            'last known config file': self._lkc_file,
            'config soak timer': str(self._cfg_soak_tmr),
            'kernel support': {
                'TP8013': nvme_options.discovery_supp,
                'host_iface': nvme_options.host_iface_supp,
            },
            'system config': conf.SYSTEM.as_dict(),
        }

    def get_controllers(self):
        '''@brief return the list of controller objects'''
        return self._controllers.values()

    def get_controller(
        self, transport: str, traddr: str, trsvcid: str, host_traddr: str, host_iface: str, subsysnqn: str
    ):  # pylint: disable=too-many-arguments
        '''@brief get the specified controller object from the list of controllers'''
        cid = {
            'transport': transport,
            'traddr': traddr,
            'trsvcid': trsvcid,
            'host-traddr': host_traddr,
            'host-iface': host_iface,
            'subsysnqn': subsysnqn,
        }
        return self._controllers.get(trid.TID(cid))

    def _remove_ctrl_from_dict(self, controller):
        tid_to_pop = controller.tid
        if not tid_to_pop:
            # Being paranoid. This should not happen, but let's say the
            # controller object has been purged, but it is somehow still
            # listed in self._controllers.
            for tid, ctrl in self._controllers.items():
                if ctrl is controller:
                    tid_to_pop = tid
                    break

        if tid_to_pop:
            log.LOG.debug('Service._remove_ctrl_from_dict()   - %s | %s', tid_to_pop, controller.device)
            self._controllers.pop(tid_to_pop, None)
        else:
            log.LOG.debug('Service._remove_ctrl_from_dict()   - already removed')

    def remove_controller(self, controller):
        '''@brief remove the specified controller object from the list of controllers'''
        log.LOG.debug('Service.remove_controller()')
        if isinstance(controller, Controller):
            self._remove_ctrl_from_dict(controller)

            controller.kill()

        if self._cfg_soak_tmr:
            self._cfg_soak_tmr.start()

    def _cancel(self):
        log.LOG.debug('Service._cancel()')
        if not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        for controller in self._controllers.values():
            controller.cancel()

    def _keep_connections_on_exit(self):
        '''@brief Determine whether connections should remain when the
        process exits.

        NOTE) This is the base class method used to define the interface.
        It must be overloaded by a child class.
        '''
        raise NotImplementedError()

    def _stop_hdlr(self):
        systemd.daemon.notify('STOPPING=1')

        self._cancel()  # Cancel pending operations

        self._dump_last_known_config(self._controllers)

        if len(self._controllers) == 0:
            GLib.idle_add(self._exit)
        else:
            # Tell all controller objects to disconnect
            keep_connections = self._keep_connections_on_exit()
            controllers = self._controllers.values()
            for controller in controllers:
                controller.disconnect(self._on_final_disconnect, keep_connections)

        return GLib.SOURCE_REMOVE

    def _on_final_disconnect(self, controller):
        '''Callback invoked after a controller is disconnected.
        THIS IS USED DURING PROCESS SHUTDOWN TO WAIT FOR ALL CONTROLLERS TO BE
        DISCONNECTED BEFORE EXITING THE PROGRAM. ONLY CALL ON SHUTDOWN!
        '''
        log.LOG.debug('Service._on_final_disconnect()')
        self._remove_ctrl_from_dict(controller)

        controller.kill()

        # When all controllers have disconnected, we can finish the clean up
        if len(self._controllers) == 0:
            # Defer exit to the next main loop's idle period.
            GLib.idle_add(self._exit)

    def _exit(self):
        log.LOG.debug('Service._exit()')
        self._release_resources()
        self._loop.quit()

    def _on_config_ctrls(self, *_user_data):
        self._config_ctrls()
        return GLib.SOURCE_REMOVE

    def _config_ctrls(self):
        '''@brief Start controllers configuration.'''
        # The configuration file may contain controllers and/or blacklist
        # elements with traddr specified as hostname instead of IP address.
        # Because of this, we need to remove those blacklisted elements before
        # running name resolution. And we will need to remove blacklisted
        # elements after name resolution is complete (i.e. in the calback
        # function _config_ctrls_finish)
        log.LOG.debug('Service._config_ctrls()')
        configured_controllers = remove_blacklisted(conf.PROCESS.get_controllers())
        self._resolver.resolve_ctrl_async(self._cancellable, configured_controllers, self._config_ctrls_finish)

    def _config_ctrls_finish(self, configured_ctrl_list):
        '''@brief Finish controllers configuration after hostnames (if any)
        have been resolved.

        Configuring controllers must be done asynchronously in 2 steps.
        In the first step, host names get resolved to find their IP addresses.
        Name resolution can take a while, especially when an external name
        resolution server is used. Once that step completed, the callback
        method _config_ctrls_finish() (i.e. this method), gets invoked to
        complete the controller configuration.

        NOTE) This is the base class method used to define the interface.
        It must be overloaded by a child class.
        '''
        raise NotImplementedError()

    def _load_last_known_config(self):
        raise NotImplementedError()

    def _dump_last_known_config(self, controllers):
        raise NotImplementedError()


def clean():
    '''Module clean up function. Call on program exist.'''
    global UDEV  # pylint: disable=global-statement
    UDEV = None
