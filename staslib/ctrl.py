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
from gi.repository import GLib
from libnvme import nvme
from staslib import conf, gutil, trid, udev, stas


DC_KATO_DEFAULT = 30  # seconds


# ******************************************************************************
class Controller(stas.ControllerABC):
    '''@brief Base class used to manage the connection to a controller.'''

    def __init__(self, root, host, tid: trid.TID, discovery_ctrl=False):
        self._udev       = udev.UDEV
        self._device     = None  # Refers to the nvme device (e.g. /dev/nvme[n])
        self._ctrl       = None  # libnvme's nvme.ctrl object
        self._connect_op = None

        super().__init__(root, host, tid, discovery_ctrl)

    def _release_resources(self):
        logging.debug('Controller._release_resources()    - %s', self.id)

        if self._udev:
            self._udev.unregister_for_device_events(self._on_udev_notification)

        self._kill_ops()

        super()._release_resources()

        self._ctrl = None
        self._udev = None

    @property
    def device(self) -> str:
        '''@brief return the Linux nvme device id (e.g. nvme3) or empty
        string if no device is associated with this controller'''
        if not self._device and self._ctrl and self._ctrl.name:
            self._device = self._ctrl.name

        return self._device or 'nvme?'

    def controller_id_dict(self) -> dict:
        '''@brief return the controller ID as a dict.'''
        cid = super().controller_id_dict()
        cid['device'] = self.device
        return cid

    def details(self) -> dict:
        '''@brief return detailed debug info about this controller'''
        details = super().details()
        details.update(
            self._udev.get_attributes(self.device,
                                      ('hostid', 'hostnqn', 'model',
                                       'serial', 'dctype', 'cntrltype'))
        )
        return details

    def info(self) -> dict:
        '''@brief Get the controller info for this object'''
        info = super().info()
        if self._connect_op:
            info['connect operation'] = self._connect_op.as_dict()
        return info

    def cancel(self):
        '''@brief Used to cancel pending operations.'''
        super().cancel()
        if self._connect_op:
            self._connect_op.cancel()

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
                self._on_ctrl_removed(udev_obj)
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

    def _on_ctrl_removed(self, obj):  # pylint: disable=unused-argument
        self._udev.unregister_for_device_events(self._on_udev_notification)
        self._kill_ops()  # Kill all pending operations
        self._ctrl = None

    def _do_connect(self):
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
            self._device = self._ctrl.name
            logging.info('%s | %s - Connection established!', self.id, self.device)
            self._connect_attempts = 0
            self._udev.register_for_device_events(self._device, self._on_udev_notification)
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
                self._retry_connect_tmr.set_timeout(self.FAST_CONNECT_RETRY_PERIOD_SEC)
            elif self._connect_attempts == 2:
                # If the fast connect re-try fails, then we can print a message to
                # indicate the failure, and start a slow re-try period.
                self._retry_connect_tmr.set_timeout(self.CONNECT_RETRY_PERIOD_SEC)
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
            GLib.idle_add(disconnected_cb, self, True)

    def _on_disconn_success(self, op_obj, data, disconnected_cb):  # pylint: disable=unused-argument
        logging.debug('Controller._on_disconn_success()   - %s | %s', self.id, self.device)
        op_obj.kill()
        # Defer callback to the next main loop's idle period. The callback
        # cannot be called directly as the current Controller object is in the
        # process of being disconnected and the callback will in fact delete
        # the object. This would invariably lead to unpredictable outcome.
        GLib.idle_add(disconnected_cb, self, True)

    def _on_disconn_fail(self, op_obj, err, fail_cnt, disconnected_cb):  # pylint: disable=unused-argument
        logging.debug('Controller._on_disconn_fail()      - %s | %s: %s', self.id, self.device, err)
        op_obj.kill()
        # Defer callback to the next main loop's idle period. The callback
        # cannot be called directly as the current Controller object is in the
        # process of being disconnected and the callback will in fact delete
        # the object. This would invariably lead to unpredictable outcome.
        GLib.idle_add(disconnected_cb, self, False)


