# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''Library for staf/stac. You will find here common code for stafd and stacd
including the Abstract Base Classes (ABC) for Controllers and Services'''

import os
import sys
import abc
import signal
import pickle
import logging
import systemd.daemon
import dasbus.connection
from gi.repository import Gio, GLib
from staslib import conf, defs, gutil, log, trid

try:
    # Python 3.9 or later
    # This is the preferred way, but may not be available before Python 3.9
    from importlib.resources import files
except ImportError:
    try:
        # Pre Python 3.9 backport of importlib.resources (if installed)
        from importlib_resources import files
    except ImportError:
        # Less efficient, but avalable on older versions of Python
        import pkg_resources

        def load_idl(idl_fname):
            '''@brief Load D-Bus Interface Description Language File'''
            try:
                return pkg_resources.resource_string('staslib', idl_fname).decode()
            except (FileNotFoundError, AttributeError):
                pass

            return ''

    else:

        def load_idl(idl_fname):
            '''@brief Load D-Bus Interface Description Language File'''
            try:
                return files('staslib').joinpath(idl_fname).read_text()  # pylint: disable=unspecified-encoding
            except FileNotFoundError:
                pass

            return ''

else:

    def load_idl(idl_fname):
        '''@brief Load D-Bus Interface Description Language File'''
        try:
            return files('staslib').joinpath(idl_fname).read_text()  # pylint: disable=unspecified-encoding
        except FileNotFoundError:
            pass

        return ''


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
def tid_from_dlpe(dlpe, host_traddr, host_iface):
    '''@brief Take a Discovery Log Page Entry and return a Controller ID as a dict.'''
    cid = {
        'transport':   dlpe['trtype'],
        'traddr':      dlpe['traddr'],
        'trsvcid':     dlpe['trsvcid'],
        'host-traddr': host_traddr,
        'host-iface':  host_iface,
        'subsysnqn':   dlpe['subnqn'],
    }
    return trid.TID(cid)


# ******************************************************************************
def _excluded(excluded_ctrl_list, controller: dict):
    '''@brief Check if @controller is excluded.'''
    for excluded_ctrl in excluded_ctrl_list:
        test_results = [val == controller.get(key, None) for key, val in excluded_ctrl.items()]
        if all(test_results):
            return True
    return False


# ******************************************************************************
def remove_excluded(controllers: list):
    '''@brief Remove excluded controllers from the list of controllers.
    @param controllers: List of TIDs
    '''
    excluded_ctrl_list = conf.SvcConf().get_excluded()
    if excluded_ctrl_list:
        logging.debug('remove_excluded()                  - excluded_ctrl_list = %s', excluded_ctrl_list)
        controllers = [
            controller for controller in controllers if not _excluded(excluded_ctrl_list, controller.as_dict())
        ]
    return controllers


# ******************************************************************************
class ControllerABC(abc.ABC):  # pylint: disable=too-many-instance-attributes
    '''@brief Base class used to manage the connection to a controller.'''

    CONNECT_RETRY_PERIOD_SEC = 60
    FAST_CONNECT_RETRY_PERIOD_SEC = 3

    def __init__(self, root, host, tid: trid.TID, discovery_ctrl=False):
        self._root              = root
        self._host              = host
        self._tid               = tid
        self._cancellable       = Gio.Cancellable()
        self._connect_attempts  = 0
        self._retry_connect_tmr = gutil.GTimer(self.CONNECT_RETRY_PERIOD_SEC, self._on_try_to_connect)
        self._discovery_ctrl    = discovery_ctrl
        self._try_to_connect_deferred = gutil.Deferred(self._try_to_connect)
        self._try_to_connect_deferred.schedule()

    def _release_resources(self):
        # Remove pending deferred from main loop
        if self._try_to_connect_deferred:
            self._try_to_connect_deferred.cancel()

        if self._retry_connect_tmr is not None:
            self._retry_connect_tmr.kill()

        if self._cancellable and not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        self._tid = None
        self._cancellable = None
        self._retry_connect_tmr = None
        self._try_to_connect_deferred = None

    @property
    def id(self) -> str:
        '''@brief Return the Transport ID as a printable string'''
        return str(self.tid)

    @property
    def tid(self):
        '''@brief Return the Transport ID object'''
        return self._tid

    def controller_id_dict(self) -> dict:
        '''@brief return the controller ID as a dict.'''
        return self.tid.as_dict()

    def details(self) -> dict:
        '''@brief return detailed debug info about this controller'''
        return self.info()

    def info(self) -> dict:
        '''@brief Get the controller info for this object'''
        info = self.controller_id_dict()
        info['connect attempts'] = str(self._connect_attempts)
        info['retry connect timer'] = str(self._retry_connect_tmr)
        return info

    def cancel(self):
        '''@brief Used to cancel pending operations.'''
        if self._cancellable and not self._cancellable.is_cancelled():
            logging.debug('ControllerABC.cancel()             - %s', self.id)
            self._cancellable.cancel()

    def kill(self):
        '''@brief Used to release all resources associated with this object.'''
        logging.debug('ControllerABC.kill()               - %s', self.id)
        self._release_resources()

    def _alive(self):
        '''There may be race condition where a queued event gets processed
        after the object is no longer configured (i.e. alive). This method
        can be used by callback functions to make sure the object is still
        alive before processing further.
        '''
        return self._cancellable and not self._cancellable.is_cancelled()

    def _on_try_to_connect(self):
        self._try_to_connect_deferred.schedule()
        return GLib.SOURCE_REMOVE

    def _should_try_to_reconnect(self):  # pylint: disable=no-self-use
        return True

    def _try_to_connect(self):
        # This is a deferred function call. Make sure
        # the source of the deferred is still good.
        source = GLib.main_current_source()
        if source and source.is_destroyed():
            return GLib.SOURCE_REMOVE

        self._connect_attempts += 1

        self._do_connect()

        return GLib.SOURCE_REMOVE

    @abc.abstractmethod
    def _do_connect(self):
        raise NotImplementedError()

    @abc.abstractmethod
    def _on_aen(self, aen: int):
        raise NotImplementedError()

    @abc.abstractmethod
    def _on_nvme_event(self, nvme_event):
        raise NotImplementedError()

    @abc.abstractmethod
    def _on_ctrl_removed(self, obj):
        raise NotImplementedError()

    @abc.abstractmethod
    def _find_existing_connection(self):
        raise NotImplementedError()

    @abc.abstractmethod
    def connected(self):
        '''@brief Return whether a connection is established'''
        raise NotImplementedError()

    @abc.abstractmethod
    def disconnect(self, disconnected_cb, keep_connection):
        '''@brief Issue an asynchronous disconnect command to a Controller.
        Once the async command has completed, the callback 'disconnected_cb'
        will be invoked. If a controller is already disconnected, then the
        callback will be added to the main loop's next idle slot to be executed
        ASAP.
        '''
        raise NotImplementedError()

    @abc.abstractmethod
    def reload_hdlr(self):
        '''@brief This is called when a "reload" signal is received.'''
        raise NotImplementedError()


# ******************************************************************************
class ServiceABC(abc.ABC):  # pylint: disable=too-many-instance-attributes
    '''@brief Base class used to manage a STorage Appliance Service'''

    CONF_STABILITY_SOAK_TIME_SEC = 1.5

    def __init__(self, args, default_conf, reload_hdlr):

        service_conf = conf.SvcConf(default_conf=default_conf)
        service_conf.set_conf_file(args.conf_file)  # reload configuration
        self._tron = args.tron or service_conf.tron
        log.set_level_from_tron(self._tron)

        self._lkc_file     = os.path.join(os.environ.get('RUNTIME_DIRECTORY', os.path.join('/run', defs.PROG_NAME)), 'last-known-config.pickle')
        self._loop         = GLib.MainLoop()
        self._cancellable  = Gio.Cancellable()
        self._resolver     = gutil.NameResolver()
        self._controllers  = self._load_last_known_config()
        self._dbus_iface   = None
        self._cfg_soak_tmr = gutil.GTimer(self.CONF_STABILITY_SOAK_TIME_SEC, self._on_config_ctrls)
        self._sysbus       = dasbus.connection.SystemMessageBus()

        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, self._stop_hdlr)  # CTRL-C
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self._stop_hdlr)  # systemctl stop stafd
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGHUP, reload_hdlr)  # systemctl reload stafd

        nvme_options = conf.NvmeOptions()
        if not nvme_options.host_iface_supp or not nvme_options.discovery_supp:
            logging.warning(
                'Kernel does not appear to support all the options needed to run this program. Consider updating to a later kernel version.'
            )

        # We don't want to apply configuration changes right away.
        # Often, multiple changes will occur in a short amount of time (sub-second).
        # We want to wait until there are no more changes before applying them
        # to the system. The following timer acts as a "soak period". Changes
        # will be applied by calling self._on_config_ctrls() at the end of
        # the soak period.
        self._cfg_soak_tmr.start()

    def _release_resources(self):
        logging.debug('ServiceABC._release_resources()')

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

    def _config_dbus(self, iface_obj, bus_name: str, obj_name: str):
        self._dbus_iface = iface_obj
        self._sysbus.publish_object(obj_name, iface_obj)
        self._sysbus.register_service(bus_name)

    @property
    def tron(self):
        '''@brief Get Trace ON property'''
        return self._tron

    @tron.setter
    def tron(self, value):
        '''@brief Set Trace ON property'''
        self._tron = value
        log.set_level_from_tron(self._tron)

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
        info = conf.SysConf().as_dict()
        info['last known config file'] = self._lkc_file
        info['config soak timer'] = str(self._cfg_soak_tmr)
        info['kernel support.TP8013'] = str(nvme_options.discovery_supp)
        info['kernel support.host_iface'] = str(nvme_options.host_iface_supp)
        return info

    def get_controllers(self) -> dict:
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
            logging.debug('ServiceABC._remove_ctrl_from_dict()- %s | %s', tid_to_pop, controller.device)
            self._controllers.pop(tid_to_pop, None)
        else:
            logging.debug('ServiceABC._remove_ctrl_from_dict()- already removed')

    def remove_controller(self, controller, success):  # pylint: disable=unused-argument
        '''@brief remove the specified controller object from the list of controllers
        @param controller: the controller object
        @param success: whether the disconnect was successful'''
        logging.debug('ServiceABC.remove_controller()')
        if isinstance(controller, ControllerABC):
            self._remove_ctrl_from_dict(controller)

            controller.kill()

        if self._cfg_soak_tmr:
            self._cfg_soak_tmr.start()

    def _cancel(self):
        logging.debug('ServiceABC._cancel()')
        if not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        for controller in self._controllers.values():
            controller.cancel()

    def _stop_hdlr(self):
        logging.debug('ServiceABC._stop_hdlr()')
        systemd.daemon.notify('STOPPING=1')

        self._cancel()  # Cancel pending operations

        self._dump_last_known_config(self._controllers)

        if len(self._controllers) == 0:
            GLib.idle_add(self._exit)
        else:
            # Tell all controller objects to disconnect
            keep_connections = self._keep_connections_on_exit()
            controllers = self._controllers.values()
            logging.debug(
                'ServiceABC._stop_hdlr()            - Controller count = %s, keep_connections = %s',
                len(controllers),
                keep_connections,
            )
            for controller in controllers:
                controller.disconnect(self._on_final_disconnect, keep_connections)

        return GLib.SOURCE_REMOVE

    def _on_final_disconnect(self, controller, success):
        '''Callback invoked after a controller is disconnected.
        THIS IS USED DURING PROCESS SHUTDOWN TO WAIT FOR ALL CONTROLLERS TO BE
        DISCONNECTED BEFORE EXITING THE PROGRAM. ONLY CALL ON SHUTDOWN!
        @param controller: the controller object
        @param success: whether the disconnect operation was successful
        '''
        logging.debug(
            'ServiceABC._on_final_disconnect()  - %s | %s disconnect %s',
            controller.id,
            controller.device,
            'succeeded' if success else 'failed',
        )

        self._remove_ctrl_from_dict(controller)

        controller.kill()

        # When all controllers have disconnected, we can finish the clean up
        if len(self._controllers) == 0:
            # Defer exit to the next main loop's idle period.
            GLib.idle_add(self._exit)

    def _exit(self):
        logging.debug('ServiceABC._exit()')
        self._release_resources()
        self._loop.quit()

    def _on_config_ctrls(self, *_user_data):
        self._config_ctrls()
        return GLib.SOURCE_REMOVE

    def _config_ctrls(self):
        '''@brief Start controllers configuration.'''
        # The configuration file may contain controllers and/or excluded
        # controllers with traddr specified as hostname instead of IP address.
        # Because of this, we need to remove those excluded elements before
        # running name resolution. And we will need to remove excluded
        # elements after name resolution is complete (i.e. in the calback
        # function _config_ctrls_finish)
        logging.debug('ServiceABC._config_ctrls()')
        configured_controllers = [trid.TID(controller) for controller in conf.SvcConf().get_controllers()]
        configured_controllers = remove_excluded(configured_controllers)
        self._resolver.resolve_ctrl_async(self._cancellable, configured_controllers, self._config_ctrls_finish)

    def _read_lkc(self):
        '''@brief Read Last Known Config from file'''
        try:
            with open(self._lkc_file, 'rb') as file:
                return pickle.load(file)
        except (FileNotFoundError, AttributeError, EOFError):
            return None

    def _write_lkc(self, config):
        '''@brief Write Last Known Config to file, and if config is empty
        make sure the file is emptied.'''
        try:
            # Note that if config is empty we still
            # want to open/close the file to empty it.
            with open(self._lkc_file, 'wb') as file:
                if config:
                    pickle.dump(config, file)
        except FileNotFoundError as ex:
            logging.error('Unable to save last known config: %s', ex)

    @abc.abstractmethod
    def _keep_connections_on_exit(self):
        '''@brief Determine whether connections should remain when the
        process exits.

        NOTE) This is the base class method used to define the interface.
        It must be overloaded by a child class.
        '''
        raise NotImplementedError()

    @abc.abstractmethod
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

    @abc.abstractmethod
    def _load_last_known_config(self):
        raise NotImplementedError()

    @abc.abstractmethod
    def _dump_last_known_config(self, controllers):
        raise NotImplementedError()
