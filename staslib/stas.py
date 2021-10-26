# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
''' Library for staf/stac
'''
import os
import re
import sys
import signal
import atexit
import logging as LG
import configparser
import platform
import pyudev
import systemd.daemon
import dasbus.connection
try:
    from pyudev.glib import MonitorObserver
except ModuleNotFoundError:
    from .glibudev import MonitorObserver # pylint: disable=relative-beyond-top-level

from gi.repository import Gio, GLib, GObject
from distutils.version import LooseVersion
from libnvme import nvme
from staslib import defs

#*******************************************************************************
def check_if_allowed_to_continue():
    ''' @brief Let's perform some basic checks before going too far. There are
               a few pre-requisites that need to be met before this program
               is allowed to proceed:

                 1) The program needs to have root privileges
                 2) The nvme-tcp kernel module must be loaded

        @return This function will only return if all conditions listed above
                are met. Otherwise the program exits.
    '''
    # 1) Check root privileges
    if os.geteuid() != 0:
        sys.exit(f'Permission denied. You need root privileges to run {os.path.basename(sys.argv[0])}.')

    # 2) Check that nvme-tcp kernel module is running
    if not os.path.exists('/dev/nvme-fabrics'):
        # There's no point going any further if the kernel module hasn't been loaded
        sys.exit('Fatal error: missing nvme-tcp kernel module')

#*******************************************************************************
LOG = None # Singleton
def get_logger(syslog:bool, identifier:str):
    ''' @brief Configure the logging system. The logging system can be
               configured to print to the syslog (journal) or stdout.

        @param syslog: If True print to syslog (journal),
                       Otherwise print to stdout.
    '''
    if syslog:
        try:
            # Try journal logger first
            import systemd.journal # pylint: disable=redefined-outer-name,import-outside-toplevel
            handler = systemd.journal.JournalHandler(SYSLOG_IDENTIFIER=identifier)
        except ModuleNotFoundError:
            # Go back to standard syslog handler
            import logging.handlers # pylint: disable=import-outside-toplevel
            handler = logging.handlers.SysLogHandler(address="/dev/log")
            handler.setFormatter(logging.Formatter('{}: %(message)s'.format(identifier)))

        level = LG.INFO
    else:
        # Log to stdout
        handler = LG.StreamHandler(stream=sys.stdout)
        level = LG.DEBUG

    global LOG     # pylint: disable=global-statement
    LOG = LG.getLogger(__name__)
    LOG.setLevel(level)
    LOG.addHandler(handler)
    LOG.propagate = False
    return LOG

def log_level() -> str:
    ''' @brief return current log level
    '''
    return str(LG.getLevelName(LOG.getEffectiveLevel()))

#*******************************************************************************
TRON = False # Singleton
def trace_control(tron:bool):
    ''' @brief Allows changing debug level in real time. Setting tron to True
               enables full tracing.
    '''
    global TRON # pylint: disable=global-statement
    TRON = tron
    LOG.setLevel(LG.DEBUG if TRON else LG.INFO)

#*******************************************************************************
TOKEN_RE  = re.compile(r'\s*;\s*')
OPTION_RE = re.compile(r'\s*=\s*')
def parse_controller(controller):
    ''' @brief Parse a "controller" entry. Controller entries are strings
               composed of several configuration parameters delimited by
               semi-colons. Each configuration parameter is specified as a
               "key=value" pair.
        @return A dictionary of key-value pairs.
    '''
    options = dict()
    tokens  = TOKEN_RE.split(controller)
    for token in tokens:
        if token:
            try:
                option,val = OPTION_RE.split(token)
                options[option] = val
            except ValueError:
                pass

    return options

#*******************************************************************************
class OrderedMultisetDict(dict):
    ''' This calls is used to change the behavior of configparser.ConfigParser
        and allow multiple configuration parameters with the same key. The
        result is a list of values.
    '''
    def __setitem__(self, key, value):
        if key in self and isinstance(value, list):
            self[key].extend(value)
        else:
            super().__setitem__(key, value)

    def __getitem__(self, key):
        value = super().__getitem__(key)

        if isinstance(value, str):
            return value.split('\n')

        return value

