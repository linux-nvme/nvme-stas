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
import dasbus.connection
from gi.repository import Gio, GLib
from systemd.daemon import notify as sd_notify
from libnvme3 import nvme
from staslib import conf, defs, gutil, iputil, log, trid

try:
    # Python 3.9 or later (preferred)
    from importlib.resources import files as _importlib_files
except ImportError:
    try:
        # Pre-3.9 backport of importlib.resources (if installed)
        from importlib_resources import files as _importlib_files
    except ImportError:
        _importlib_files = None

if _importlib_files is not None:

    def load_idl(idl_fname):
        '''Load and return a D-Bus introspection XML file from the staslib package
        (e.g. 'stafd.idl'). Returns an empty string if the file is not found.'''
        try:
            return _importlib_files('staslib').joinpath(idl_fname).read_text()
        except FileNotFoundError:
            pass

        return ''

else:
    # Less efficient fallback available on older Python versions
    import pkg_resources

    def load_idl(idl_fname):
        '''Load and return a D-Bus introspection XML file from the staslib package
        (e.g. 'stafd.idl'). Returns an empty string if the file is not found.'''
        try:
            return pkg_resources.resource_string('staslib', idl_fname).decode()
        except (FileNotFoundError, AttributeError):
            pass

        return ''


# ******************************************************************************
def check_if_allowed_to_continue():
    '''Check that the process has root privileges and that /dev/nvme-fabrics exists.
    Exits the program immediately if either condition is not met.'''
    # 1) Check root privileges
    if os.geteuid() != 0:
        sys.exit(f'Permission denied. You need root privileges to run {defs.PROG_NAME}.')

    # 2) Check that nvme-tcp kernel module is running
    if not os.path.exists('/dev/nvme-fabrics'):
        # There's no point going any further if the kernel module hasn't been loaded
        sys.exit('Fatal error: /dev/nvme-fabrics not found. Check that the NVMe-oF kernel modules are loaded.')


# ******************************************************************************
def remove_invalid_addresses(controllers: list):
    '''Return a filtered copy of controllers with invalid or disabled-family IP addresses removed.'''
    service_conf = conf.SvcConf()
    valid_controllers = list()
    for controller in controllers:
        if controller.transport in ('tcp', 'rdma'):
            # Let's make sure that traddr is
            # syntactically a valid IPv4 or IPv6 address.
            ip = iputil.get_ipaddress_obj(controller.traddr)
            if ip is None:
                logging.warning('%s IP address is not valid', controller)
                continue

            # Let's make sure the address family is enabled.
            if ip.version not in service_conf.ip_family:
                logging.debug(
                    '%s ignored because IPv%s is disabled in %s',
                    controller,
                    ip.version,
                    service_conf.conf_file,
                )
                continue

            valid_controllers.append(controller)

        elif controller.transport in ('fc', 'loop'):
            # At some point, need to validate FC addresses as well...
            valid_controllers.append(controller)

        else:
            logging.warning('Invalid transport %s', controller.transport)

    return valid_controllers


# ******************************************************************************
def tid_from_dlpe(dlpe, host_traddr, host_iface, hostnqn):
    '''Convert a Discovery Log Page Entry (DLPE) to a controller ID dict.'''
    cid = {
        'transport': dlpe['trtype'],
        'traddr': dlpe['traddr'],
        'trsvcid': dlpe['trsvcid'],
        'host-traddr': host_traddr,
        'host-iface': host_iface,
        'subsysnqn': dlpe['subnqn'],
    }
    if hostnqn:
        cid['hostnqn'] = hostnqn
    return trid.TID(cid)


# ******************************************************************************
def _fc_wwn(traddr: str):
    '''Normalize an FC WWN pair. Some Discovery Controllers report it as
    "nn-0x...,pn-0x..." (comma) instead of the spec's "nn-0x...:pn-0x..."
    (colon). Mirrors libnvme's fc_wwn_normalize().'''
    return traddr.replace(',', ':', 1)


def _addresses_match(val: str, ctrl_val: str, transport: str):
    '''Return True if two addresses designate the same thing. Addresses are
    compared in normalized form, the way libnvme's exclusion list does it, so
    that two spellings of one address match: "fe80::1" designates the same
    controller as "fe80:0000:0000:0000:0000:0000:0000:0001".'''
    if transport == 'fc':
        return _fc_wwn(val) == _fc_wwn(ctrl_val)

    ip = iputil.get_ipaddress_obj(val)
    ctrl_ip = iputil.get_ipaddress_obj(ctrl_val)
    if ip is not None and ctrl_ip is not None:
        return ip == ctrl_ip

    # Not a numeric address on either side. This is how a hostname in an
    # "exclude=" entry gets matched before name resolution has taken place.
    return val == ctrl_val


