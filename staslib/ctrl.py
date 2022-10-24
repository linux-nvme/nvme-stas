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

import inspect
import logging
import libnvme
from gi.repository import GLib
from libnvme import nvme
from staslib import conf, gutil, trid, udev, stas


DC_KATO_DEFAULT = 30  # seconds


def get_eflags(dlpe):
    '''@brief Return eflags field of dlpe'''
    return int(dlpe.get('eflags', 0)) if dlpe else 0


def get_ncc(eflags: int):
    '''@brief Return True if Not Connected to CDC bit is asserted, False otherwise'''
    return eflags & nvme.NVMF_DISC_EFLAGS_NCC != 0


def dlp_supp_opts_as_string(dlp_supp_opts: int):
    '''@brief Return the list of options supported by the Get
    discovery log page command.
    '''
    data = {
        nvme.NVMF_LOG_DISC_LID_EXTDLPES: "EXTDLPES",
        nvme.NVMF_LOG_DISC_LID_PLEOS: "PLEOS",
        nvme.NVMF_LOG_DISC_LID_ALLSUBES: "ALLSUBES",
    }
    return [txt for msk, txt in data.items() if dlp_supp_opts & msk]


# ******************************************************************************
class Controller(stas.ControllerABC):
    '''@brief Base class used to manage the connection to a controller.'''

    def __init__(self, root, host, tid: trid.TID, discovery_ctrl=False):
        self._udev = udev.UDEV
        self._device = None  # Refers to the nvme device (e.g. /dev/nvme[n])
        self._ctrl = None  # libnvme's nvme.ctrl object
        self._connect_op = None

        super().__init__(root, host, tid, discovery_ctrl)

    def _release_resources(self):
        logging.debug('Controller._release_resources()    - %s | %s', self.id, self.device)

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

    def connected(self):
        '''@brief Return whether a connection is established'''
        return self._ctrl and self._ctrl.connected()

    def controller_id_dict(self) -> dict:
        '''@brief return the controller ID as a dict.'''
        cid = super().controller_id_dict()
        cid['device'] = self.device
        return cid

    def details(self) -> dict:
        '''@brief return detailed debug info about this controller'''
        details = super().details()
        details.update(
            self._udev.get_attributes(self.device, ('hostid', 'hostnqn', 'model', 'serial', 'dctype', 'cntrltype'))
        )
        details['connected'] = str(self.connected())
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
                    'Controller._on_udev_notification() - %s | %s - Received "%s" event',
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
        if self._udev:
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
            cfg = {'hdr_digest': service_conf.hdr_digest, 'data_digest': service_conf.data_digest}
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
                logging.error('%s Failed to connect to controller. %s %s', self.id, err.domain, err.message)

            if self._should_try_to_reconnect():
                logging.debug(
                    'Controller._on_connect_fail()      - %s %s. Retry in %s sec.',
                    self.id,
                    err,
                    self._retry_connect_tmr.get_timeout(),
                )
                self._retry_connect_tmr.start()
        else:
            logging.debug(
                'Controller._on_connect_fail()      - %s Received event on dead object. %s %s',
                self.id,
                err.domain,
                err.message,
            )

    def disconnect(self, disconnected_cb, keep_connection):
        '''@brief Issue an asynchronous disconnect command to a Controller.
        Once the async command has completed, the callback 'disconnected_cb'
        will be invoked. If a controller is already disconnected, then the
        callback will be added to the main loop's next idle slot to be executed
        ASAP.
        '''
        logging.debug('Controller.disconnect()            - %s | %s: keep_connection=%s', self.id, self.device, keep_connection)
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
        logging.debug('Controller._on_disconn_fail()      - %s | %s - %s', self.id, self.device, err)
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
    REGISTRATION_RETRY_RERIOD_SEC = 5
    GET_SUPPORTED_RETRY_RERIOD_SEC = 5

    def __init__(self, staf, root, host, tid: trid.TID, log_pages=None):  # pylint: disable=too-many-arguments
        super().__init__(root, host, tid, discovery_ctrl=True)
        self._staf = staf
        self._register_op = None
        self._get_supported_op = None
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
        if self._get_supported_op:
            self._get_supported_op.kill()
            self._get_supported_op = None

    def reload_hdlr(self):
        '''@brief This is called when a "reload" signal is received.'''
        logging.debug('Dc.reload_hdlr()                   - %s | %s', self.id, self.device)
        self._resync_with_controller()

    def info(self) -> dict:
        '''@brief Get the controller info for this object'''
        info = super().info()
        if self._get_log_op:
            info['get log page operation'] = self._get_log_op.as_dict()
        if self._register_op:
            info['register operation'] = self._register_op.as_dict()
        if self._get_supported_op:
            info['get supported log page operation'] = self._get_supported_op.as_dict()
        return info

    def cancel(self):
        '''@brief Used to cancel pending operations.'''
        super().cancel()
        if self._get_log_op:
            self._get_log_op.cancel()
        if self._register_op:
            self._register_op.cancel()
        if self._get_supported_op:
            self._get_supported_op.cancel()

    def log_pages(self) -> list:
        '''@brief Get the cached log pages for this object'''
        return self._log_pages

    def referrals(self) -> list:
        '''@brief Return the list of referrals'''
        return [page for page in self._log_pages if page['subtype'] == 'referral']

    def _is_ddc(self):
        return self._ctrl and self._ctrl.dctype != 'cdc'

    def _on_aen(self, aen: int):
        if aen == self.DLP_CHANGED and self._get_log_op:
            self._get_log_op.run_async()

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
                'Dc._on_nvme_event()                - %s | %s - Received "connected" event', self.id, self.device
            )
            self._resync_with_controller()

    def _on_ctrl_removed(self, obj):
        super()._on_ctrl_removed(obj)
        if self._try_to_connect_deferred:
            self._try_to_connect_deferred.schedule()

    def _find_existing_connection(self):
        return self._udev.find_nvme_dc_device(self.tid)

    def _post_registration_actions(self):
        # Need to check that supported_log_pages() is available (introduced in libnvme 1.2)
        has_supported_log_pages = hasattr(self._ctrl, 'supported_log_pages')

        if not has_supported_log_pages:
            logging.warning(
                '%s | %s - libnvme-%s does not support "Get supported log pages". Please upgrade libnvme.',
                self.id,
                self.device,
                libnvme.__version__,
            )

        if conf.SvcConf().pleo_enabled and self._is_ddc() and has_supported_log_pages:
            self._get_supported_op = gutil.AsyncOperationWithRetry(
                self._on_get_supported_success, self._on_get_supported_fail, self._ctrl.supported_log_pages
            )
            self._get_supported_op.run_async()
        else:
            self._get_log_op = gutil.AsyncOperationWithRetry(
                self._on_get_log_success, self._on_get_log_fail, self._ctrl.discover
            )
            self._get_log_op.run_async()

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
                self._post_registration_actions()

    # --------------------------------------------------------------------------
    def _on_registration_success(self, op_obj, data):  # pylint: disable=unused-argument
        '''@brief Function called when we successfully register with the
        Discovery Controller. See self._register_op object
        for details.

        NOTE: The name _on_registration_success() may be misleading. "success"
        refers to the fact that a successful exchange was made with the DC.
        It doesn't mean that the registration itself succeeded.
        '''
        if self._alive():
            if data is not None:
                logging.warning('%s | %s - Registration error. %s.', self.id, self.device, data)
            else:
                logging.debug('Dc._on_registration_success()      - %s | %s', self.id, self.device)

            self._post_registration_actions()
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
                'Dc._on_registration_fail()         - %s | %s - %s. Retry in %s sec',
                self.id,
                self.device,
                err,
                Dc.REGISTRATION_RETRY_RERIOD_SEC,
            )
            if fail_cnt == 1:  # Throttle the logs. Only print the first time we fail to connect
                logging.error('%s | %s - Failed to register with Discovery Controller. %s', self.id, self.device, err)
            op_obj.retry(Dc.REGISTRATION_RETRY_RERIOD_SEC)
        else:
            logging.debug(
                'Dc._on_registration_fail()         - %s | %s Received event on dead object. %s',
                self.id,
                self.device,
                err,
            )
            op_obj.kill()

    # --------------------------------------------------------------------------
    def _on_get_supported_success(self, op_obj, data):  # pylint: disable=unused-argument
        '''@brief Function called when we successfully retrieved the supported
        log pages from the Discovery Controller. See self._get_supported_op object
        for details.

        NOTE: The name _on_get_supported_success() may be misleading. "success"
        refers to the fact that a successful exchange was made with the DC.
        It doesn't mean that the Get Supported Log Page itself succeeded.
        '''
        if self._alive():
            try:
                dlp_supp_opts = data[nvme.NVME_LOG_LID_DISCOVER] >> 16
            except (TypeError, IndexError):
                dlp_supp_opts = 0

            logging.debug(
                'Dc._on_get_supported_success()     - %s | %s - supported options = 0x%04X = %s',
                self.id,
                self.device,
                dlp_supp_opts,
                dlp_supp_opts_as_string(dlp_supp_opts),
            )

            if 'lsp' in inspect.signature(self._ctrl.discover).parameters:
                lsp = nvme.NVMF_LOG_DISC_LSP_PLEO if dlp_supp_opts & nvme.NVMF_LOG_DISC_LID_PLEOS else 0
                self._get_log_op = gutil.AsyncOperationWithRetry(
                    self._on_get_log_success, self._on_get_log_fail, self._ctrl.discover, lsp
                )
            else:
                logging.warning(
                    '%s | %s - libnvme-%s does not support setting PLEO bit. Please upgrade.',
                    self.id,
                    self.device,
                    libnvme.__version__,
                )
                self._get_log_op = gutil.AsyncOperationWithRetry(
                    self._on_get_log_success, self._on_get_log_fail, self._ctrl.discover
                )
            self._get_log_op.run_async()
        else:
            logging.debug(
                'Dc._on_get_supported_success()     - %s | %s Received event on dead object.', self.id, self.device
            )

    def _on_get_supported_fail(self, op_obj, err, fail_cnt):
        '''@brief Function called when we fail to retrieve the supported log
        page from the Discovery Controller. See self._get_supported_op object
        for details.
        '''
        if self._alive():
            logging.debug(
                'Dc._on_get_supported_fail()        - %s | %s - %s. Retry in %s sec',
                self.id,
                self.device,
                err,
                Dc.GET_SUPPORTED_RETRY_RERIOD_SEC,
            )
            if fail_cnt == 1:  # Throttle the logs. Only print the first time we fail to connect
                logging.error(
                    '%s | %s - Failed to Get supported log pages from Discovery Controller. %s',
                    self.id,
                    self.device,
                    err,
                )
            op_obj.retry(Dc.GET_SUPPORTED_RETRY_RERIOD_SEC)
        else:
            logging.debug(
                'Dc._on_get_supported_fail()        - %s | %s Received event on dead object. %s',
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
            # return invalid addresses ('0.0.0.0', '::', or ''). Those need to
            # be filtered out.
            referrals_before = self.referrals()
            self._log_pages = (
                [
                    {k: str(v) for k, v in dictionary.items()}
                    for dictionary in data
                    if dictionary.get('traddr') not in ('0.0.0.0', '::', '')
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
                'Dc._on_get_log_fail()              - %s | %s - %s. Retry in %s sec',
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
        self._dlpe = None
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

    def reload_hdlr(self):
        '''@brief This is called when a "reload" signal is received.'''
        if not self.connected() and self._retry_connect_tmr.time_remaining() == 0:
            self._try_to_connect_deferred.schedule()

    @property
    def eflags(self):
        '''@brief Return the eflag field of the DLPE'''
        return get_eflags(self._dlpe)

    @property
    def ncc(self):
        '''@brief Return Not Connected to CDC status'''
        return get_ncc(self.eflags)

    def details(self) -> dict:
        '''@brief return detailed debug info about this controller'''
        details = super().details()
        details['dlpe'] = str(self._dlpe)
        details['dlpe.eflags.ncc'] = str(self.ncc)
        return details

    def update_dlpe(self, dlpe):
        '''@brief This method is called when a new DLPE associated
        with this controller is received.'''
        new_ncc = get_ncc(get_eflags(dlpe))
        old_ncc = self.ncc
        self._dlpe = dlpe

        if old_ncc and not new_ncc:  # NCC bit cleared?
            if not self.connected():
                self._connect_attempts = 0
                self._try_to_connect_deferred.schedule()

    def _should_try_to_reconnect(self):
        '''@brief This is used to determine when it's time to stop trying toi connect'''
        max_connect_attempts = conf.SvcConf().connect_attempts_on_ncc if self.ncc else 0
        return max_connect_attempts == 0 or self._connect_attempts < max_connect_attempts