class Configuration:
    ''' Read and cache configuration file.
    '''
    def __init__(self, conf_file):
        self.defaults = {
            ('Global', 'tron'): 'false',
            ('Global', 'persistent-connections'): 'true',
            ('Global', 'hdr-digest'): 'false',
            ('Global', 'data-digest'): 'false',
            ('Global', 'kato'): None,
            ('Service Discovery', 'stype'): list(),
            ('Controllers', 'controller'): list(),
            ('Controllers', 'blacklist'): list(),
        }
        self._conf_file = conf_file
        self.reload()

    def reload(self):
        ''' @brief Reload the configuration file.
        '''
        self._config = self.read_conf_file()

    @property
    def tron(self):
        ''' @brief return the "tron" config parameter
        '''
        return self.__get_value('Global', 'tron')[0] == 'true'

    @property
    def hdr_digest(self):
        ''' @brief return the "hdr-digest" config parameter
        '''
        return self.__get_value('Global', 'hdr-digest')[0] == 'true'

    @property
    def data_digest(self):
        ''' @brief return the "data-digest" config parameter
        '''
        return self.__get_value('Global', 'data-digest')[0] == 'true'

    @property
    def kato(self):
        ''' @brief return the "kato" config parameter
        '''
        kato = self.__get_value('Global', 'kato')[0]
        return None if kato is None else int(kato)

    @property
    def persistent_connections(self):
        ''' @brief return the "persistent-connections" config parameter
        '''
        return self.__get_value('Global', 'persistent-connections')[0] == 'true'

    def get_controllers(self):
        ''' @brief Return the list of controllers in the config file.
                   Each controller is in the form of a dictionary as follows.
                   Note that some of the keys are optional.
                   {
                       'transport':   [TRANSPORT],
                       'traddr':      [TRADDR],
                       'trsvcid':     [TRSVCID],
                       'host-traddr': [TRADDR],
                       'host-iface':  [IFACE],
                       'subsysnqn':   [NQN],
                   }
        '''
        controller_list = self.__get_value('Controllers', 'controller')
        controllers = [ parse_controller(controller) for controller in controller_list ]
        for controller in controllers:
            try:
                # replace 'nqn' key by 'subsysnqn', if present.
                controller['subsysnqn'] = controller.pop('nqn')
            except KeyError:
                pass
        return controllers

    def get_blacklist(self):
        ''' @brief Return the list of blacklisted controllers in the config file.
                   Each blacklisted controller is in the form of a dictionary
                   as follows. All the keys are optional.
                   {
                       'transport':  [TRANSPORT],
                       'traddr':     [TRADDR],
                       'trsvcid':    [TRSVCID],
                       'host-iface': [IFACE],
                       'subsysnqn':  [NQN],
                   }
        '''
        controller_list = self.__get_value('Controllers', 'blacklist')
        blacklist = [ parse_controller(controller) for controller in controller_list ]
        for controller in blacklist:
            controller.pop('host-traddr', None) # remove host-traddr
            try:
                # replace 'nqn' key by 'subsysnqn', if present.
                controller['subsysnqn'] = controller.pop('nqn')
            except KeyError:
                pass
        return blacklist

    def get_stypes(self):
        ''' @brief Get the DNS-SD/mDNS service types.
        '''
        return self.__get_value('Service Discovery', 'stype')

    def read_conf_file(self):
        ''' @brief Read the configuration file if the file exists.
        '''
        config = configparser.ConfigParser(default_section=None, allow_no_value=True, delimiters=('='),
                                           interpolation=None, strict=False, dict_type=OrderedMultisetDict)
        if os.path.isfile(self._conf_file):
            config.read(self._conf_file)
        return config

    def __get_value(self, section, option):
        default = self.defaults[(section, option)]
        if not isinstance(default, list):
            default = [default]
        try:
            return ( self._config.get(section=section, option=option, fallback=default)
                     if isinstance(self._config, configparser.ConfigParser) else default )
        except configparser.NoSectionError:
            return default

CNF = None # Singleton
def get_configuration(conf_file:str):
    global CNF # pylint: disable=global-statement
    CNF = Configuration(conf_file)
    return CNF

#*******************************************************************************
KERNEL_VERSION = platform.release()

class NvmeOptions():
    def __init__(self):
        ''' Read and cache contents of file /dev/nvme-fabrics.
            Note that this file was not readable prior to Linux 5.16.
        '''
        # Supported options can be determined by looking at the kernel version
        # or by reading '/dev/nvme-fabrics'. The ability to read the options
        # from '/dev/nvme-fabrics' was only introduced in kernel 5.17, but may
        # have been backported to older kernels. In any case, if the kernel
        # version meets the minimum version for that option, then we don't need
        # even need to read '/dev/nvme-fabrics'.
        self._supported_options = {
            'register':   LooseVersion(KERNEL_VERSION) >= LooseVersion(defs.KERNEL_TP8010_MIN_VERSION),
            'discovery':  LooseVersion(KERNEL_VERSION) >= LooseVersion(defs.KERNEL_TP8013_MIN_VERSION),
            'host_iface': LooseVersion(KERNEL_VERSION) >= LooseVersion(defs.KERNEL_REQD_MIN_VERSION),
        }

        # If some of the options are False, we need to check wether they can be
        # read from '/dev/nvme-fabrics'. This method allows us to determine that
        # an older kernels actually supports a specific option because it was
        # backported to that kernel.
        if not all(self._supported_options.values()): # At least one option is False.
            try:
                with open('/dev/nvme-fabrics') as f:
                    options = [ option.split('=')[0].strip() for option in f.readlines()[0].rstrip('\n').split(',') ]
            except PermissionError: # Must be root to read this file
                raise
            except OSError:
                LOG.warning('Cannot determine which NVMe options the kernel supports')
            else:
                for option, supported in self._supported_options.items():
                    if not supported:
                        self._supported_options[option] = option in options

    def __str__(self):
        return f'supported options: {self._supported_options}'

    @property
    def register_supp(self):
        ''' This option adds support for TP8010 '''
        return self._supported_options['register']

    @property
    def discovery_supp(self):
        ''' This option adds support for TP8013 '''
        return self._supported_options['discovery']

    @property
    def host_iface_supp(self):
        ''' This option allows forcing connections to go over
            a specific interface regardless of the routing tables.
        '''
        return self._supported_options['host_iface']