def _values_match(key: str, val: str, ctrl_val, transport: str):
    '''Return True if the value of an exclusion entry matches a controller's.'''
    if ctrl_val is None:
        return False

    if key in ('traddr', 'host-traddr'):
        return _addresses_match(val, ctrl_val, transport)

    return val == ctrl_val


def _excluded(excluded_ctrl_list, controller: dict):
    '''Return True if controller matches any entry in excluded_ctrl_list.'''
    transport = controller.get('transport', '')
    for excluded_ctrl in excluded_ctrl_list:
        test_results = [
            _values_match(key, val, controller.get(key, None), transport) for key, val in excluded_ctrl.items()
        ]
        if all(test_results):
            return True
    return False


# ******************************************************************************
def _nbft_tids():
    '''Return the TIDs of all the controllers described by the NBFT.

    This is meant to be temporary. Reading the NBFT ourselves is only needed
    because a boot connection carries "owner=nbft" in the registry solely when
    the initramfs that made it was new enough to write it, and the initramfs
    nvme-cli is a snapshot taken when the initramfs was built, which can lag
    the root file system by a long time. Until initramfs images in the field
    can be counted on to register their connections, an unmarked boot
    controller would look unowned to us, and unowned is eligible.

    Once that marking is dependable - years, not releases - this function and
    the NBFT half of protected() can go, and the registry owner check alone
    will filter NBFT controllers out.
    '''
    nbft_conf = conf.NbftConf()
    return {trid.TID(cid) for cid in nbft_conf.dcs + nbft_conf.iocs}


# ******************************************************************************
def _owner(device):
    '''Return the orchestrator that owns device according to libnvme's
    registry, or None if the device has no registry entry.'''
    if not device or device == 'nvme?':
        return None

    try:
        return nvme.registry_retrieve(conf.libnvme_ctx(), device, 'owner')
    except (OSError, ValueError) as ex:
        # A registry we can't read must not get in the way of a teardown.
        logging.warning('Unable to read the registry entry of %s: %s', device, ex)
        return None


# ******************************************************************************
def claim(tid, device):
    '''Record in libnvme's registry that this connection is ours.

    libnvme registers owner=stas on the controllers it connects for us, but
    Controller._do_connect() borrows an existing connection when it finds one
    instead of making a new one, and a borrow never reaches libnvme's connect
    path. Claiming it here is what tells everybody else we took it over:
    "nvme connect-all" does nothing at all with a Discovery Controller that
    somebody else owns, and that is what keeps udevd from racing us for it.

    A connection that already belongs to somebody else is left alone.
    remove_protected() should have kept it out of our hands long before we got
    here, but ownership can change under a connection we already hold, and
    taking it away from its owner is never ours to do.
    '''
    if not device or device == 'nvme?':
        return

    owner = _owner(device)
    if owner is not None:
        if owner != defs.REGISTRY_OWNER:
            logging.debug('claim()                            - %s | %s: owned by "%s"', tid, device, owner)
        return

    try:
        nvme.registry_update(conf.libnvme_ctx(), device, 'owner', defs.REGISTRY_OWNER)
    except (OSError, ValueError) as ex:
        # Not being able to claim it is not a reason to give up the connection.
        logging.warning('Unable to claim the registry entry of %s: %s', device, ex)


# ******************************************************************************
def protected(tid, device=None):
    '''Return True if this controller must never be disconnected by us.

    Two independent sources, either of which is sufficient:

    - libnvme's registry says the connection belongs to another orchestrator
      (nvme-discoverd, the initramfs, ...). A controller with no registry entry
      remains eligible: that is what every connection predating the registry
      looks like.
    - The controller is described by the NBFT, i.e. it is a boot connection. We
      read the NBFT ourselves instead of trusting "owner=nbft" to be in the
      registry, because that marking is only made by an initramfs new enough to
      make it, and the initramfs nvme-cli is a snapshot taken at initramfs
      build time that can lag the root file system.
    '''
    owner = _owner(device)
    if owner is not None and owner != defs.REGISTRY_OWNER:
        logging.debug('protected()                        - %s | %s: owned by "%s"', tid, device, owner)
        return True

    return tid in _nbft_tids()


