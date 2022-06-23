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

import os
import signal
import logging
import systemd.daemon
import dasbus.connection

from gi.repository import Gio, GLib
from libnvme import nvme
from staslib import conf, ctrl, defs, gutil, log, stas, trid, udev


# ******************************************************************************
class Service:  # pylint: disable=too-many-instance-attributes
    '''@brief Base class used to manage a STorage Appliance Service'''

    def __init__(self, args, reload_hdlr):

        sysconf = conf.SysConf()
        self._root = nvme.root()
        self._host = nvme.host(self._root, sysconf.hostnqn, sysconf.hostid, sysconf.hostsymname)

        service_conf = conf.SvcConf()
        service_conf.set_conf_file(args.conf_file) # reload configuration
        self._tron = args.tron or service_conf.tron
        log.set_level_from_tron(self._tron)
        self._root.log_level("debug" if self._tron else "err")

        self._lkc_file     = os.path.join(os.environ.get('RUNTIME_DIRECTORY', os.path.join('/run', defs.PROG_NAME)), 'last-known-config.pickle')
        self._loop         = GLib.MainLoop()
        self._udev         = udev.UDEV
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
            logging.warning(
                'Kernel does not appear to support all the options needed to run this program. Consider updating to a later kernel version.'
            )

    def _release_resources(self):
        logging.debug('Service._release_resources()')

        if self._cancellable and not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        if self._cfg_soak_tmr is not None:
            self._cfg_soak_tmr.kill()

        self._controllers.clear()

        if self._sysbus:
            self._sysbus.disconnect()

        self._cfg_soak_tmr = None
        self._cancellable = None
        self._resolver = None
        self._lkc_file = None
        self._sysbus = None
        self._udev = None

    def _config_dbus(self, iface_obj, bus_name: str, obj_name: str):
        self._dbus_iface = iface_obj
        self._sysbus.publish_object(obj_name, iface_obj)
        self._sysbus.register_service(bus_name)

    @property
    def tron(self):
        '''@brief Get Trace ON property'''
        return self._tron

    @tron.setter
    def tron(self, value):  # pylint: disable=no-self-use
        '''@brief Set Trace ON property'''
        self._tron = value
        log.set_level_from_tron(self._tron)
        self._root.log_level("debug" if self._tron else "err")

    def run(self):
        '''@brief Start the main loop execution'''
        try:
            self._loop.run()
        except Exception as ex:  # pylint: disable=broad-except
            logging.critical('exception: %s', ex)

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
            'system config': conf.SysConf().as_dict(),
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
            for tid, _controller in self._controllers.items():
                if _controller is controller:
                    tid_to_pop = tid
                    break

        if tid_to_pop:
            logging.debug('Service._remove_ctrl_from_dict()   - %s | %s', tid_to_pop, controller.device)
            self._controllers.pop(tid_to_pop, None)
        else:
            logging.debug('Service._remove_ctrl_from_dict()   - already removed')

    def remove_controller(self, controller):
        '''@brief remove the specified controller object from the list of controllers'''
        logging.debug('Service.remove_controller()')
        if isinstance(controller, ctrl.Controller):
            self._remove_ctrl_from_dict(controller)

            controller.kill()

        if self._cfg_soak_tmr:
            self._cfg_soak_tmr.start()

    def _cancel(self):
        logging.debug('Service._cancel()')
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
        logging.debug('Service._on_final_disconnect()')
        self._remove_ctrl_from_dict(controller)

        controller.kill()

        # When all controllers have disconnected, we can finish the clean up
        if len(self._controllers) == 0:
            # Defer exit to the next main loop's idle period.
            GLib.idle_add(self._exit)

    def _exit(self):
        logging.debug('Service._exit()')
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
        logging.debug('Service._config_ctrls()')
        configured_controllers = stas.remove_blacklisted(conf.SvcConf().get_controllers())
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