NVME_OPTIONS = NvmeOptions()

#*******************************************************************************
class GTimer:
    ''' @brief Convenience class to wrap GLib timers
    '''
    def __init__(self, interval_sec:float=0, user_cback=lambda: GLib.SOURCE_REMOVE, *user_data, priority=GLib.PRIORITY_DEFAULT):
        self._source       = None
        self._interval_sec = float(interval_sec)
        self._user_cback   = user_cback
        self._user_data    = user_data
        self._priority     = priority if priority is not None else GLib.PRIORITY_DEFAULT

    def _release_resources(self):
        self.stop()
        self._user_cback = None
        self._user_data  = None

    def kill(self):
        ''' @brief Used to release all resources associated with a timer.
        '''
        self._release_resources()

    def __str__(self):
        if self._source is not None:
            return f'{self._interval_sec}s [{self.time_remaining()}s]'

        return f'{self._interval_sec}s [off]'

    def _callback(self, *_):
        retval = self._user_cback(*self._user_data)
        if retval == GLib.SOURCE_REMOVE:
            self._source = None
        return retval

    def stop(self):
        ''' @brief Stop timer
        '''
        if self._source is not None:
            self._source.destroy()
            self._source = None

    def start(self, new_interval_sec:float=-1.0):
        ''' @brief Start (or restart) timer
        '''
        if new_interval_sec >= 0:
            self._interval_sec = float(new_interval_sec)

        if self._source is not None:
            self._source.set_ready_time(self._source.get_time() + (self._interval_sec * 1000000)) # ready time is in micro-seconds (monotonic time)
        else:
            if self._interval_sec.is_integer():
                self._source = GLib.timeout_source_new_seconds(int(self._interval_sec)) # seconds resolution
            else:
                self._source = GLib.timeout_source_new(self._interval_sec * 1000.0)     # mili-seconds resolution

            self._source.set_priority(self._priority)
            self._source.set_callback(self._callback)
            self._source.attach()

    def clear(self):
        ''' @brief Make timer expire now. The callback function
                   will be invoked immediately by the main loop.
        '''
        if self._source is not None:
            self._source.set_ready_time(0) # Expire now!

    def set_callback(self, user_cback, *user_data):
        self._user_cback = user_cback
        self._user_data  = user_data

    def set_timeout(self, new_interval_sec:float):
        if new_interval_sec >= 0:
            self._interval_sec = float(new_interval_sec)

    def get_timeout(self):
        return self._interval_sec

    def time_remaining(self) -> float:
        ''' @brief Get how much time remains on a timer before it fires.
        '''
        if self._source is not None:
            delta_us = self._source.get_ready_time() - self._source.get_time() # monotonic time in micro-seconds
            if delta_us > 0:
                return delta_us / 1000000.0

        return 0