# ******************************************************************************
def remove_protected(controllers: list, find_device):
    '''Return a filtered copy of controllers with the connections that are not
    ours to manage removed. @find_device maps a TID to the udev device of an
    existing connection, or None.

    This is where "we never disconnect somebody else's controller" is really
    decided. Controller._do_connect() borrows an existing connection rather than
    making a new one, so a controller we keep here is one we would adopt and,
    later, disconnect. Dropping it now means we never take it over in the first
    place; CtrlTerminator.dispose() then only has to catch the cases where a
    controller we already hold turns out to belong to somebody else.
    '''
    keep = []
    for controller in controllers:
        device = find_device(controller)
        if protected(controller, device.sys_name if device is not None else None):
            logging.debug('remove_protected()                 - %s: not ours to manage', controller)
            continue
        keep.append(controller)

    return keep


# ******************************************************************************
def excluded(controller):
    '''Return True if controller is excluded by the configuration file.'''
    return _excluded(conf.SvcConf().get_excluded(), controller.as_dict())


# ******************************************************************************
def remove_excluded(controllers: list):
    '''Return a filtered copy of controllers with excluded entries removed.'''
    excluded_ctrl_list = conf.SvcConf().get_excluded()
    if excluded_ctrl_list:
        logging.debug('remove_excluded()                  - excluded_ctrl_list   = %s', excluded_ctrl_list)
        controllers = [
            controller for controller in controllers if not _excluded(excluded_ctrl_list, controller.as_dict())
        ]
    return controllers


# ******************************************************************************
class ControllerABC(abc.ABC):
    '''Abstract base class for managing the connection to an NVMe controller.'''

    CONNECT_RETRY_PERIOD_SEC = 60
    FAST_CONNECT_RETRY_PERIOD_SEC = 3

    def __init__(self, tid: trid.TID, service, discovery_ctrl: bool = False):
        self._tid = tid
        self._serv = service  # Refers to the parent service (either Staf or Stac)
        self.set_level_from_tron(self._serv.tron)
        self._cancellable = Gio.Cancellable()
        self._connect_attempts = 0
        self._retry_connect_tmr = gutil.GTimer(self.CONNECT_RETRY_PERIOD_SEC, self._on_try_to_connect)
        self._discovery_ctrl = discovery_ctrl
        self._try_to_connect_deferred = gutil.Deferred(self._try_to_connect)
        self._try_to_connect_deferred.schedule()

    def _release_resources(self):
        # Remove pending deferred from main loop
        if self._try_to_connect_deferred:
            self._try_to_connect_deferred.cancel()

        if self._retry_connect_tmr is not None:
            self._retry_connect_tmr.kill()

        if self._alive():
            self._cancellable.cancel()

        self._tid = None
        self._serv = None
        self._cancellable = None
        self._retry_connect_tmr = None
        self._try_to_connect_deferred = None

    @property
    def id(self) -> str:
        '''Return the Transport ID as a printable string.'''
        return str(self.tid)

    @property
    def tid(self):
        '''Return the Transport ID object.'''
        return self._tid

    def controller_id_dict(self) -> dict:
        '''Return the controller ID as a dict.'''
        return {k: str(v) for k, v in self.tid.as_dict().items()}

    def details(self) -> dict:
        '''Return detailed debug info about this controller.'''
        return self.info()

    def info(self) -> dict:
        '''Return the controller info for this object.'''
        info = self.controller_id_dict()
        info['connect attempts'] = str(self._connect_attempts)
        info['retry connect timer'] = str(self._retry_connect_tmr)
        return info

    def cancel(self):
        '''Cancel pending operations.'''
        if self._alive():
            logging.debug('ControllerABC.cancel()             - %s', self.id)
            self._cancellable.cancel()

    def kill(self):
        '''Release all resources associated with this object.'''
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
        if self._alive():
            self._try_to_connect_deferred.schedule()
        return GLib.SOURCE_REMOVE

    def _should_try_to_reconnect(self):
        return True

    def _try_to_connect(self):
        if not self._alive():
            return GLib.SOURCE_REMOVE

        # This is a deferred function call. Make sure
        # the source of the deferred is still good.
        source = GLib.main_current_source()
        if source and source.is_destroyed():
            return GLib.SOURCE_REMOVE

        # The exclusion list may have changed since this controller was
        # configured. Check it on every attempt so that a controller that
        # is now excluded does not get (re)connected while we wait for the
        # normal reconfiguration to dispose of it.
        if excluded(self.tid):
            logging.info('%s - Controller is excluded. Do not connect.', self.id)
            return GLib.SOURCE_REMOVE

        self._connect_attempts += 1

        self._do_connect()

        return GLib.SOURCE_REMOVE

    @abc.abstractmethod
    def set_level_from_tron(self, tron):
        '''Set log level based on TRON'''

    @abc.abstractmethod
    def _do_connect(self):
        '''Perform connection'''

    @abc.abstractmethod
    def _on_aen(self, aen: int):
        '''Event handler when an AEN is received'''

    @abc.abstractmethod
    def _on_nvme_event(self, nvme_event):
        '''Event handler when an nvme_event is received'''

    @abc.abstractmethod
    def _on_ctrl_removed(self, udev_obj):
        '''Called when the associated nvme device (/dev/nvmeX) is removed
        from the system by the kernel.
        '''

    @abc.abstractmethod
    def _find_existing_connection(self):
        '''Check if there is an existing connection that matches this Controller's TID'''

    @abc.abstractmethod
    def all_ops_completed(self) -> bool:
        '''Return True if all operations have completed, False otherwise.'''

    @abc.abstractmethod
    def connected(self):
        '''Return whether a connection is established.'''

    @abc.abstractmethod
    def disconnect(self, disconnected_cb, keep_connection):
        '''Issue an asynchronous disconnect command to this controller.
        Once the command completes, disconnected_cb is invoked. If the
        controller is already disconnected, the callback is scheduled on the
        next idle slot of the main loop.'''

    @abc.abstractmethod
    def reload_hdlr(self):
        '''Called when a "reload" signal is received.'''


