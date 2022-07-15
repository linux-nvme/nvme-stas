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

import logging
from gi.repository import Gio, GLib
from libnvme import nvme
from staslib import conf, gutil, trid, udev


DC_KATO_DEFAULT = 30  # seconds


# ******************************************************************************
class Controller:  # pylint: disable=too-many-instance-attributes
    '''@brief Base class used to manage the connection to a controller.'''

    CONNECT_RETRY_PERIOD_SEC = 60
    FAST_CONNECT_RETRY_PERIOD_SEC = 3

    def __init__(self, root, host, tid: trid.TID, discovery_ctrl=False):
        self._root              = root
        self._host              = host
        self._udev              = udev.UDEV
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
        logging.debug('Controller._release_resources()    - %s', self.id)

        # Remove pending deferred from main loop
        if self._try_to_connect_deferred:
            self._try_to_connect_deferred.cancel()
        self._try_to_connect_deferred = None

        if self._udev:
            self._udev.unregister_for_device_events(self._on_udev_notification)

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
        self._udev = None

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
                    logging.info('%s | %s - Received AEN: %s', self.id, udev_obj.sys_name, nvme_aen)
                    self._on_aen(int(nvme_aen, 16))
                if isinstance(nvme_event, str):
                    self._on_nvme_event(nvme_event)
            elif udev_obj.action == 'remove':
                logging.info('%s | %s - Received "remove" event', self.id, udev_obj.sys_name)
                self._on_udev_remove(udev_obj)
            else:
                logging.debug(
                    'Controller._on_udev_notification() - %s | %s - Received "%s" notification.',
                    self.id,
                    udev_obj.sys_name,
                    udev_obj.action,
                )
        else:
            logging.debug(
                'Controller._on_udev_notification() - %s | %s - Received event on dead object. udev_obj %s: %s',
                self.id,
                self.device,
                udev_obj.action,
                udev_obj.sys_name,
            )

    def _on_aen(self, aen: int):
        pass

    def _on_nvme_event(self, nvme_event):
        pass

    def _on_udev_remove(self, udev_obj):  # pylint: disable=unused-argument
        self._udev.unregister_for_device_events(self._on_udev_notification)
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
            if (self.tid.host_iface and not conf.SvcConf().ignore_iface and conf.NvmeOptions().host_iface_supp)
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
            logging.debug(
                'Controller._try_to_connect()       - %s Found existing control device: %s', self.id, udev_obj.sys_name
            )
            self._connect_op = gutil.AsyncOperationWithRetry(
                self._on_connect_success, self._on_connect_fail, self._ctrl.init, self._host, int(udev_obj.sys_number)
            )
        else:
            self._device = None
            service_conf = conf.SvcConf()
            cfg = { 'hdr_digest':  service_conf.hdr_digest,
                    'data_digest': service_conf.data_digest }
            if service_conf.kato is not None:
                cfg['keep_alive_tmo'] = service_conf.kato
            elif self._discovery_ctrl:
                # All the connections to Controllers (I/O and Discovery) are
                # persistent. Persistent connections MUST configure the KATO.
                # The kernel already assigns a default 2-minute KATO to I/O
                # controller connections, but it doesn't assign one to
                # Discovery controller (DC) connections. Here we set the default
                # DC connection KATO to match the default set by nvme-cli on
                # persistent DC connections (i.e. 30 sec).
                cfg['keep_alive_tmo'] = DC_KATO_DEFAULT

            logging.debug(
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
            logging.info('%s | %s - Connection established!', self.id, self.device)
            self._connect_attempts = 0
            self._udev.register_for_device_events(self.device, self._on_udev_notification)
        else:
            logging.debug(
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
                logging.error('%s Failed to connect to controller. %s', self.id, getattr(err, 'message', err))

            logging.debug(
                'Controller._on_connect_fail()      - %s %s. Retry in %s sec.',
                self.id,
                err,
                self._retry_connect_tmr.get_timeout(),
            )
            self._retry_connect_tmr.start()
        else:
            logging.debug(
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
        details.update(self._udev.get_attributes(self.device, ('hostid', 'hostnqn', 'model', 'serial')))
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
            logging.debug('Controller.cancel()                - %s', self.id)
            self._cancellable.cancel()

        if self._connect_op:
            self._connect_op.cancel()

    def kill(self):
        '''@brief Used to release all resources associated with this object.'''
        logging.debug('Controller.kill()                  - %s', self.id)
        self._release_resources()

    def disconnect(self, disconnected_cb, keep_connection):
        '''@brief Issue an asynchronous disconnect command to a Controller.
        Once the async command has completed, the callback 'disconnected_cb'
        will be invoked. If a controller is already disconnected, then the
        callback will be added to the main loop's next idle slot to be executed
        ASAP.
        '''
        logging.debug('Controller.disconnect()            - %s | %s', self.id, self.device)
        self._kill_ops()
        if self._ctrl and self._ctrl.connected() and not keep_connection:
            logging.info('%s | %s - Disconnect initiated', self.id, self.device)
            op = gutil.AsyncOperationWithRetry(self._on_disconn_success, self._on_disconn_fail, self._ctrl.disconnect)
            op.run_async(disconnected_cb)
        else:
            # Defer callback to the next main loop's idle period. The callback
            # cannot be called directly as the current Controller object is in the
            # process of being disconnected and the callback will in fact delete
            # the object. This would invariably lead to unpredictable outcome.
            GLib.idle_add(disconnected_cb, self)

    def _on_disconn_success(self, op_obj, data, disconnected_cb):  # pylint: disable=unused-argument
        logging.debug('Controller._on_disconn_success()   - %s | %s', self.id, self.device)
        op_obj.kill()
        # Defer callback to the next main loop's idle period. The callback
        # cannot be called directly as the current Controller object is in the
        # process of being disconnected and the callback will in fact delete
        # the object. This would invariably lead to unpredictable outcome.
        GLib.idle_add(disconnected_cb, self)

    def _on_disconn_fail(self, op_obj, err, fail_cnt, disconnected_cb):  # pylint: disable=unused-argument
        logging.debug('Controller._on_disconn_fail()      - %s | %s: %s', self.id, self.device, err)
        op_obj.kill()
        # Defer callback to the next main loop's idle period. The callback
        # cannot be called directly as the current Controller object is in the
        # process of being disconnected and the callback will in fact delete
        # the object. This would invariably lead to unpredictable outcome.
        GLib.idle_add(disconnected_cb, self)