#*******************************************************************************
class Udev:
    ''' @brief Udev event monitor. Provide a way to register for udev events.
    '''
    def __init__(self):
        self._registry = dict()
        self._context  = pyudev.Context()
        self._monitor  = pyudev.Monitor.from_netlink(self._context)
        self._monitor.filter_by(subsystem='nvme')
        self._observer = MonitorObserver(self._monitor)
        self._sig_id   = self._observer.connect('device-event', self._device_event)
        self._monitor.start()

        atexit.register(self._release_resources) # Make sure resources are released on exit

    def _release_resources(self):
        atexit.unregister(self._release_resources)
        if self._sig_id is not None:
            self._observer.disconnect(self._sig_id)
            self._sig_id = None
        self._observer = None

        if self._monitor is not None:
            self._monitor.remove_filter()
            self._monitor = None

        self._context  = None
        self._registry = None

    def get_nvme_device(self, sys_name):
        ''' @brief Get the udev device object associated with an nvme device.
            @param sys_name: The device system name (e.g. 'nvme1')
            @return A pyudev.device._device.Device object
        '''
        device_node = os.path.join('/dev', sys_name)
        try:
            return pyudev.Devices.from_device_file(self._context, device_node)
        except pyudev.DeviceNotFoundByFileError as ex:
            LOG.error("Udev.get_nvme_device() - Error: %s", ex)
            return None

    def register_for_events(self, sys_name:str, user_cback):
        ''' @brief Register a callback function to be called when udev events
                   are received for a specific nvme device.
            @param sys_name: The device system name (e.g. 'nvme1')
        '''
        if sys_name:
            self._registry[sys_name] = user_cback

    def unregister_for_events(self, user_cback):
        ''' @brief The opposite of register_for_events()
        '''
        entries = list(self._registry.items())
        for sys_name, _user_cback in entries:
            if user_cback == _user_cback:
                self._registry.pop(sys_name, None)
                break

    def get_attributes(self, sys_name:str, attr_ids):
        attrs = { attr_id: '' for attr_id in attr_ids }
        if sys_name:
            udev = self.get_nvme_device(sys_name)
            if udev is not None:
                for attr_id in attr_ids:
                    try:
                        value = udev.attributes.asstring(attr_id).strip()
                        attrs[attr_id] = '' if value == '(efault)' else value
                    except Exception: # pylint: disable=broad-except
                        pass

        return attrs

    def find_nvme_dc_device(self, tid):
        ''' @brief  Find the nvme device associated with the specified
                    Discovery Controller.
            @return The device if a match is found, None otherwise.
        '''
        for device in self._context.list_devices(subsystem='nvme', NVME_TRADDR=tid.traddr, NVME_TRSVCID=tid.trsvcid, NVME_TRTYPE=tid.transport):
            # Discovery Controllers have no children devices
            if len(list(device.children)) != 0:
                continue

            if self._get_tid(device) != tid:
                continue

            return device

        return None

    def find_nvme_ioc_device(self, tid):
        for device in self._context.list_devices(subsystem='nvme', NVME_TRADDR=tid.traddr, NVME_TRSVCID=tid.trsvcid, NVME_TRTYPE=tid.transport):
            # I/O Controllers have children devices
            if len(list(device.children)) == 0:
                continue

            if self._get_tid(device) != tid:
                continue

            return device

        return None

    def _device_event(self, _observer, device):
        user_cback = self._registry.get(device.sys_name, None)
        if user_cback is not None:
            user_cback(device)

    @staticmethod
    def _get_property(device, prop, default=''):
        prop = device.properties.get(prop, default)
        return '' if prop.lower() == 'none' else prop

    @staticmethod
    def _get_attribute(device, attr_id, default=''):
        try:
            attr = device.attributes.asstring(attr_id).strip()
        except Exception: # pylint: disable=broad-except
            attr = default

        return '' if attr.lower() == 'none' else attr

    @staticmethod
    def _get_tid(device):
        cid = {
            'transport':   Udev._get_property(device, 'NVME_TRTYPE'),
            'traddr':      Udev._get_property(device, 'NVME_TRADDR'),
            'trsvcid':     Udev._get_property(device, 'NVME_TRSVCID'),
            'host-traddr': Udev._get_property(device, 'NVME_HOST_TRADDR'),
            'host-iface':  Udev._get_property(device, 'NVME_HOST_IFACE'),
            'subsysnqn':   Udev._get_attribute(device, 'subsysnqn'),
        }
        return TransportId(cid)

UDEV = Udev() # Singleton

#*******************************************************************************
def cid_from_dlpe(dlpe, host_traddr, host_iface):
    return {
        'transport':   dlpe['trtype'],
        'traddr':      dlpe['traddr'],
        'trsvcid':     dlpe['trsvcid'],
        'host-traddr': host_traddr,
        'host-iface':  host_iface,
        'subsysnqn':   dlpe['subnqn'],
    }

#*******************************************************************************
def blacklisted(blacklisted_ctrl_list, controller):
    for blacklisted_ctrl in blacklisted_ctrl_list:
        test_results = [ val == controller.get(key, None) for key, val in blacklisted_ctrl.items() ]
        if all(test_results):
            return True
    return False

#*******************************************************************************
def remove_blacklisted(controllers:list):
    blacklisted_ctrl_list = CNF.get_blacklist()
    if blacklisted_ctrl_list:
        LOG.debug('remove_blacklisted()               - blacklisted_ctrl_list = %s', blacklisted_ctrl_list)
        controllers = [ controller for controller in controllers if not blacklisted(blacklisted_ctrl_list, controller) ]
    return controllers