# ******************************************************************************
class ServiceABC(abc.ABC):
    '''Abstract base class for the stafd and stacd daemon services.'''

    CONF_STABILITY_SOAK_TIME_SEC = 1.5

    # Which half of the connectivity configuration is ours: the
    # [Discovery Controller] sections for stafd, the [Subsystem] sections for
    # stacd. One file serves both daemons.
    CONFIGURES_DCS = None

    def __init__(self, args, default_conf, reload_hdlr):
        service_conf = conf.SvcConf(default_conf=default_conf)
        service_conf.set_conf_file(args.conf_file)  # reload configuration
        # Read the connectivity configuration now, at startup, so that a
        # malformed file is reported here instead of at the first connection
        # attempt, where it would be lost among the connection logging.
        self._conn_conf = conf.ConnConf()
        self._tron = args.tron or service_conf.tron
        log.set_level_from_tron(self._tron)

        self._lkc_file = os.path.join(
            os.environ.get('RUNTIME_DIRECTORY', os.path.join('/run', defs.PROG_NAME)), 'last-known-config.pickle'
        )
        self._loop = GLib.MainLoop()
        self._cancellable = Gio.Cancellable()
        self._resolver = gutil.NameResolver()
        self._controllers = self._load_last_known_config()
        self._dbus_iface = None
        self._cfg_soak_tmr = gutil.GTimer(self.CONF_STABILITY_SOAK_TIME_SEC, self._on_config_ctrls)
        self._sysbus = dasbus.connection.SystemMessageBus()

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

        if self._alive():
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
        '''Return the Trace ON (tron) flag.'''
        return self._tron

    @tron.setter
    def tron(self, value):
        '''Set the Trace ON (tron) flag and propagate the log level to all controllers.'''
        self._tron = value
        log.set_level_from_tron(self._tron)
        for controller in self._controllers.values():
            controller.set_level_from_tron(self._tron)

    def run(self):
        '''Block until a termination signal is received, then return.'''
        try:
            self._loop.run()
        except Exception:
            logging.exception('self._loop.run() failed!')

        self._loop = None

    def info(self) -> dict:
        '''Return the status info for this object (used for debug).'''
        nvme_options = conf.NvmeOptions()
        info = conf.SysConf().as_dict()
        info['last known config file'] = self._lkc_file
        info['config soak timer'] = str(self._cfg_soak_tmr)
        info['kernel support.TP8013'] = str(nvme_options.discovery_supp)
        info['kernel support.host_iface'] = str(nvme_options.host_iface_supp)
        return info

    def get_controllers(self) -> dict:
        '''Return the list of controller objects.'''
        return self._controllers.values()

    def get_controller(
        self,
        transport: str,
        traddr: str,
        trsvcid: str,
        subsysnqn: str,
        host_traddr: str,
        host_iface: str,
        hostnqn: str,
    ):
        '''Return the specified controller object, or None if not found.'''
        cid = {
            'transport': transport,
            'traddr': traddr,
            'trsvcid': trsvcid,
            'subsysnqn': subsysnqn,
            'host-traddr': host_traddr,
            'host-iface': host_iface,
            'hostnqn': hostnqn,
        }
        return self._controllers.get(trid.TID(cid))

    def _remove_ctrl_from_dict(self, controller, shutdown=False):
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
            popped = self._controllers.pop(tid_to_pop, None)
            if not shutdown and popped is not None and self._cfg_soak_tmr:
                self._cfg_soak_tmr.start()
        else:
            logging.debug('ServiceABC._remove_ctrl_from_dict()- already removed')

    def remove_controller(self, controller, success):
        '''Remove the specified controller object from the list of controllers.
        success indicates whether the preceding disconnect completed successfully.'''
        logging.debug('ServiceABC.remove_controller()')
        if isinstance(controller, ControllerABC):
            self._remove_ctrl_from_dict(controller)
            controller.kill()

    def _alive(self):
        '''It's a good idea to check that this object hasn't been
        cancelled (i.e. is still alive) when entering a callback function.
        Callback functions can be invoked after, for example, a process has
        been signalled to stop or restart, in which case it makes no sense to
        proceed with the callback.
        '''
        return self._cancellable and not self._cancellable.is_cancelled()

    def _cancel(self):
        logging.debug('ServiceABC._cancel()')
        if self._alive():
            self._cancellable.cancel()

        for controller in self._controllers.values():
            controller.cancel()

    def _stop_hdlr(self):
        logging.debug('ServiceABC._stop_hdlr()')
        sd_notify('STOPPING=1')

        self._cancel()  # Cancel pending operations

        self._dump_last_known_config(self._controllers)

        if len(self._controllers) == 0:
            GLib.idle_add(self._exit)
        else:
            self._disconnect_all()

        return GLib.SOURCE_REMOVE

    def _on_final_disconnect(self, controller, success):
        '''Callback invoked after a controller is disconnected.
        THIS IS USED DURING PROCESS SHUTDOWN TO WAIT FOR ALL CONTROLLERS TO BE
        DISCONNECTED BEFORE EXITING THE PROGRAM. ONLY CALL ON SHUTDOWN!
        '''
        logging.debug(
            'ServiceABC._on_final_disconnect()  - %s | %s: disconnect %s',
            controller.id,
            controller.device,
            'succeeded' if success else 'failed',
        )

        self._remove_ctrl_from_dict(controller, True)
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
        if self._alive():
            self._config_ctrls()
        return GLib.SOURCE_REMOVE

    def _config_ctrls(self):
        '''Start controllers configuration.'''
        # The configuration file may contain controllers and/or excluded
        # controllers with traddr specified as hostname instead of IP address.
        # Because of this, we need to remove those excluded elements before
        # running name resolution. And we will need to remove excluded
        # elements after name resolution is complete (i.e. in the callback
        # function _config_ctrls_finish)
        logging.debug('ServiceABC._config_ctrls()')
        # Note that the NBFT is deliberately not consulted here. Controllers
        # described by it were connected by the initramfs and are not ours to
        # manage; protected() keeps us from disconnecting them.
        configured_controllers = [trid.TID(cid) for cid in self._conn_conf.get_controllers(self.CONFIGURES_DCS)]
        configured_controllers = remove_excluded(configured_controllers)
        self._resolver.resolve_ctrl_async(self._cancellable, configured_controllers, self._config_ctrls_finish)

    def _read_lkc(self):
        '''Read the last known config from file.

        Security note: pickle.load() is used here. This is safe because the
        LKC file is written exclusively by this process to a path under
        RUNTIME_DIRECTORY (e.g. /run/nvme-stas/), which is only writable by
        root. No untrusted data can reach this code path.
        '''
        try:
            with open(self._lkc_file, 'rb') as file:
                return pickle.load(file)
        except (FileNotFoundError, AttributeError, EOFError, pickle.UnpicklingError):
            return None

    def _write_lkc(self, config):
        '''Write the last known config to file. If config is empty, the file is truncated.'''
        try:
            # Note that if config is empty we still
            # want to open/close the file to empty it.
            with open(self._lkc_file, 'wb') as file:
                if config:
                    pickle.dump(config, file)
        except FileNotFoundError as ex:
            logging.error('Unable to save last known config: %s', ex)

    @abc.abstractmethod
    def _disconnect_all(self):
        '''Tell all controller objects to disconnect'''

    @abc.abstractmethod
    def _keep_connections_on_exit(self):
        '''Return True if NVMe-oF connections should persist after the daemon exits.'''

    @abc.abstractmethod
    def _config_ctrls_finish(self, configured_ctrl_list):
        '''Complete controller configuration after hostname resolution.

        Controller configuration is split into two async steps: first, any
        hostnames in the config are resolved to IP addresses (which can be
        slow when an external DNS server is involved); then this callback is
        invoked to apply the resolved list and reconcile running controllers.'''

    @abc.abstractmethod
    def _load_last_known_config(self):
        '''Load last known config from file (if any)'''

    @abc.abstractmethod
    def _dump_last_known_config(self, controllers):
        '''Save last known config to file'''