# ******************************************************************************
class Dc(Controller):
    '''@brief This object establishes a connection to one Discover Controller (DC).
    It retrieves the discovery log pages and caches them.
    It also monitors udev events associated with that DC and updates
    the cached discovery log pages accordingly.
    '''

    DLP_CHANGED = (
        (nvme.NVME_LOG_LID_DISCOVER << 16) | (nvme.NVME_AER_NOTICE_DISC_CHANGED << 8) | nvme.NVME_AER_NOTICE
    )  # 0x70f002
    GET_LOG_PAGE_RETRY_RERIOD_SEC = 20
    REGISTRATION_RETRY_RERIOD_SEC = 10

    def __init__(self, staf, root, host, tid: trid.TID, log_pages=None):  # pylint: disable=too-many-arguments
        super().__init__(root, host, tid, discovery_ctrl=True)
        self._staf = staf
        self._register_op = None
        self._get_log_op = None
        self._log_pages = log_pages if log_pages else list()  # Log pages cache

    def _release_resources(self):
        logging.debug('Dc._release_resources()            - %s | %s', self.id, self.device)
        super()._release_resources()
        self._log_pages = list()
        self._staf = None

    def _kill_ops(self):
        super()._kill_ops()
        if self._get_log_op:
            self._get_log_op.kill()
            self._get_log_op = None
        if self._register_op:
            self._register_op.kill()
            self._register_op = None

    def info(self) -> dict:
        '''@brief Get the controller info for this object'''
        info = super().info()
        if self._get_log_op:
            info['get log page operation'] = self._get_log_op.as_dict()
        if self._register_op:
            info['register operation'] = self._register_op.as_dict()
        return info

    def cancel(self):
        '''@brief Used to cancel pending operations.'''
        super().cancel()
        if self._get_log_op:
            self._get_log_op.cancel()
        if self._register_op:
            self._register_op.cancel()

    def log_pages(self) -> list:
        '''@brief Get the cached log pages for this object'''
        return self._log_pages

    def referrals(self) -> list:
        '''@brief Return the list of referrals'''
        return [page for page in self._log_pages if page['subtype'] == 'referral']

    def _on_aen(self, aen: int):
        if aen == self.DLP_CHANGED and self._get_log_op:
            self._get_log_op.run_async()

    def _on_nvme_event(self, nvme_event: str):
        if nvme_event == 'connected' and self._register_op:
            self._register_op.run_async()

    def _on_ctrl_removed(self, obj):
        super()._on_ctrl_removed(obj)
        if self._try_to_connect_deferred:
            self._try_to_connect_deferred.schedule()

    def _find_existing_connection(self):
        return self._udev.find_nvme_dc_device(self.tid)

    # --------------------------------------------------------------------------
    def _on_connect_success(self, op_obj, data):
        '''@brief Function called when we successfully connect to the
        Discovery Controller.
        '''
        super()._on_connect_success(op_obj, data)

        if self._alive():
            if self._ctrl.is_registration_supported():
                self._register_op = gutil.AsyncOperationWithRetry(
                    self._on_registration_success,
                    self._on_registration_fail,
                    self._ctrl.registration_ctlr,
                    nvme.NVMF_DIM_TAS_REGISTER,
                )
                self._register_op.run_async()
            else:
                self._get_log_op = gutil.AsyncOperationWithRetry(
                    self._on_get_log_success, self._on_get_log_fail, self._ctrl.discover
                )
                self._get_log_op.run_async()

    # --------------------------------------------------------------------------
    def _on_registration_success(self, op_obj, data):  # pylint: disable=unused-argument
        '''@brief Function called when we successfully register with the
        Discovery Controller. See self._register_op object
        for details.
        '''
        if self._alive():
            if data is not None:
                logging.warning('%s | %s - Registration error. %s.', self.id, self.device, data)
            else:
                logging.debug('Dc._on_registration_success()      - %s | %s', self.id, self.device)
            self._get_log_op = gutil.AsyncOperationWithRetry(
                self._on_get_log_success, self._on_get_log_fail, self._ctrl.discover
            )
            self._get_log_op.run_async()
        else:
            logging.debug(
                'Dc._on_registration_success()      - %s | %s Received event on dead object.', self.id, self.device
            )

    def _on_registration_fail(self, op_obj, err, fail_cnt):
        '''@brief Function called when we fail to register with the
        Discovery Controller. See self._register_op object
        for details.
        '''
        if self._alive():
            logging.debug(
                'Dc._on_registration_fail()         - %s | %s: %s. Retry in %s sec',
                self.id,
                self.device,
                err,
                Dc.REGISTRATION_RETRY_RERIOD_SEC,
            )
            if fail_cnt == 1:  # Throttle the logs. Only print the first time we fail to connect
                logging.error('%s | %s - Failed to register with Discovery Controller. %s', self.id, self.device, err)
            # op_obj.retry(Dc.REGISTRATION_RETRY_RERIOD_SEC)
        else:
            logging.debug(
                'Dc._on_registration_fail()         - %s | %s Received event on dead object. %s',
                self.id,
                self.device,
                err,
            )
            op_obj.kill()

    # --------------------------------------------------------------------------
    def _on_get_log_success(self, op_obj, data):  # pylint: disable=unused-argument
        '''@brief Function called when we successfully retrieve the log pages
        from the Discovery Controller. See self._get_log_op object
        for details.
        '''
        if self._alive():
            # Note that for historical reasons too long to explain, the CDC may
            # return invalid addresses ("0.0.0.0", "::", or ""). Those need to be
            # filtered out.
            referrals_before = self.referrals()
            self._log_pages = (
                [
                    {k.strip(): str(v).strip() for k, v in dictionary.items()}
                    for dictionary in data
                    if dictionary.get('traddr','').strip() not in ('0.0.0.0', '::', '')
                ]
                if data
                else list()
            )
            logging.info(
                '%s | %s - Received discovery log pages (num records=%s).', self.id, self.device, len(self._log_pages)
            )
            referrals_after = self.referrals()
            self._staf.log_pages_changed(self, self.device)
            if referrals_after != referrals_before:
                logging.debug(
                    'Dc._on_get_log_success()           - %s | %s Referrals before = %s',
                    self.id,
                    self.device,
                    referrals_before,
                )
                logging.debug(
                    'Dc._on_get_log_success()           - %s | %s Referrals after  = %s',
                    self.id,
                    self.device,
                    referrals_after,
                )
                self._staf.referrals_changed()
        else:
            logging.debug(
                'Dc._on_get_log_success()           - %s | %s Received event on dead object.', self.id, self.device
            )

    def _on_get_log_fail(self, op_obj, err, fail_cnt):
        '''@brief Function called when we fail to retrieve the log pages
        from the Discovery Controller. See self._get_log_op object
        for details.
        '''
        if self._alive():
            logging.debug(
                'Dc._on_get_log_fail()              - %s | %s: %s. Retry in %s sec',
                self.id,
                self.device,
                err,
                Dc.GET_LOG_PAGE_RETRY_RERIOD_SEC,
            )
            if fail_cnt == 1:  # Throttle the logs. Only print the first time we fail to connect
                logging.error('%s | %s - Failed to retrieve log pages. %s', self.id, self.device, err)
            op_obj.retry(Dc.GET_LOG_PAGE_RETRY_RERIOD_SEC)
        else:
            logging.debug(
                'Dc._on_get_log_fail()              - %s | %s Received event on dead object. %s',
                self.id,
                self.device,
                err,
            )
            op_obj.kill()


# ******************************************************************************
class Ioc(Controller):
    '''@brief This object establishes a connection to one I/O Controller.'''

    def __init__(self, stac, root, host, tid: trid.TID):
        self._stac = stac
        super().__init__(root, host, tid)

    def _release_resources(self):
        super()._release_resources()
        self._stac = None

    def _on_ctrl_removed(self, obj):
        '''Called when the associated nvme device (/dev/nvmeX) is removed
        from the system.
        '''
        super()._on_ctrl_removed(obj)

        # Defer removal of this object to the next main loop's idle period.
        GLib.idle_add(self._stac.remove_controller, self, True)

    def _find_existing_connection(self):
        return self._udev.find_nvme_ioc_device(self.tid)

    def _on_aen(self, aen: int):
        pass

    def _on_nvme_event(self, nvme_event):
        pass