#*******************************************************************************
class TransportId:
    # pylint: disable=too-many-instance-attributes
    ''' Transport Identifier
    '''
    RDMA_IP_PORT = '4420'
    DISC_IP_PORT = '8009'

    def __init__(self, cid:dict):
        ''' @param cid: Controller Identifier. A dictionary with the following
                        contents.
                        {
                            'transport':   str, # [mandatory]
                            'traddr':      str, # [mandatory]
                            'subsysnqn':   str, # [mandatory]
                            'trsvcid':     str, # [optional]
                            'host-traddr': str, # [optional]
                            'host-iface':  str, # [optional]
                        }
        '''
        self._transport   = cid.get('transport')
        self._traddr      = cid.get('traddr')
        trsvcid = cid.get('trsvcid')
        self._trsvcid     = trsvcid if trsvcid else (TransportId.RDMA_IP_PORT if self._transport == 'rdma' else TransportId.DISC_IP_PORT) # pylint: disable=used-before-assignment
        self._host_traddr = cid.get('host-traddr', '')
        self._host_iface  = cid.get('host-iface', '')
        self._subsysnqn   = cid.get('subsysnqn')
        self._key         = (self._transport, self._traddr, self._trsvcid, self._host_traddr, self._host_iface, self._subsysnqn)
        self._hash        = hash(self._key)
        self._id = f'({self._transport}, {self._traddr}, {self._trsvcid}{", " + self._subsysnqn if self._subsysnqn else ""}{", " + self._host_iface if self._host_iface else ""}{", " + self._host_traddr if self._host_traddr else ""})'

    @property
    def key(self):
        return self._key

    @property
    def hash(self):
        return self._hash

    @property
    def transport(self):
        return self._transport

    @property
    def traddr(self):
        return self._traddr

    @property
    def trsvcid(self):
        return self._trsvcid

    @property
    def host_traddr(self):
        return self._host_traddr

    @property
    def host_iface(self):
        return self._host_iface

    @property
    def subsysnqn(self):
        return self._subsysnqn

    def as_dict(self):
        return {
            'transport': self.transport,
            'traddr': self.traddr,
            'trsvcid': self.trsvcid,
            'host-traddr': self.host_traddr,
            'host-iface': self.host_iface,
            'subsysnqn': self.subsysnqn,
        }

    def __str__(self):
        return self._id

    def __repr__(self):
        return self._id

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.key == other.key

    def __ne__(self, other):
        return not isinstance(other, self.__class__) or self.key != other.key

    def __hash__(self):
        return self.hash

#*******************************************************************************
class NameResolver:
    # pylint: disable=too-few-public-methods
    ''' @brief DNS resolver to convert host names to IP addresses.
    '''
    def __init__(self):
        self._resolver = Gio.Resolver.get_default()

    def resolve_ctrl_async(self, cancellable, controllers:dict, callback):
        ''' @brief The traddr fields may specify a hostname instead of an IP
                   address. We need to resolve all the host names to addresses.
                   Resolving hostnames may take a while as a DNS server may need
                   to be contracted. For that reason we're using async APIs with
                   callbacks to resolve all the hostnames.

                   The callback @callback will be called once all hostnames have
                   been resolved.
        '''
        pending_resolution_count = 0

        def addr_resolved(resolver, result, indx):
            hostname = controllers[indx]['traddr']
            traddr = None
            try:
                addresses = resolver.lookup_by_name_finish(result)
                if addresses:
                    traddr = addresses[0].to_string()
                else:
                    LOG.error('Cannot resolve traddr: %s', hostname)

            except GLib.GError:
                LOG.error('Cannot resolve traddr: %s', hostname)

            LOG.debug('NameResolver.resolve_ctrl_async()  - resolved \'%s\' -> %s', hostname, traddr)
            controllers[indx]['traddr'] = traddr

            # Invoke callback after all hostnames have been resolved
            nonlocal pending_resolution_count
            pending_resolution_count -= 1
            if pending_resolution_count == 0:
                callback(controllers)

        for indx, controller in enumerate(controllers):
            if controller.get('transport') in ('tcp', 'rdma'):
                hostname = controller.get('traddr')
                if not hostname:
                    LOG.error('Invalid traddr: %s', controller)
                else:
                    LOG.debug('NameResolver.resolve_ctrl_async()  - resolving \'%s\'', hostname)
                    pending_resolution_count += 1
                    self._resolver.lookup_by_name_async(hostname, cancellable, addr_resolved, indx)

        if pending_resolution_count == 0: # No names are pending asynchronous resolution
            callback(controllers)


#*******************************************************************************
class AsyncCaller(GObject.Object):
    ''' @brief This class allows running methods asynchronously in a thread.
    '''
    def __init__(self, user_function, *user_args):
        ''' @param user_function: function to run inside a thread
            @param user_args: arguments passed to @user_function
        '''
        super().__init__()
        self._user_function = user_function
        self._user_args     = user_args

    def communicate(self, cancellable, cb_function, *cb_args):
        ''' @param cancellable: A Gio.Cancellable object that can be used to
                                cancel an in-flight async command.
            @param cb_function: User callback function to call when the async
                                command has completed.  The callback function
                                will be passed these arguments:

                                    (async_caller_obj, result, *cb_args)

                                Where:
                                    async_caller_obj: This AsyncCaller object instance
                                    result: A GObject.Object instance that contains the result
                                    cb_args: The cb_args arguments passed to communicate()

            @param cb_args: User arguments to pass to @cb_function
        '''
        def in_thread_exec(task, self, task_data, cancellable): # pylint: disable=unused-argument
            if task.return_error_if_cancelled():
                return # Bail out if task has been cancelled

            try:
                value = GObject.Object()
                value.result = self._user_function(*self._user_args)
                task.return_value(value)
            except Exception as ex: # pylint: disable=broad-except
                task.return_error(GLib.Error(repr(ex)))

        task = Gio.Task.new(self, cancellable, cb_function, *cb_args)
        task.set_return_on_cancel(False)
        task.run_in_thread(in_thread_exec)

    def communicate_finish(self, result): # pylint: disable=no-self-use
        ''' @brief Use this function in your callback (see @cb_function) to
                   extract data from the result object.

            @return A tuple: (success, data, errmsg)
        '''
        try:
            success, value = result.propagate_value()
            return success, value.result, None
        except GLib.Error as err:
            return False, None, err

