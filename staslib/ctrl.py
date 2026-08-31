# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''This module defines the base Controller object from which the
Dc (Discovery Controller) and Ioc (I/O Controller) objects are derived.'''

import time
import logging
from typing import Optional
from gi.repository import GLib
from libnvme3 import nvme
from staslib import conf, defs, gutil, trid, udev, stas


# Connection parameters, as (connectivity-configuration name, kernel name).
_CONN_PARAMS = (
    ('keep-alive-tmo', 'keep_alive_tmo'),
    ('tos', 'tos'),
    ('tls', 'tls'),
    ('concat', 'concat'),
    ('keyring', 'keyring'),
    ('tls-key', 'tls_key'),
    ('queue-size', 'queue_size'),
    ('hdr-digest', 'hdr_digest'),
    ('data-digest', 'data_digest'),
    ('nr-io-queues', 'nr_io_queues'),
    ('ctrl-loss-tmo', 'ctrl_loss_tmo'),
    ('disable-sqflow', 'disable_sqflow'),
    ('nr-poll-queues', 'nr_poll_queues'),
    ('nr-write-queues', 'nr_write_queues'),
    ('reconnect-delay', 'reconnect_delay'),
    ('tls-key-identity', 'tls_key_identity'),
    ('fast-io-fail-tmo', 'fast_io_fail_tmo'),
)


def host_identity(tid, sysconf):
    '''Return the (hostnqn, hostid, hostsymname) a connection is made under.

    A connection may name its own identity - that is what a [Host] section in
    the connectivity configuration is for. Take that identity whole or not at
    all: pairing a configured host NQN with the system's host ID invents an
    identity nobody configured, and the two are meant to travel together
    (TP4126). Pure function, so it is directly unit-testable.
    '''
    if tid.hostnqn and tid.hostnqn != sysconf.hostnqn:
        return tid.hostnqn, tid.cfg.get('hostid'), tid.cfg.get('hostsymname')

    return sysconf.hostnqn, sysconf.hostid, tid.cfg.get('hostsymname', sysconf.hostsymname)


DLP_CHANGED = (
    (nvme.NVME_LOG_LID_DISCOVERY << 16) | (nvme.NVME_AER_NOTICE_DISC_CHANGED << 8) | nvme.NVME_AER_NOTICE
)  # 0x70f002


def get_eflags(dlpe):
    '''Return the eflags field of a discovery log page entry.'''
    return int(dlpe.get('eflags', 0)) if dlpe else 0


def get_ncc(eflags: int):
    '''Return True if the Not Connected to CDC (NCC) bit is set in eflags.'''
    return eflags & nvme.NVMF_DISC_EFLAGS_NCC != 0


def dlp_supp_opts_as_string(dlp_supp_opts: int):
    '''Return a list of human-readable option names supported by the
    Get Discovery Log Page command.'''
    data = {
        nvme.NVMF_LOG_DISC_LID_EXTDLPES: "EXTDLPES",
        nvme.NVMF_LOG_DISC_LID_PLEOS: "PLEOS",
        nvme.NVMF_LOG_DISC_LID_ALLSUBES: "ALLSUBES",
    }
    return [txt for msk, txt in data.items() if dlp_supp_opts & msk]


# ******************************************************************************
class Controller(stas.ControllerABC):
    '''Base class for managing the connection to an NVMe controller.'''

    def __init__(self, tid: trid.TID, service, discovery_ctrl: bool = False):
        sysconf = conf.SysConf()
        self._nvme_options = conf.NvmeOptions()

        hostnqn, hostid, hostsymname = host_identity(tid, sysconf)

        self._ctx = nvme.GlobalCtx(owner=defs.REGISTRY_OWNER)
        self._ctx.hostnqn = hostnqn
        self._ctx.hostid = hostid
        self._host = nvme.Host(self._ctx, hostnqn=hostnqn, hostid=hostid, hostsymname=hostsymname)
        self._host.kxchap_host_key = sysconf.hostkey if self._nvme_options.kxchap_hostkey_supp else None
        self._udev = udev.UDEV
        self._device = None  # Refers to the nvme device (e.g. /dev/nvme[n])
        self._ctrl = None  # libnvme's nvme.Ctrl object
        self._connect_op = None

        super().__init__(tid, service, discovery_ctrl)

    def _release_resources(self):
        logging.debug('Controller._release_resources()    - %s | %s', self.id, self.device)

        if self._udev:
            self._udev.unregister_for_device_events(self._on_udev_notification)

        self._kill_ops()

        super()._release_resources()

        self._ctrl = None
        self._udev = None
        self._host = None
        self._ctx = None
        self._nvme_options = None

    @property
    def device(self) -> str:
        '''Return the Linux nvme device name (e.g. "nvme3"), or "nvme?" if
        no device is associated with this controller yet.'''
        if not self._device and self._ctrl and self._ctrl.name:
            self._device = self._ctrl.name

        return self._device or 'nvme?'

    def all_ops_completed(self) -> bool:
        '''Return True if all pending operations have completed.'''
        return self._connect_op is None or self._connect_op.completed()

    def connected(self):
        '''Return True if a connection to the controller is currently established.'''
        return self._ctrl and self._ctrl.connected

    def controller_id_dict(self) -> dict:
        '''Return the controller ID as a dict.'''
        cid = super().controller_id_dict()
        cid['device'] = self.device
        return cid

    def details(self) -> dict:
        '''Return detailed debug info about this controller.'''
        details = super().details()
        # Note that 'hostnqn' is deliberately not read from the sysfs here:
        # the TID already provides it, and the two are equal by construction
        # for a controller we manage (see Udev._cid_matches_tid()). Reading it
        # would only overwrite it with an empty string while disconnected.
        details.update(self._udev.get_attributes(self.device, ('hostid', 'model', 'serial', 'dctype', 'cntrltype')))
        details['connected'] = str(self.connected())
        return details

    def info(self) -> dict:
        '''Return status info for this controller.'''
        info = super().info()
        if self._connect_op:
            info['connect operation'] = str(self._connect_op.as_dict())
        return info

    def cancel(self):
        '''Cancel all pending operations.'''
        super().cancel()
        if self._connect_op:
            self._connect_op.cancel()

    def _kill_ops(self):
        if self._connect_op:
            self._connect_op.kill()
            self._connect_op = None

    def set_level_from_tron(self, tron):
        '''Set log level based on TRON'''
        if self._ctx:
            self._ctx.log_level("debug" if tron else "err")

    def _on_udev_notification(self, udev_obj):
        if not self._alive():
            logging.debug(
                'Controller._on_udev_notification() - %s | %s: Received event on dead object. udev_obj %s: %s',
                self.id,
                self.device,
                udev_obj.action,
                udev_obj.sys_name,
            )
            return

        if udev_obj.action == 'change':
            nvme_aen = udev_obj.get('NVME_AEN')
            nvme_event = udev_obj.get('NVME_EVENT')
            if isinstance(nvme_aen, str):
                logging.info('%s | %s - Received AEN: %s', self.id, udev_obj.sys_name, nvme_aen)
                self._on_aen(int(nvme_aen, 16))
            if isinstance(nvme_event, str):
                self._on_nvme_event(nvme_event)
        elif udev_obj.action == 'remove':
            logging.info('%s | %s - Received "remove" event', self.id, udev_obj.sys_name)
            self._on_ctrl_removed(udev_obj)
        else:
            logging.debug(
                'Controller._on_udev_notification() - %s | %s: Received "%s" event',
                self.id,
                udev_obj.sys_name,
                udev_obj.action,
            )

    def _on_ctrl_removed(self, udev_obj):
        if self._udev:
            self._udev.unregister_for_device_events(self._on_udev_notification)
        self._kill_ops()  # Kill all pending operations
        self._ctrl = None
        self._device = None
        self._connect_attempts = 0
        # Reset the retry interval to fast since this is effectively a fresh start
        self._retry_connect_tmr.start(self.FAST_CONNECT_RETRY_PERIOD_SEC)

    def _get_cfg(self):
        '''Get all parameters needed to create and connect an nvme.Ctrl object.
        Transport ID parameters are included directly. Fabrics config parameters
        may come from the [Global] section or from a "controller" entry in the
        configuration file; a "controller" entry overrides the [Global] section.
        '''
        service_conf = conf.SvcConf()
        cfg = {
            'subsysnqn': self.tid.subsysnqn,
            'transport': self.tid.transport,
            'traddr': self.tid.traddr,
        }
        if self.tid.trsvcid:
            cfg['trsvcid'] = self.tid.trsvcid
        if self.tid.host_traddr:
            cfg['host_traddr'] = self.tid.host_traddr
        if self.tid.host_iface and not service_conf.ignore_iface and self._nvme_options.host_iface_supp:
            cfg['host_iface'] = self.tid.host_iface

        # A configured controller arrives with its parameters already resolved
        # by libnvme. One we discovered is in no file, so it draws the defaults
        # for its class.
        defaults = conf.ConnConf().defaults(self._discovery_ctrl)
        for option, keyword in _CONN_PARAMS:
            value = self.tid.cfg.get(option, defaults.get(option))
            if value is not None:
                cfg[keyword] = value

        return cfg

    def _do_connect(self):
        cfg = self._get_cfg()
        try:
            self._ctrl = nvme.Ctrl(self._ctx, cfg)
        except ValueError as ex:
            # A configuration we cannot turn into a connection at all - an
            # incomplete host identity, most likely. Retrying changes nothing
            # until the configuration does, but the retry timer is how we find
            # out that it has.
            logging.error('%s - Cannot create controller: %s', self.id, ex)
            self._retry_connect_tmr.set_timeout(self.CONNECT_RETRY_PERIOD_SEC)
            self._retry_connect_tmr.start()
            return

        self._ctrl.discovery_ctrl = self._discovery_ctrl

        # Set the KXCHAP host key on the controller
        # NOTE that this may eventually have to
        # change once we have support for AVE (TP8019)
        # This is used for in-band authentication
        kxchap_host_key = self.tid.cfg.get('kxchap-secret')
        if kxchap_host_key and self._nvme_options.kxchap_hostkey_supp:
            self._ctrl.kxchap_host_key = kxchap_host_key

        # Set the KXCHAP controller key on the controller
        # NOTE that this may eventually have to
        # change once we have support for AVE (TP8019)
        # This is used for bidirectional authentication
        kxchap_ctrl_key = self.tid.cfg.get('kxchap-ctrl-secret')
        if kxchap_ctrl_key and self._nvme_options.kxchap_ctrlkey_supp:
            self._ctrl.kxchap_ctrl_key = kxchap_ctrl_key

        # Audit existing nvme devices. If we find a match, then
        # we'll just borrow that device instead of creating a new one.
        udev_obj = self._find_existing_connection()
        if udev_obj is not None:
            # A device already exists.
            self._device = udev_obj.sys_name
            logging.debug(
                'Controller._do_connect()           - %s Found existing control device: %s', self.id, udev_obj.sys_name
            )
            self._connect_op = gutil.AsyncTask(
                self._on_connect_success,
                self._on_connect_fail,
                self._ctrl.load_from_device,
                self._host,
                int(udev_obj.sys_number),
            )
        else:
            logging.debug(
                'Controller._do_connect()           - %s Connecting to nvme control with cfg=%s', self.id, cfg
            )
            self._connect_op = gutil.AsyncTask(
                self._on_connect_success, self._on_connect_fail, self._ctrl.connect, self._host
            )

        self._connect_op.run_async()

    # --------------------------------------------------------------------------
    def _on_connect_success(self, op_obj: gutil.AsyncTask, data):
        '''Called when the connection to the controller is established successfully.'''
        op_obj.kill()
        self._connect_op = None

        if not self._alive():
            logging.debug(
                'Controller._on_connect_success()   - %s | %s: Received event on dead object. data=%s',
                self.id,
                self.device,
                data,
            )
            return

        self._device = self._ctrl.name
        stas.claim(self.tid, self._device)
        logging.info('%s | %s - Connection established!', self.id, self.device)
        self._connect_attempts = 0
        self._udev.register_for_device_events(self._device, self._on_udev_notification)

    def _on_connect_fail(self, op_obj: gutil.AsyncTask, err, fail_cnt):
        '''Called when the connection attempt to the controller fails.'''
        op_obj.kill()
        self._connect_op = None

        if not self._alive():
            logging.debug(
                'Controller._on_connect_fail()      - %s Received event on dead object. %s %s',
                self.id,
                err.domain,
                err.message,
            )
            return

        if self._connect_attempts == 1:
            # Do a fast re-try on the first failure.
            self._retry_connect_tmr.set_timeout(self.FAST_CONNECT_RETRY_PERIOD_SEC)
        elif self._connect_attempts == 2:
            # If the fast connect re-try fails, then we can print a message to
            # indicate the failure, and start a slow re-try period.
            self._retry_connect_tmr.set_timeout(self.CONNECT_RETRY_PERIOD_SEC)
            logging.error('%s Failed to connect to controller. %s %s', self.id, err.domain, err.message)

        if self._should_try_to_reconnect():
            logging.debug(
                'Controller._on_connect_fail()      - %s %s. Retry in %s sec.',
                self.id,
                err,
                self._retry_connect_tmr.get_timeout(),
            )
            self._retry_connect_tmr.start()

    def disconnect(self, disconnected_cb, keep_connection):
        '''Initiate an asynchronous disconnect. Once complete, disconnected_cb
        is invoked. If already disconnected, the callback is scheduled on the
        next main loop idle slot.

        Callback signature: def disconnected_cb(controller: Controller, success: bool)

        If keep_connection is True, the kernel connection is preserved.'''
        logging.debug(
            'Controller.disconnect()            - %s | %s: keep_connection=%s', self.id, self.device, keep_connection
        )
        if self._ctrl and self._ctrl.connected and not keep_connection:
            logging.info('%s | %s - Disconnect initiated', self.id, self.device)
            op = gutil.AsyncTask(self._on_disconn_success, self._on_disconn_fail, self._ctrl.disconnect)
            op.run_async(disconnected_cb)
        else:
            # Defer callback to the next main loop's idle period. The callback
            # cannot be called directly as the current Controller object is in the
            # process of being disconnected and the callback will in fact delete
            # the object. This would invariably lead to unpredictable outcome.
            GLib.idle_add(disconnected_cb, self, True)

    def _on_disconn_success(self, op_obj: gutil.AsyncTask, data, disconnected_cb):
        logging.debug('Controller._on_disconn_success()   - %s | %s', self.id, self.device)
        op_obj.kill()
        # Defer callback to the next main loop's idle period. The callback
        # cannot be called directly as the current Controller object is in the
        # process of being disconnected and the callback will in fact delete
        # the object. This would invariably lead to unpredictable outcome.
        GLib.idle_add(disconnected_cb, self, True)

    def _on_disconn_fail(self, op_obj: gutil.AsyncTask, err, fail_cnt, disconnected_cb):
        logging.debug('Controller._on_disconn_fail()      - %s | %s: %s', self.id, self.device, err)
        op_obj.kill()
        # Defer callback to the next main loop's idle period. The callback
        # cannot be called directly as the current Controller object is in the
        # process of being disconnected and the callback will in fact delete
        # the object. This would invariably lead to unpredictable outcome.
        GLib.idle_add(disconnected_cb, self, False)


# ******************************************************************************
class Dc(Controller):
    '''Manages the connection to a single Discovery Controller (DC).
    Retrieves and caches discovery log pages, and reacts to udev events
    associated with the DC.'''

    GET_LOG_PAGE_RETRY_PERIOD_SEC = 20
    REGISTRATION_RETRY_PERIOD_SEC = 5
    GET_SUPPORTED_RETRY_PERIOD_SEC = 5

    def __init__(self, staf, tid: trid.TID, log_pages=None, origin=None):
        super().__init__(tid, staf, discovery_ctrl=True)
        self._register_op = None
        self._get_supported_op = None
        self._get_log_op = None
        self._origin = origin
        self._log_pages = log_pages if log_pages else list()  # Log pages cache

        # For Avahi-discovered DCs that later become unresponsive, monitor how
        # long the controller remains unresponsive and if it does not return for
        # a configurable soak period (_ctrl_unresponsive_tmr), remove that
        # controller. Only Avahi-discovered controllers need this timeout-based
        # cleanup.
        self._ctrl_unresponsive_time = None  # The time at which connectivity was lost
        self._ctrl_unresponsive_tmr = gutil.GTimer(0, self._serv.controller_unresponsive, self.tid)

    def _release_resources(self):
        logging.debug('Dc._release_resources()            - %s | %s', self.id, self.device)
        super()._release_resources()

        if self._ctrl_unresponsive_tmr is not None:
            self._ctrl_unresponsive_tmr.kill()

        self._log_pages = list()
        self._ctrl_unresponsive_tmr = None

    def _kill_ops(self):
        super()._kill_ops()
        if self._get_log_op:
            self._get_log_op.kill()
            self._get_log_op = None
        if self._register_op:
            self._register_op.kill()
            self._register_op = None
        if self._get_supported_op:
            self._get_supported_op.kill()
            self._get_supported_op = None

    def all_ops_completed(self) -> bool:
        '''Return True if all pending operations have completed.'''
        return (
            super().all_ops_completed()
            and (self._get_log_op is None or self._get_log_op.completed())
            and (self._register_op is None or self._register_op.completed())
            and (self._get_supported_op is None or self._get_supported_op.completed())
        )

    @property
    def origin(self):
        '''Return how this controller was discovered: "discovered" (mDNS/TP8009),
        "configured" (stafd.conf), or "referral".'''
        return self._origin

    @origin.setter
    def origin(self, value):
        '''Set the origin of this controller.'''
        if value in ('discovered', 'configured', 'referral'):
            self._origin = value
            self._handle_lost_controller()
        else:
            logging.error('%s | %s - Trying to set invalid origin to %s', self.id, self.device, value)

    def reload_hdlr(self):
        '''Called when a SIGHUP/reload signal is received.'''
        logging.debug('Dc.reload_hdlr()                   - %s | %s', self.id, self.device)

        self._handle_lost_controller()
        self._resync_with_controller()

    def info(self) -> dict:
        '''Return status info for this discovery controller.'''
        timeout = conf.SvcConf().zeroconf_persistence_sec
        unresponsive_time = (
            time.asctime(self._ctrl_unresponsive_time) if self._ctrl_unresponsive_time is not None else '---'
        )
        info = super().info()
        info['origin'] = self.origin
        if self.origin == 'discovered':
            # The code that handles "unresponsive" DCs only applies to
            # discovered DCs. So, let's only print that info when it's relevant.
            info['unresponsive timer'] = str(self._ctrl_unresponsive_tmr)
            info['unresponsive timeout'] = f'{timeout} sec' if timeout >= 0 else 'forever'
            info['unresponsive time'] = unresponsive_time
        if self._get_log_op:
            info['get log page operation'] = str(self._get_log_op.as_dict())
        if self._register_op:
            info['register operation'] = str(self._register_op.as_dict())
        if self._get_supported_op:
            info['get supported log page operation'] = str(self._get_supported_op.as_dict())
        return info

    def cancel(self):
        '''Cancel all pending operations.'''
        super().cancel()
        if self._get_log_op:
            self._get_log_op.cancel()
        if self._register_op:
            self._register_op.cancel()
        if self._get_supported_op:
            self._get_supported_op.cancel()

    def log_pages(self) -> list:
        '''Return the cached discovery log pages.'''
        return self._log_pages

    def referrals(self) -> list:
        '''Return the list of referral entries from the cached log pages.'''
        return [page for page in self._log_pages if page['subtype'] == 'referral']

    def _is_ddc(self):
        return self._ctrl and self._ctrl.dctype != 'cdc'

    def _on_aen(self, aen: int):
        if aen == DLP_CHANGED and self._get_log_op:
            self._get_log_op.run_async()

    def _handle_lost_controller(self):
        if self.origin == 'discovered':  # Only apply to mDNS-discovered DCs
            if not self._serv.is_avahi_reported(self.tid) and not self.connected():
                timeout = conf.SvcConf().zeroconf_persistence_sec
                if timeout >= 0:
                    if self._ctrl_unresponsive_time is None:
                        self._ctrl_unresponsive_time = time.localtime()
                        self._ctrl_unresponsive_tmr.start(timeout)
                        logging.info(
                            '%s | %s - Controller is not responding. Will be removed by %s unless restored',
                            self.id,
                            self.device,
                            time.ctime(time.mktime(self._ctrl_unresponsive_time) + timeout),
                        )

                    return

                logging.info('%s | %s - Controller not responding. Retrying...', self.id, self.device)

        self._ctrl_unresponsive_time = None
        self._ctrl_unresponsive_tmr.stop()
        self._ctrl_unresponsive_tmr.set_timeout(0)

    def is_unresponsive(self):
        '''Return True if this discovered DC has been unresponsive long enough
        to be considered for removal.'''
        return (
            self.origin == 'discovered'
            and not self._serv.is_avahi_reported(self.tid)
            and not self.connected()
            and self._ctrl_unresponsive_time is not None
            and self._ctrl_unresponsive_tmr.time_remaining() <= 0
        )

    def _resync_with_controller(self):
        '''Communicate with DC to resync the states'''
        if self._register_op:
            self._register_op.run_async()
        elif self._get_supported_op:
            self._get_supported_op.run_async()
        elif self._get_log_op:
            self._get_log_op.run_async()

    def _on_nvme_event(self, nvme_event: str):
        if nvme_event in ('connected', 'rediscover'):
            # This event indicates that the kernel
            # driver re-connected to the DC.
            logging.debug(
                'Dc._on_nvme_event()                - %s | %s: Received "%s" event',
                self.id,
                self.device,
                nvme_event,
            )
            self._resync_with_controller()

    def _find_existing_connection(self):
        return self._udev.find_nvme_dc_device(self.tid)

    def _post_registration_actions(self):
        if conf.SvcConf().pleo_enabled and self._is_ddc():
            self._get_supported_op = gutil.AsyncTask(
                self._on_get_supported_success, self._on_get_supported_fail, self._ctrl.get_supported_log_pages
            )
            self._get_supported_op.run_async()
        else:
            self._get_log_op = gutil.AsyncTask(self._on_get_log_success, self._on_get_log_fail, self._ctrl.discover)
            self._get_log_op.run_async()

    # --------------------------------------------------------------------------
    def _on_connect_success(self, op_obj: gutil.AsyncTask, data):
        '''Called when the connection to the Discovery Controller is established.'''
        super()._on_connect_success(op_obj, data)

        if not self._alive():
            return

        self._ctrl_unresponsive_time = None
        self._ctrl_unresponsive_tmr.stop()
        self._ctrl_unresponsive_tmr.set_timeout(0)

        if self._ctrl.registration_supported:
            self._register_op = gutil.AsyncTask(
                self._on_registration_success,
                self._on_registration_fail,
                self._ctrl.registration_ctlr,
                nvme.NVMF_DIM_TAS_REGISTER,
            )
            self._register_op.run_async()
        else:
            self._post_registration_actions()

    def _on_connect_fail(self, op_obj: gutil.AsyncTask, err, fail_cnt):
        '''Called when the connection attempt to the Discovery Controller fails.'''
        super()._on_connect_fail(op_obj, err, fail_cnt)

        if self._alive():
            self._handle_lost_controller()

    # --------------------------------------------------------------------------
    def _on_registration_success(self, op_obj: gutil.AsyncTask, data):
        '''Called when the registration exchange with the DC completes.

        Note: "success" here means the exchange completed, not that the
        registration was accepted. Check data for any error returned by the DC.'''
        if not self._alive():
            logging.debug(
                'Dc._on_registration_success()      - %s | %s: Received event on dead object.', self.id, self.device
            )
            return

        if data is not None:
            logging.warning('%s | %s - Registration error. %s.', self.id, self.device, data)
        else:
            logging.debug('Dc._on_registration_success()      - %s | %s', self.id, self.device)

        self._post_registration_actions()

    def _on_registration_fail(self, op_obj: gutil.AsyncTask, err, fail_cnt):
        '''Called when the registration exchange with the DC fails (transport error).'''
        if not self._alive():
            logging.debug(
                'Dc._on_registration_fail()         - %s | %s: Received event on dead object. %s',
                self.id,
                self.device,
                err,
            )
            op_obj.kill()
            return

        logging.debug(
            'Dc._on_registration_fail()         - %s | %s: %s. Retry in %s sec',
            self.id,
            self.device,
            err,
            Dc.REGISTRATION_RETRY_PERIOD_SEC,
        )
        if fail_cnt == 1:  # Throttle the logs. Only print the first time the command fails
            logging.error('%s | %s - Failed to register with Discovery Controller. %s', self.id, self.device, err)
        op_obj.retry(Dc.REGISTRATION_RETRY_PERIOD_SEC)

    # --------------------------------------------------------------------------
    def _on_get_supported_success(self, op_obj: gutil.AsyncTask, data: Optional[list]):
        '''Called when the Get Supported Log Pages exchange with the DC completes.

        Note: "success" means the exchange completed, not that the operation
        returned valid data.'''
        if not self._alive():
            logging.debug(
                'Dc._on_get_supported_success()     - %s | %s: Received event on dead object.', self.id, self.device
            )
            return

        try:
            dlp_supp_opts = data[nvme.NVME_LOG_LID_DISCOVERY] >> 16
        except (TypeError, IndexError):
            dlp_supp_opts = 0

        logging.debug(
            'Dc._on_get_supported_success()     - %s | %s: supported options = 0x%04X = %s',
            self.id,
            self.device,
            dlp_supp_opts,
            dlp_supp_opts_as_string(dlp_supp_opts),
        )

        lsp = nvme.NVMF_LOG_DISC_LSP_PLEO if dlp_supp_opts & nvme.NVMF_LOG_DISC_LID_PLEOS else 0
        self._get_log_op = gutil.AsyncTask(self._on_get_log_success, self._on_get_log_fail, self._ctrl.discover, lsp)
        self._get_log_op.run_async()

    def _on_get_supported_fail(self, op_obj: gutil.AsyncTask, err, fail_cnt):
        '''Called when the Get Supported Log Pages exchange with the DC fails.'''
        if not self._alive():
            logging.debug(
                'Dc._on_get_supported_fail()        - %s | %s: Received event on dead object. %s',
                self.id,
                self.device,
                err,
            )
            op_obj.kill()
            return

        logging.debug(
            'Dc._on_get_supported_fail()        - %s | %s: %s. Retry in %s sec',
            self.id,
            self.device,
            err,
            Dc.GET_SUPPORTED_RETRY_PERIOD_SEC,
        )
        if fail_cnt == 1:  # Throttle the logs. Only print the first time the command fails
            logging.error(
                '%s | %s - Failed to Get supported log pages from Discovery Controller. %s',
                self.id,
                self.device,
                err,
            )
        op_obj.retry(Dc.GET_SUPPORTED_RETRY_PERIOD_SEC)

    # --------------------------------------------------------------------------
    def _on_get_log_success(self, op_obj: gutil.AsyncTask, data):
        '''Called when discovery log pages are successfully retrieved from the DC.'''
        if not self._alive():
            logging.debug(
                'Dc._on_get_log_success()           - %s | %s: Received event on dead object.', self.id, self.device
            )
            return

        # Note that for historical reasons too long to explain, the CDC may
        # return invalid addresses ('0.0.0.0', '::', or ''). Those need to
        # be filtered out.
        referrals_before = self.referrals()
        self._log_pages = (
            [
                {k.strip(): str(v).strip() for k, v in dictionary.items()}
                for dictionary in data
                if dictionary.get('traddr', '').strip() not in ('0.0.0.0', '::', '')
            ]
            if data
            else list()
        )
        logging.info(
            '%s | %s - Received discovery log pages (num records=%s).', self.id, self.device, len(self._log_pages)
        )
        referrals_after = self.referrals()
        self._serv.log_pages_changed(self, self.device)
        if referrals_after != referrals_before:
            logging.debug(
                'Dc._on_get_log_success()           - %s | %s: Referrals before = %s',
                self.id,
                self.device,
                referrals_before,
            )
            logging.debug(
                'Dc._on_get_log_success()           - %s | %s: Referrals after  = %s',
                self.id,
                self.device,
                referrals_after,
            )
            self._serv.referrals_changed()

    def _on_get_log_fail(self, op_obj: gutil.AsyncTask, err, fail_cnt):
        '''Called when the discovery log page retrieval from the DC fails.'''
        if not self._alive():
            logging.debug(
                'Dc._on_get_log_fail()              - %s | %s: Received event on dead object. %s',
                self.id,
                self.device,
                err,
            )
            op_obj.kill()
            return

        logging.debug(
            'Dc._on_get_log_fail()              - %s | %s: %s. Retry in %s sec',
            self.id,
            self.device,
            err,
            Dc.GET_LOG_PAGE_RETRY_PERIOD_SEC,
        )
        if fail_cnt == 1:  # Throttle the logs. Only print the first time the command fails
            logging.error('%s | %s - Failed to retrieve log pages. %s', self.id, self.device, err)
        op_obj.retry(Dc.GET_LOG_PAGE_RETRY_PERIOD_SEC)


# ******************************************************************************
class Ioc(Controller):
    '''Manages the connection to a single I/O Controller.'''

    def __init__(self, stac, tid: trid.TID):
        self._dlpe = None
        super().__init__(tid, stac)

    def _find_existing_connection(self):
        return self._udev.find_nvme_ioc_device(self.tid)

    def _on_aen(self, aen: int):
        pass  # Not applicable for I/O controllers

    def _on_nvme_event(self, nvme_event):
        pass  # Not applicable for I/O controllers

    def reload_hdlr(self):
        '''Called when a SIGHUP/reload signal is received.'''
        if not self.connected() and self._retry_connect_tmr.time_remaining() == 0:
            self._try_to_connect_deferred.schedule()

    @property
    def eflags(self):
        '''Return the eflags field of the associated Discovery Log Page Entry.'''
        return get_eflags(self._dlpe)

    @property
    def ncc(self):
        '''Return True if the Not Connected to CDC (NCC) flag is set.'''
        return get_ncc(self.eflags)

    def details(self) -> dict:
        '''Return detailed debug info about this I/O controller.'''
        details = super().details()
        details['dlpe'] = str(self._dlpe)
        details['dlpe.eflags.ncc'] = str(self.ncc)
        return details

    def update_dlpe(self, dlpe):
        '''Update the Discovery Log Page Entry (DLPE) for this controller.
        If the NCC bit was previously set and has now been cleared, a connection
        attempt is immediately scheduled.'''
        new_ncc = get_ncc(get_eflags(dlpe))
        old_ncc = self.ncc
        self._dlpe = dlpe

        if old_ncc and not new_ncc:  # NCC bit cleared?
            if not self.connected():
                self._connect_attempts = 0
                self._try_to_connect_deferred.schedule()

    def _should_try_to_reconnect(self):
        '''Return True if another connection attempt should be made.'''
        max_connect_attempts = conf.SvcConf().connect_attempts_on_ncc if self.ncc else 0
        return max_connect_attempts == 0 or self._connect_attempts < max_connect_attempts