#*******************************************************************************
class AsyncOperationWithRetry: # pylint: disable=too-many-instance-attributes
    def __init__(self, on_success_callback, on_failure_callback, operation, *op_args):
        ''' @param on_success_callback: Callback method invoked when @operation completes successfully
            @param on_failure_callback: Callback method invoked when @operation fails
            @param operation: Operation (i.e. a function) to execute asynchronously
            @param op_args: Arguments passed to operation
        '''
        self._cancellable = Gio.Cancellable()
        self._operation   = operation
        self._op_args     = op_args
        self._success_cb  = on_success_callback
        self._fail_cb     = on_failure_callback
        self._retry_tmr   = None
        self._errmsg      = None
        self._fail_cnt    = 0

    def _release_resources(self):
        if not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        if self._retry_tmr is not None:
            self._retry_tmr.kill()

        self._operation  = None
        self._op_args    = None
        self._success_cb = None
        self._fail_cb    = None
        self._retry_tmr  = None
        self._errmsg     = None
        self._fail_cnt   = None

    def __str__(self):
        return str(self.as_dict())

    def as_dict(self):
        info = {
            'fail count': self._fail_cnt,
        }

        if self._retry_tmr:
            info['retry timer'] = str(self._retry_tmr)

        if self._errmsg:
            info['error'] = self._errmsg

        return info

    def cancel(self):
        if not self._cancellable.is_cancelled():
            self._cancellable.cancel()

    def kill(self):
        self._release_resources()

    def run_async(self, *args):
        ''' @brief
                Method used to initiate an asynchronous operation with the
                Controller. When the operation completes (or fails) the
                callback method @_on_operation_complete() will be invoked.
        '''
        async_caller = AsyncCaller(self._operation, *self._op_args)
        async_caller.communicate(self._cancellable, self._on_operation_complete, *args)

    def retry(self, interval_sec, *args):
        if self._retry_tmr is None:
            self._retry_tmr = GTimer()
        self._retry_tmr.set_callback(self._on_retry_timeout, *args)
        self._retry_tmr.start(interval_sec)

    def _on_retry_timeout(self, *args):
        ''' @brief
                When an operation fails, the application has the option to
                retry at a later time by calling the retry() method. The
                retry() method starts a timer at the end of which the operation
                will be executed again. This is the method that is called when
                the timer expires.
        '''
        self.run_async(*args)
        return GLib.SOURCE_REMOVE

    def _on_operation_complete(self, async_caller, result, *args):
        ''' @brief
                This callback method is invoked when the operation with the
                Controller has completed (be it successful or not).
        '''
        success, data, err = async_caller.communicate_finish(result)

        # The operation might have been cancelled.
        # Only proceed if it hasn't been cancelled.
        if self._operation is None or self._cancellable.is_cancelled():
            return

        if success:
            self._errmsg = None
            self._fail_cnt = 0
            self._success_cb(self, data, *args)
        else:
            self._errmsg = str(err)
            self._fail_cnt += 1
            self._fail_cb(self, err, self._fail_cnt, *args)


#*******************************************************************************
class Controller:
    NVME_ROOT = nvme.root()          # Singleton
    NVME_HOST = nvme.host(NVME_ROOT) # Singleton
    CONNECT_RETRY_PERIOD_SEC = 60
    def __init__(self, tid:TransportId, discovery_ctrl=False, register=False):
        self._tid               = tid
        self._cancellable       = Gio.Cancellable()
        self._connect_op        = None
        self._connect_attempts  = 0
        self._retry_connect_tmr = GTimer(Controller.CONNECT_RETRY_PERIOD_SEC, self._on_try_to_connect)
        self._device            = None
        self._ctrl              = None
        self._discovery_ctrl    = discovery_ctrl
        self._register          = register

        # Defer attempt to connect to the next main loop's idle period.
        GLib.idle_add(self._try_to_connect)

    def _release_resources(self):
        LOG.debug('Controller._release_resources()    - %s', self.id)

        device = self.device
        if device:
            UDEV.unregister_for_events(self._on_udev_notification)

        self._retry_connect_tmr.kill()

        if not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        self._kill_ops()

        self._tid               = None
        self._ctrl              = None
        self._device            = None
        self._retry_connect_tmr = None

    def _alive(self):
        ''' There may be race condition where a queued event gets processed
            after the object is no longer configured (i.e. alive). This method
            can be used by callback functions to make sure the object is still
            alive before processing further.
        '''
        return not self._cancellable.is_cancelled()

    def _kill_ops(self):
        if self._connect_op:
            self._connect_op.kill()
            self._connect_op = None

    def _on_udev_notification(self, udev):
        if self._alive():
            if udev.action == 'change':
                LOG.info('%s | %s - Received "change" notification.', self.id, udev.sys_name)
                self._on_udev_change(udev)
            elif udev.action == 'remove':
                LOG.info('%s | %s - Received "remove" notification.', self.id, udev.sys_name)
                self._on_udev_remove(udev)
            else:
                LOG.debug('Controller._on_udev_notification() - %s | %s - Received "%s" notification.',
                          self.id, udev.sys_name, udev.action)
        else:
            LOG.debug('Controller._on_udev_notification() - %s | %s - Received event on dead object. udev %s: %s',
                      self.id, self.device, udev.action, udev.sys_name)

    def _on_udev_change(self, udev):
        pass

    def _on_udev_remove(self, udev): # pylint: disable=unused-argument
        UDEV.unregister_for_events(self._on_udev_notification)
        self._kill_ops() # Kill all pending operations
        self._ctrl = None

    def _find_existing_connection(self):
        raise NotImplementedError()

    def _on_try_to_connect(self):
        self._try_to_connect()
        return GLib.SOURCE_REMOVE

    def _try_to_connect(self):
        self._connect_attempts += 1

        host_iface = self.tid.host_iface if self.tid.host_iface and NVME_OPTIONS.host_iface_supp else None
        self._ctrl = nvme.ctrl(subsysnqn=self.tid.subsysnqn,
                               transport=self.tid.transport,
                               traddr=self.tid.traddr,
                               trsvcid=self.tid.trsvcid,
                               host_traddr=self.tid.host_traddr if self.tid.host_traddr else None,
                               host_iface=host_iface)
        self._ctrl.discovery_ctrl_set(self._discovery_ctrl)
        self._ctrl.persistent_set(True)
        self._ctrl.explicit_registration_set(self._register)

        # Audit existing nvme devices. If we find a match, then
        # we'll just borrow that device instead of creating a new one.
        udev = self._find_existing_connection()
        if udev is not None:
            # A device already exists.
            self._device = udev.sys_name
            LOG.debug('Controller._try_to_connect()       - %s Found existing control device: %s', self.id, udev.sys_name)
            self._connect_op = AsyncOperationWithRetry(self._on_connect_success, self._on_connect_fail,
                                                       self._ctrl.init, Controller.NVME_HOST, int(udev.sys_number))
        else:
            self._device = None
            cfg = { 'hdr_digest':  CNF.hdr_digest,
                    'data_digest': CNF.data_digest }
            if CNF.kato is not None:
                cfg['keep_alive_tmo'] = CNF.kato
            LOG.debug('Controller._try_to_connect()       - %s Connecting to nvme control with cfg=%s', self.id, cfg)
            self._connect_op = AsyncOperationWithRetry(self._on_connect_success, self._on_connect_fail,
                                                       self._ctrl.connect, Controller.NVME_HOST, cfg)

        self._connect_op.run_async()

    #--------------------------------------------------------------------------
    def _on_connect_success(self, op_obj, data):
        ''' @brief Function called when we successfully connect to the
                   Controller.
        '''
        op_obj.kill()
        self._connect_op = None

        if self._alive():
            if not self._device:
                self._device = self._ctrl.name
            LOG.info('%s | %s - Connection established!', self.id, self.device)
            self._connect_attempts = 0
            UDEV.register_for_events(self.device, self._on_udev_notification)
        else:
            LOG.debug('Controller._on_connect_success()   - %s | %s Received event on dead object. data=%s',
                      self.id, self.device, data)

    def _on_connect_fail(self, op_obj, err, fail_cnt): # pylint: disable=unused-argument
        ''' @brief Function called when we fail to connect to the Controller.
        '''
        op_obj.kill()
        if self._alive():
            LOG.debug('Controller._on_connect_fail()      - %s %s. Retry in %s sec.',
                      self.id, err, self._retry_connect_tmr.get_timeout())
            if self._connect_attempts == 1: # Throttle the logs. Only print the first time we fail to connect
                LOG.error('%s Failed to connect to controller. %s', self.id, err)
            self._retry_connect_tmr.start()
        else:
            LOG.debug('Controller._on_connect_fail()      - %s Received event on dead object. %s', self.id, err)

    @property
    def id(self) -> str:
        return str(self.tid)

    @property
    def tid(self):
        return self._tid

    @property
    def device(self) -> str:
        return self._device if self._device else ''

    def controller_id_dict(self) -> dict:
        cid = self.tid.as_dict()
        cid['device'] = self.device
        return cid

    def details(self) -> dict:
        details = self.controller_id_dict()
        details.update(UDEV.get_attributes(self.device, ('hostid', 'hostnqn', 'model', 'serial')))
        details['connect attempts'] = self._connect_attempts
        details['retry connect timer'] = str(self._retry_connect_tmr)
        return details

    def info(self) -> dict:
        ''' @brief Get the controller info for this object
        '''
        info = self.details()
        if self._connect_op:
            info['connect operation'] = self._connect_op.as_dict()
        return info

    def cancel(self):
        ''' @brief Used to cancel pending operations.
        '''
        if not self._cancellable.is_cancelled():
            LOG.debug('Controller.cancel()                - %s', self.id)
            self._cancellable.cancel()

        if self._connect_op:
            self._connect_op.cancel()

    def disconnect(self, disconnected_cb):
        LOG.info('%s | %s - Disconnect initiated', self.id, self.device)
        self._kill_ops()
        # Defer callback to the next main loop's idle period.
        GLib.idle_add(disconnected_cb, self.tid)

    def kill(self):
        ''' @brief Used to release all resources associated with this object.
        '''
        LOG.debug('Controller.kill()                  - %s', self.id)
        self._release_resources()

#*******************************************************************************
class Service:
    def __init__(self, reload_hdlr):
        self._loop         = GLib.MainLoop()
        self._cancellable  = Gio.Cancellable()
        self._resolver     = NameResolver()
        self._controllers  = dict()
        self._dbus_iface   = None
        self._cfg_soak_tmr = None
        self._sysbus       = dasbus.connection.SystemMessageBus()

        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, self._stop_hdlr)  # CTRL-C
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self._stop_hdlr) # systemctl stop stafd
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGHUP, reload_hdlr)      # systemctl reload stafd

        if not NVME_OPTIONS.host_iface_supp:
            LOG.warning('Kernel does not appear to support all the options needed to run this program. Consider updating to a later kernel version.')

    def _release_resources(self):
        LOG.debug('Service._release_resources()')

        if not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        if self._cfg_soak_tmr is not None:
            self._cfg_soak_tmr.kill()

        self._controllers.clear()

        self._sysbus.disconnect()

        self._cfg_soak_tmr = None
        self._resolver     = None
        self._sysbus       = None

    def _config_dbus(self, iface_obj, bus_name:str, obj_name:str):
        self._dbus_iface = iface_obj
        self._sysbus.publish_object(obj_name, iface_obj)
        self._sysbus.register_service(bus_name)

    def run(self):
        ''' @brief Start the main loop execution
        '''
        try:
            self._loop.run()
        except Exception as ex: # pylint: disable=broad-except
            LOG.critical('exception: %s', ex)

        self._loop = None

    def info(self) -> dict:
        ''' @brief Get the status info for this object (used for debug)
        '''
        return {
            'config soak timer': str(self._cfg_soak_tmr),
            'kernel support': {
                'TP8010':     NVME_OPTIONS.register_supp,
                'TP8013':     NVME_OPTIONS.discovery_supp,
                'host_iface': NVME_OPTIONS.host_iface_supp,
            },
        }

    def get_controllers(self):
        ''' @brief return the list of controller objects
        '''
        return self._controllers.values()

    def get_controller(self, transport:str, traddr:str, trsvcid:str, host_traddr:str, host_iface:str, subsysnqn:str): # pylint: disable=too-many-arguments
        cid = {
            'transport': transport,
            'traddr': traddr,
            'trsvcid': trsvcid,
            'host-traddr': host_traddr,
            'host-iface': host_iface,
            'subsysnqn': subsysnqn,
        }
        return self._controllers.get(TransportId(cid))

    def remove_controller(self, tid, device):
        LOG.debug('Service.remove_controller()        - %s %s', tid, device)
        controller = self._controllers.pop(tid, None)
        if controller is not None:
            controller.kill()

        if self._cfg_soak_tmr:
            self._cfg_soak_tmr.start()

    def _cancel(self):
        LOG.debug('Service._cancel()')
        if not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        for controller in self._controllers.values():
            controller.cancel()

    def _stop_hdlr(self):
        systemd.daemon.notify('STOPPING=1')

        self._cancel() # Cancel pending operations

        if len(self._controllers) == 0:
            GLib.idle_add(self._exit)
        else:
            # Tell all controller objects to disconnect
            controllers = self._controllers.values()
            for controller in controllers:
                controller.disconnect(self._on_ctrl_disconnected)

        return GLib.SOURCE_REMOVE

    def _on_ctrl_disconnected(self, tid):
        LOG.debug('Service._on_ctrl_disconnected()    - %s', tid)
        controller = self._controllers.pop(tid, None)
        if controller is not None:
            controller.kill()

        # When all controllers have disconnected, we can finish the clean up
        if len(self._controllers) == 0:
            # Defer exit to the next main loop's idle period.
            GLib.idle_add(self._exit)

    def _exit(self):
        LOG.debug('Service._exit()')
        self._release_resources()
        self._loop.quit()

    def _on_config_ctrls(self, *_user_data):
        self._config_ctrls()
        return GLib.SOURCE_REMOVE

    def _config_ctrls(self):
        ''' @brief Start controllers configuration.
        '''
        # The configuration file may contain controllers and/or blacklist
        # elements with traddr specified as hostname instead of IP address.
        # Because of this, we need to remove those blacklisted elements before
        # running name resolution. And we will need to remove blacklisted
        # elements after name resolution is complete (i.e. in the calback
        # function _config_ctrls_finish)
        configured_controllers = remove_blacklisted(CNF.get_controllers())
        self._resolver.resolve_ctrl_async(self._cancellable, configured_controllers, self._config_ctrls_finish)

    def _config_ctrls_finish(self, configured_ctrl_list):
        raise NotImplementedError()
