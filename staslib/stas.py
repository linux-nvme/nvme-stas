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
import re
import sys
import signal
import hashlib
import logging
import configparser
import platform
import ipaddress
import pyudev
import systemd.daemon
import dasbus.connection

from gi.repository import Gio, GLib, GObject
from libnvme import nvme
from staslib.version import KernelVersion
from staslib import defs

try:
    from pyudev.glib import MonitorObserver
except (ModuleNotFoundError, AttributeError):
    from staslib.glibudev import MonitorObserver  # pylint: disable=relative-beyond-top-level,ungrouped-imports


DC_KATO_DEFAULT = 30  # seconds

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
        sys.exit(f'Permission denied. You need root privileges to run {os.path.basename(sys.argv[0])}.')

    # 2) Check that nvme-tcp kernel module is running
    if not os.path.exists('/dev/nvme-fabrics'):
        # There's no point going any further if the kernel module hasn't been loaded
        sys.exit('Fatal error: missing nvme-tcp kernel module')


# ******************************************************************************
LOG = logging.getLogger(__name__)  # Singleton
LOG.propagate = False


def get_log_handler(syslog: bool, identifier: str):
    '''Instantiate and return a log handler'''
    if syslog:
        try:
            # Try journal logger first
            import systemd.journal  # pylint: disable=redefined-outer-name,import-outside-toplevel

            handler = systemd.journal.JournalHandler(SYSLOG_IDENTIFIER=identifier)
        except ModuleNotFoundError:
            # Go back to standard syslog handler
            from logging.handlers import SysLogHandler  # pylint: disable=import-outside-toplevel

            handler = SysLogHandler(address="/dev/log")
            handler.setFormatter(
                logging.Formatter('{}: %(message)s'.format(identifier))  # pylint: disable=consider-using-f-string
            )
    else:
        # Log to stdout
        handler = logging.StreamHandler(stream=sys.stdout)

    return handler


def log_level() -> str:
    '''@brief return current log level'''
    return str(logging.getLevelName(LOG.getEffectiveLevel()))


# ******************************************************************************
TRON = False  # Singleton


def trace_control(tron: bool):
    '''@brief Allows changing debug level in real time. Setting tron to True
    enables full tracing.
    '''
    global TRON  # pylint: disable=global-statement
    TRON = tron
    LOG.setLevel(logging.DEBUG if TRON else logging.INFO)


# ******************************************************************************
TOKEN_RE = re.compile(r'\s*;\s*')
OPTION_RE = re.compile(r'\s*=\s*')


def parse_controller(controller):
    '''@brief Parse a "controller" entry. Controller entries are strings
           composed of several configuration parameters delimited by
           semi-colons. Each configuration parameter is specified as a
           "key=value" pair.
    @return A dictionary of key-value pairs.
    '''
    options = dict()
    tokens = TOKEN_RE.split(controller)
    for token in tokens:
        if token:
            try:
                option, val = OPTION_RE.split(token)
                options[option] = val
            except ValueError:
                pass

    return options


# ******************************************************************************
class OrderedMultisetDict(dict):
    '''This class is used to change the behavior of configparser.ConfigParser
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
    '''Read and cache configuration file.'''

    def __init__(self, conf_file='/dev/null'):
        self._defaults = {
            ('Global', 'tron'): 'false',
            ('Global', 'persistent-connections'): 'true',
            ('Global', 'hdr-digest'): 'false',
            ('Global', 'data-digest'): 'false',
            ('Global', 'kato'): None,
            ('Global', 'ignore-iface'): 'false',
            ('Global', 'ip-family'): 'ipv4+ipv6',
            ('Global', 'udev-rule'): 'enabled',
            ('Global', 'sticky-connections'): 'disabled',
            ('Service Discovery', 'zeroconf'): 'enabled',
            ('Controllers', 'controller'): list(),
            ('Controllers', 'blacklist'): list(),
        }
        self._conf_file = conf_file
        self.reload()

    def reload(self):
        '''@brief Reload the configuration file.'''
        self._config = self.read_conf_file()

    @property
    def conf_file(self):  # pylint: disable=missing-function-docstring
        return self._conf_file

    @conf_file.setter
    def conf_file(self, fname):  # pylint: disable=missing-function-docstring
        self._conf_file = fname
        self.reload()

    @property
    def tron(self):
        '''@brief return the "tron" config parameter'''
        return self.__get_bool('Global', 'tron')

    @property
    def hdr_digest(self):
        '''@brief return the "hdr-digest" config parameter'''
        return self.__get_bool('Global', 'hdr-digest')

    @property
    def data_digest(self):
        '''@brief return the "data-digest" config parameter'''
        return self.__get_bool('Global', 'data-digest')

    @property
    def persistent_connections(self):
        '''@brief return the "persistent-connections" config parameter'''
        return self.__get_bool('Global', 'persistent-connections')

    @property
    def ignore_iface(self):
        '''@brief return the "ignore-iface" config parameter'''
        return self.__get_bool('Global', 'ignore-iface')

    @property
    def ip_family(self):
        '''@brief return the "ip-family" config parameter.
        @rtype tuple
        '''
        family = self.__get_value('Global', 'ip-family')[0]

        if family == 'ipv4':
            return (4,)
        if family == 'ipv6':
            return (6,)

        return (4, 6)

    @property
    def udev_rule_enabled(self):
        '''@brief return the "udev-rule" config parameter'''
        return self.__get_value('Global', 'udev-rule')[0] == 'enabled'

    @property
    def sticky_connections(self):
        '''@brief return the "sticky-connections" config parameter'''
        return self.__get_value('Global', 'sticky-connections')[0] == 'enabled'

    @property
    def kato(self):
        '''@brief return the "kato" config parameter'''
        kato = self.__get_value('Global', 'kato')[0]
        return None if kato is None else int(kato)

    def get_controllers(self):
        '''@brief Return the list of controllers in the config file.
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
        controllers = [parse_controller(controller) for controller in controller_list]
        for controller in controllers:
            try:
                # replace 'nqn' key by 'subsysnqn', if present.
                controller['subsysnqn'] = controller.pop('nqn')
            except KeyError:
                pass
        return controllers

    def get_blacklist(self):
        '''@brief Return the list of blacklisted controllers in the config file.
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
        blacklist = [parse_controller(controller) for controller in controller_list]
        for controller in blacklist:
            controller.pop('host-traddr', None)  # remove host-traddr
            try:
                # replace 'nqn' key by 'subsysnqn', if present.
                controller['subsysnqn'] = controller.pop('nqn')
            except KeyError:
                pass
        return blacklist

    def get_stypes(self):
        '''@brief Get the DNS-SD/mDNS service types.'''
        return ['_nvme-disc._tcp'] if self.zeroconf_enabled() else list()

    def zeroconf_enabled(self):  # pylint: disable=missing-function-docstring
        return self.__get_value('Service Discovery', 'zeroconf')[0] == 'enabled'

    def read_conf_file(self):
        '''@brief Read the configuration file if the file exists.'''
        config = configparser.ConfigParser(
            default_section=None,
            allow_no_value=True,
            delimiters=('='),
            interpolation=None,
            strict=False,
            dict_type=OrderedMultisetDict,
        )
        if self._conf_file and os.path.isfile(self._conf_file):
            config.read(self._conf_file)
        return config

    def __get_bool(self, section, option):
        return self.__get_value(section, option)[0] == 'true'

    def __get_value(self, section, option):
        try:
            value = self._config.get(section=section, option=option)
        except (configparser.NoSectionError, configparser.NoOptionError, KeyError):
            value = self._defaults.get((section, option), [])
            if not isinstance(value, list):
                value = [value]
        return value if value is not None else list()


CNF = Configuration()  # Singleton


# ******************************************************************************
class SysConfiguration:
    '''Read and cache the host configuration file.'''

    def __init__(self, conf_file='/dev/null'):
        self._conf_file = conf_file
        self.reload()

    def reload(self):
        '''@brief Reload the configuration file.'''
        self._config = self.read_conf_file()

    @property
    def conf_file(self):  # pylint: disable=missing-function-docstring
        return self._conf_file

    @conf_file.setter
    def conf_file(self, fname):  # pylint: disable=missing-function-docstring
        self._conf_file = fname
        self.reload()

    def as_dict(self):  # pylint: disable=missing-function-docstring
        return {
            'hostnqn': self.hostnqn,
            'hostid': self.hostid,
            'symname': self.hostsymname,
        }

    @property
    def hostnqn(self):
        '''@brief return the host NQN
        @return: Host NQN
        @raise: Host NQN is mandatory. The program will terminate if a
                Host NQN cannot be determined.
        '''
        try:
            value = self.__get_value('Host', 'nqn', '/etc/nvme/hostnqn')
        except FileNotFoundError as ex:
            sys.exit(f'Error reading mandatory Host NQN (see stasadm --help): {ex}')

        if not value.startswith('nqn.'):
            sys.exit(f'Error Host NQN "{value}" should start with "nqn."')

        return value

    @property
    def hostid(self):
        '''@brief return the host ID
        @return: Host ID
        @raise: Host ID is mandatory. The program will terminate if a
                Host ID cannot be determined.
        '''
        try:
            value = self.__get_value('Host', 'id', '/etc/nvme/hostid')
        except FileNotFoundError as ex:
            sys.exit(f'Error reading mandatory Host ID (see stasadm --help): {ex}')

        return value

    @property
    def hostsymname(self):
        '''@brief return the host symbolic name (or None)
        @return: symbolic name or None
        '''
        try:
            value = self.__get_value('Host', 'symname')
        except FileNotFoundError as ex:
            LOG.warning('Error reading host symbolic name (will remain undefined): %s', ex)
            value = None

        return value

    def read_conf_file(self):
        '''@brief Read the configuration file if the file exists.'''
        config = configparser.ConfigParser(
            default_section=None, allow_no_value=True, delimiters=('='), interpolation=None, strict=False
        )
        if os.path.isfile(self._conf_file):
            config.read(self._conf_file)
        return config

    def __get_value(self, section, option, default_file=None):
        '''@brief A configuration file consists of sections, each led by a
               [section] header, followed by key/value entries separated
               by a equal sign (=). This method retrieves the value
               associated with the key @option from the section @section.
               If the value starts with the string "file://", then the value
               will be retrieved from that file.

        @param section:      Configuration section
        @param option:       The key to look for
        @param default_file: A file that contains the default value

        @return: On success, the value associated with the key. On failure,
                 this method will return None is a default_file is not
                 specified, or will raise an exception if a file is not
                 found.

        @raise: This method will raise the FileNotFoundError exception if
                the value retrieved is a file that does not exist.
        '''
        try:
            value = self._config.get(section=section, option=option)
            if not value.startswith('file://'):
                return value
            file = value[7:]
        except (configparser.NoSectionError, configparser.NoOptionError, KeyError):
            if default_file is None:
                return None
            file = default_file

        with open(file) as f:  # pylint: disable=unspecified-encoding
            return f.readline().split()[0]


SYS_CNF = SysConfiguration('/etc/stas/sys.conf')  # Singleton


# ******************************************************************************
KERNEL_VERSION = KernelVersion(platform.release())


class NvmeOptions:  # Singleton
    '''Object used to read and cache contents of file /dev/nvme-fabrics.
    Note that this file was not readable prior to Linux 5.16.
    '''

    __instance = None
    __initialized = False

    def __init__(self):
        if self.__initialized:  # Singleton - only init once
            return

        self.__initialized = True

        # Supported options can be determined by looking at the kernel version
        # or by reading '/dev/nvme-fabrics'. The ability to read the options
        # from '/dev/nvme-fabrics' was only introduced in kernel 5.17, but may
        # have been backported to older kernels. In any case, if the kernel
        # version meets the minimum version for that option, then we don't
        # even need to read '/dev/nvme-fabrics'.
        self._supported_options = {
            'discovery': KERNEL_VERSION >= defs.KERNEL_TP8013_MIN_VERSION,
            'host_iface': KERNEL_VERSION >= defs.KERNEL_IFACE_MIN_VERSION,
        }

        # If some of the options are False, we need to check wether they can be
        # read from '/dev/nvme-fabrics'. This method allows us to determine that
        # an older kernel actually supports a specific option because it was
        # backported to that kernel.
        if not all(self._supported_options.values()):  # At least one option is False.
            try:
                with open('/dev/nvme-fabrics') as f:  # pylint: disable=unspecified-encoding
                    options = [option.split('=')[0].strip() for option in f.readline().rstrip('\n').split(',')]
            except PermissionError:  # Must be root to read this file
                raise
            except OSError:
                LOG.warning('Cannot determine which NVMe options the kernel supports')
            else:
                for option, supported in self._supported_options.items():
                    if not supported:
                        self._supported_options[option] = option in options

    def __new__(cls):
        '''This is used to make this class a singleton'''
        if cls.__instance is None:
            cls.__instance = super(NvmeOptions, cls).__new__(cls)

        return cls.__instance

    @classmethod
    def destroy(cls):
        '''This is used to destroy this singleton class'''
        cls.__instance = None
        cls.__initialized = False

    def __str__(self):
        return f'supported options: {self._supported_options}'

    @property
    def discovery_supp(self):
        '''This option adds support for TP8013'''
        return self._supported_options['discovery']

    @property
    def host_iface_supp(self):
        '''This option allows forcing connections to go over
        a specific interface regardless of the routing tables.
        '''
        return self._supported_options['host_iface']


# ******************************************************************************
class GTimer:
    '''@brief Convenience class to wrap GLib timers'''

    def __init__(
        self, interval_sec: float = 0, user_cback=lambda: GLib.SOURCE_REMOVE, *user_data, priority=GLib.PRIORITY_DEFAULT
    ):  # pylint: disable=keyword-arg-before-vararg
        self._source = None
        self._interval_sec = float(interval_sec)
        self._user_cback = user_cback
        self._user_data = user_data
        self._priority = priority if priority is not None else GLib.PRIORITY_DEFAULT

    def _release_resources(self):
        self.stop()
        self._user_cback = None
        self._user_data = None

    def kill(self):
        '''@brief Used to release all resources associated with a timer.'''
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
        '''@brief Stop timer'''
        if self._source is not None:
            self._source.destroy()
            self._source = None

    def start(self, new_interval_sec: float = -1.0):
        '''@brief Start (or restart) timer'''
        if new_interval_sec >= 0:
            self._interval_sec = float(new_interval_sec)

        if self._source is not None:
            self._source.set_ready_time(
                self._source.get_time() + (self._interval_sec * 1000000)
            )  # ready time is in micro-seconds (monotonic time)
        else:
            if self._interval_sec.is_integer():
                self._source = GLib.timeout_source_new_seconds(int(self._interval_sec))  # seconds resolution
            else:
                self._source = GLib.timeout_source_new(self._interval_sec * 1000.0)  # mili-seconds resolution

            self._source.set_priority(self._priority)
            self._source.set_callback(self._callback)
            self._source.attach()

    def clear(self):
        '''@brief Make timer expire now. The callback function
        will be invoked immediately by the main loop.
        '''
        if self._source is not None:
            self._source.set_ready_time(0)  # Expire now!

    def set_callback(self, user_cback, *user_data):
        '''@brief set the callback function to invoke when timer expires'''
        self._user_cback = user_cback
        self._user_data = user_data

    def set_timeout(self, new_interval_sec: float):
        '''@brief set the timer's duration'''
        if new_interval_sec >= 0:
            self._interval_sec = float(new_interval_sec)

    def get_timeout(self):
        '''@brief get the timer's duration'''
        return self._interval_sec

    def time_remaining(self) -> float:
        '''@brief Get how much time remains on a timer before it fires.'''
        if self._source is not None:
            delta_us = self._source.get_ready_time() - self._source.get_time()  # monotonic time in micro-seconds
            if delta_us > 0:
                return delta_us / 1000000.0

        return 0


# ******************************************************************************
class Udev:
    '''@brief Udev event monitor. Provide a way to register for udev events.'''

    def __init__(self):
        self._device_event_registry = dict()
        self._action_event_registry = dict()
        self._context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(self._context)
        self._monitor.filter_by(subsystem='nvme')
        self._observer = MonitorObserver(self._monitor)
        self._sig_id = self._observer.connect('device-event', self._device_event)
        self._monitor.start()

    def _release_resources(self):
        if self._sig_id is not None:
            self._observer.disconnect(self._sig_id)
            self._sig_id = None
        self._observer = None

        if self._monitor is not None:
            self._monitor.remove_filter()
            self._monitor = None

        self._context = None
        self._device_event_registry = None
        self._action_event_registry = None

    def clean(self):
        '''Clean up all resources'''
        self._release_resources()

    def get_nvme_device(self, sys_name):
        '''@brief Get the udev device object associated with an nvme device.
        @param sys_name: The device system name (e.g. 'nvme1')
        @return A pyudev.device._device.Device object
        '''
        device_node = os.path.join('/dev', sys_name)
        try:
            return pyudev.Devices.from_device_file(self._context, device_node)
        except pyudev.DeviceNotFoundByFileError as ex:
            LOG.error("Udev.get_nvme_device() - Error: %s", ex)
            return None

    def get_registered_action_cback(self, action: str):
        '''@brief Return the callback function registered for a specific action.
        @param action: one of 'add', 'remove', 'change'.
        '''
        return self._action_event_registry.get(action, None)

    def register_for_action_events(self, action: str, user_cback):
        '''@brief Register a callback function to be called when udev events
        for a specific action are received.
        @param action: one of 'add', 'remove', 'change'.
        '''
        if action and action not in self._action_event_registry:
            self._action_event_registry[action] = user_cback

    def unregister_for_action_events(self, action: str):
        '''@brief The opposite of register_for_action_events()'''
        self._action_event_registry.pop(action, None)

    def register_for_device_events(self, sys_name: str, user_cback):
        '''@brief Register a callback function to be called when udev events
        are received for a specific nvme device.
        @param sys_name: The device system name (e.g. 'nvme1')
        '''
        if sys_name:
            self._device_event_registry[sys_name] = user_cback

    def unregister_for_device_events(self, user_cback):
        '''@brief The opposite of register_for_device_events()'''
        entries = list(self._device_event_registry.items())
        for sys_name, _user_cback in entries:
            if user_cback == _user_cback:
                self._device_event_registry.pop(sys_name, None)
                break

    def get_attributes(self, sys_name: str, attr_ids) -> dict:
        '''@brief Get all the attributes associated with device @sys_name'''
        attrs = {attr_id: '' for attr_id in attr_ids}
        if sys_name:
            udev = self.get_nvme_device(sys_name)
            if udev is not None:
                for attr_id in attr_ids:
                    try:
                        value = udev.attributes.asstring(attr_id).strip()
                        attrs[attr_id] = '' if value == '(efault)' else value
                    except Exception:  # pylint: disable=broad-except
                        pass

        return attrs

    @staticmethod
    def is_dc_device(device):
        '''@brief check whether device refers to a Discovery Controller'''
        # Note: Prior to 5.18 linux didn't expose the cntrltype through
        # the sysfs. So, this may return None on older kernels.
        cntrltype = device.attributes.get('cntrltype')
        if cntrltype is not None and cntrltype.decode() != 'discovery':
            return False

        # Imply Discovery controller based on the absence of children.
        # Discovery Controllers have no children devices
        if len(list(device.children)) != 0:
            return False

        return True

    @staticmethod
    def is_ioc_device(device):
        '''@brief check whether device refers to an I/O Controller'''
        # Note: Prior to 5.18 linux didn't expose the cntrltype through
        # the sysfs. So, this may return None on older kernels.
        cntrltype = device.attributes.get('cntrltype')
        if cntrltype is not None and cntrltype.decode() != 'io':
            return False

        subsysnqn = device.attributes.get('subsysnqn')
        if subsysnqn is not None and subsysnqn.decode() == defs.WELL_KNOWN_DISC_NQN:
            return False

        # Imply I/O controller based on the presence of children.
        # I/O Controllers have children devices
        if len(list(device.children)) == 0:
            return False

        return True

    def find_nvme_dc_device(self, tid):
        '''@brief  Find the nvme device associated with the specified
                Discovery Controller.
        @return The device if a match is found, None otherwise.
        '''
        for device in self._context.list_devices(
            subsystem='nvme', NVME_TRADDR=tid.traddr, NVME_TRSVCID=tid.trsvcid, NVME_TRTYPE=tid.transport
        ):
            if not self.is_dc_device(device):
                continue

            if self.get_tid(device) != tid:
                continue

            return device

        return None

    def find_nvme_ioc_device(self, tid):
        '''@brief  Find the nvme device associated with the specified
                I/O Controller.
        @return The device if a match is found, None otherwise.
        '''
        for device in self._context.list_devices(
            subsystem='nvme', NVME_TRADDR=tid.traddr, NVME_TRSVCID=tid.trsvcid, NVME_TRTYPE=tid.transport
        ):
            if not self.is_ioc_device(device):
                continue

            if self.get_tid(device) != tid:
                continue

            return device

        return None

    def get_nvme_ioc_tids(self):
        '''@brief  Find all the I/O controller nvme devices in the system.
        @return A list of pyudev.device._device.Device objects
        '''
        tids = []
        for device in self._context.list_devices(subsystem='nvme'):
            if not self.is_ioc_device(device):
                continue

            tids.append(self.get_tid(device))

        return tids

    def _device_event(self, _observer, device):
        user_cback = self._action_event_registry.get(device.action, None)
        if user_cback is not None:
            user_cback(device)

        user_cback = self._device_event_registry.get(device.sys_name, None)
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
        except Exception:  # pylint: disable=broad-except
            attr = default

        return '' if attr.lower() == 'none' else attr

    @staticmethod
    def get_tid(device):
        '''@brief return the Transport ID associated with a udev device'''
        cid = {
            'transport':   Udev._get_property(device, 'NVME_TRTYPE'),
            'traddr':      Udev._get_property(device, 'NVME_TRADDR'),
            'trsvcid':     Udev._get_property(device, 'NVME_TRSVCID'),
            'host-traddr': Udev._get_property(device, 'NVME_HOST_TRADDR'),
            'host-iface':  Udev._get_property(device, 'NVME_HOST_IFACE'),
            'subsysnqn':   Udev._get_attribute(device, 'subsysnqn'),
        }
        return TransportId(cid)


UDEV = Udev()  # Singleton


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
def blacklisted(blacklisted_ctrl_list, controller):
    '''@brief Check if @controller is black-listed.'''
    for blacklisted_ctrl in blacklisted_ctrl_list:
        test_results = [val == controller.get(key, None) for key, val in blacklisted_ctrl.items()]
        if all(test_results):
            return True
    return False


# ******************************************************************************
def remove_blacklisted(controllers: list):
    '''@brief Remove black-listed controllers from the list of controllers.'''
    blacklisted_ctrl_list = CNF.get_blacklist()
    if blacklisted_ctrl_list:
        LOG.debug('remove_blacklisted()               - blacklisted_ctrl_list = %s', blacklisted_ctrl_list)
        controllers = [controller for controller in controllers if not blacklisted(blacklisted_ctrl_list, controller)]
    return controllers


# ******************************************************************************
def remove_invalid_addresses(controllers: list):
    '''@brief Remove controllers with invalid addresses from the list of controllers.'''
    valid_controllers = list()
    for controller in controllers:
        # First, let's make sure that traddr is
        # syntactically a valid IPv4 or IPv6 address.
        traddr = controller.get('traddr')
        try:
            ip = ipaddress.ip_address(traddr)
        except ValueError:
            LOG.warning('%s IP address is not valid', TransportId(controller))
            continue

        if ip.version not in CNF.ip_family:
            LOG.debug('%s ignored because IPv%s is disabled in %s', TransportId(controller), ip.version, CNF.conf_file)
            continue

        valid_controllers.append(controller)

    return valid_controllers


# ******************************************************************************
class TransportId:
    # pylint: disable=too-many-instance-attributes
    '''Transport Identifier'''
    RDMA_IP_PORT = '4420'
    DISC_IP_PORT = '8009'

    def __init__(self, cid: dict):
        '''@param cid: Controller Identifier. A dictionary with the following
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
        self._transport = cid.get('transport')
        self._traddr    = cid.get('traddr')
        trsvcid         = cid.get('trsvcid')
        self._trsvcid = (
            trsvcid
            if trsvcid
            else (TransportId.RDMA_IP_PORT if self._transport == 'rdma' else TransportId.DISC_IP_PORT)
        )  # pylint: disable=used-before-assignment
        self._host_traddr = cid.get('host-traddr', '')
        self._host_iface  = '' if CNF.ignore_iface else cid.get('host-iface', '')
        self._subsysnqn   = cid.get('subsysnqn')
        self._key         = (self._transport, self._traddr, self._trsvcid, self._host_traddr, self._host_iface, self._subsysnqn)
        self._hash        = int.from_bytes(hashlib.md5(''.join(self._key).encode('utf-8')).digest(), 'big')  # We need a consistent hash between restarts
        self._id          = f'({self._transport}, {self._traddr}, {self._trsvcid}{", " + self._subsysnqn if self._subsysnqn else ""}{", " + self._host_iface if self._host_iface else ""}{", " + self._host_traddr if self._host_traddr else ""})'  # pylint: disable=line-too-long

    @property
    def key(self):  # pylint: disable=missing-function-docstring
        return self._key

    @property
    def hash(self):  # pylint: disable=missing-function-docstring
        return self._hash

    @property
    def transport(self):  # pylint: disable=missing-function-docstring
        return self._transport

    @property
    def traddr(self):  # pylint: disable=missing-function-docstring
        return self._traddr

    @property
    def trsvcid(self):  # pylint: disable=missing-function-docstring
        return self._trsvcid

    @property
    def host_traddr(self):  # pylint: disable=missing-function-docstring
        return self._host_traddr

    @property
    def host_iface(self):  # pylint: disable=missing-function-docstring
        return self._host_iface

    @property
    def subsysnqn(self):  # pylint: disable=missing-function-docstring
        return self._subsysnqn

    def as_dict(self):  # pylint: disable=missing-function-docstring
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


# ******************************************************************************
class NameResolver:
    # pylint: disable=too-few-public-methods
    '''@brief DNS resolver to convert host names to IP addresses.'''

    def __init__(self):
        self._resolver = Gio.Resolver.get_default()

    def resolve_ctrl_async(self, cancellable, controllers: dict, callback):
        '''@brief The traddr fields may specify a hostname instead of an IP
        address. We need to resolve all the host names to addresses.
        Resolving hostnames may take a while as a DNS server may need
        to be contacted. For that reason, we're using async APIs with
        callbacks to resolve all the hostnames.

        The callback @callback will be called once all hostnames have
        been resolved.
        '''
        pending_resolution_count = 0

        def addr_resolved(resolver, result, indx):
            hostname = controllers[indx]['traddr']
            traddr = hostname
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

        if pending_resolution_count == 0:  # No names are pending asynchronous resolution
            callback(controllers)


# ******************************************************************************
class AsyncCaller(GObject.Object):
    '''@brief This class allows running methods asynchronously in a thread.'''

    def __init__(self, user_function, *user_args):
        '''@param user_function: function to run inside a thread
        @param user_args: arguments passed to @user_function
        '''
        super().__init__()
        self._user_function = user_function
        self._user_args = user_args

    def communicate(self, cancellable, cb_function, *cb_args):
        '''@param cancellable: A Gio.Cancellable object that can be used to
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

        def in_thread_exec(task, self, task_data, cancellable):  # pylint: disable=unused-argument
            if task.return_error_if_cancelled():
                return  # Bail out if task has been cancelled

            try:
                value = GObject.Object()
                value.result = self._user_function(*self._user_args)
                task.return_value(value)
            except Exception as ex:  # pylint: disable=broad-except
                task.return_error(GLib.Error(repr(ex)))

        task = Gio.Task.new(self, cancellable, cb_function, *cb_args)
        task.set_return_on_cancel(False)
        task.run_in_thread(in_thread_exec)

    def communicate_finish(self, result):  # pylint: disable=no-self-use
        '''@brief Use this function in your callback (see @cb_function) to
               extract data from the result object.

        @return A tuple: (success, data, errmsg)
        '''
        try:
            success, value = result.propagate_value()
            return success, value.result, None
        except GLib.Error as err:
            return False, None, err


# ******************************************************************************
class AsyncOperationWithRetry:  # pylint: disable=too-many-instance-attributes
    '''Object used to manage an asynchronous GLib operation. The operation
    can be cancelled or retried.
    '''

    def __init__(self, on_success_callback, on_failure_callback, operation, *op_args):
        '''@param on_success_callback: Callback method invoked when @operation completes successfully
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

    def as_dict(self):  # pylint: disable=missing-function-docstring
        info = {
            'fail count': self._fail_cnt,
        }

        if self._retry_tmr:
            info['retry timer'] = str(self._retry_tmr)

        if self._errmsg:
            info['error'] = self._errmsg

        return info

    def cancel(self):
        '''@brief cancel async operation'''
        if not self._cancellable.is_cancelled():
            self._cancellable.cancel()

    def kill(self):
        '''@brief kill and clean up this object'''
        self._release_resources()

    def run_async(self, *args):
        '''@brief
        Method used to initiate an asynchronous operation with the
        Controller. When the operation completes (or fails) the
        callback method @_on_operation_complete() will be invoked.
        '''
        async_caller = AsyncCaller(self._operation, *self._op_args)
        async_caller.communicate(self._cancellable, self._on_operation_complete, *args)

    def retry(self, interval_sec, *args):
        '''@brief Tell this object that the async operation is to be retried
        in @interval_sec seconds.

        '''
        if self._retry_tmr is None:
            self._retry_tmr = GTimer()
        self._retry_tmr.set_callback(self._on_retry_timeout, *args)
        self._retry_tmr.start(interval_sec)

    def _on_retry_timeout(self, *args):
        '''@brief
        When an operation fails, the application has the option to
        retry at a later time by calling the retry() method. The
        retry() method starts a timer at the end of which the operation
        will be executed again. This is the method that is called when
        the timer expires.
        '''
        self.run_async(*args)
        return GLib.SOURCE_REMOVE

    def _on_operation_complete(self, async_caller, result, *args):
        '''@brief
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


# ******************************************************************************
class Controller:  # pylint: disable=too-many-instance-attributes
    '''@brief Base class used to manage the connection to a controller.'''

    CONNECT_RETRY_PERIOD_SEC = 60
    FAST_CONNECT_RETRY_PERIOD_SEC = 3

    def __init__(self, root, host, tid: TransportId, discovery_ctrl=False):
        self._root              = root
        self._host              = host
        self._tid               = tid
        self._cancellable       = Gio.Cancellable()
        self._connect_op        = None
        self._connect_attempts  = 0
        self._retry_connect_tmr = GTimer(Controller.CONNECT_RETRY_PERIOD_SEC, self._on_try_to_connect)
        self._device            = None
        self._ctrl              = None
        self._discovery_ctrl    = discovery_ctrl

        # Defer attempt to connect to the next main loop's idle period.
        GLib.idle_add(self._try_to_connect)

    def _release_resources(self):
        LOG.debug('Controller._release_resources()    - %s', self.id)

        device = self.device
        if device:
            UDEV.unregister_for_device_events(self._on_udev_notification)

        self._retry_connect_tmr.kill()

        if not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        self._kill_ops()

        self._tid = None
        self._ctrl = None
        self._device = None
        self._retry_connect_tmr = None

    def _alive(self):
        '''There may be race condition where a queued event gets processed
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
                nvme_aen = udev.get("NVME_AEN")
                nvme_event = udev.get("NVME_EVENT")
                if isinstance(nvme_aen, str):
                    LOG.info('%s | %s - Received AEN: %s', self.id, udev.sys_name, nvme_aen)
                    self._on_aen(udev, int(nvme_aen, 16))
                if isinstance(nvme_event, str):
                    self._on_nvme_event(udev, nvme_event)
            elif udev.action == 'remove':
                LOG.info('%s | %s - Received "remove" event', self.id, udev.sys_name)
                self._on_udev_remove(udev)
            else:
                LOG.debug(
                    'Controller._on_udev_notification() - %s | %s - Received "%s" notification.',
                    self.id,
                    udev.sys_name,
                    udev.action,
                )
        else:
            LOG.debug(
                'Controller._on_udev_notification() - %s | %s - Received event on dead object. udev %s: %s',
                self.id,
                self.device,
                udev.action,
                udev.sys_name,
            )

    def _on_aen(self, udev, aen: int):
        pass

    def _on_nvme_event(self, udev, nvme_event):
        pass

    def _on_udev_remove(self, udev):  # pylint: disable=unused-argument
        UDEV.unregister_for_device_events(self._on_udev_notification)
        self._kill_ops()  # Kill all pending operations
        self._ctrl = None

    def _find_existing_connection(self):
        raise NotImplementedError()

    def _on_try_to_connect(self):
        self._try_to_connect()
        return GLib.SOURCE_REMOVE

    def _try_to_connect(self):
        self._connect_attempts += 1

        host_iface = (
            self.tid.host_iface
            if (self.tid.host_iface and not CNF.ignore_iface and NvmeOptions().host_iface_supp)
            else None
        )
        self._ctrl = nvme.ctrl(
            self._root,
            subsysnqn=self.tid.subsysnqn,
            transport=self.tid.transport,
            traddr=self.tid.traddr,
            trsvcid=self.tid.trsvcid,
            host_traddr=self.tid.host_traddr if self.tid.host_traddr else None,
            host_iface=host_iface,
        )
        self._ctrl.discovery_ctrl_set(self._discovery_ctrl)

        # Audit existing nvme devices. If we find a match, then
        # we'll just borrow that device instead of creating a new one.
        udev = self._find_existing_connection()
        if udev is not None:
            # A device already exists.
            self._device = udev.sys_name
            LOG.debug(
                'Controller._try_to_connect()       - %s Found existing control device: %s', self.id, udev.sys_name
            )
            self._connect_op = AsyncOperationWithRetry(
                self._on_connect_success, self._on_connect_fail, self._ctrl.init, self._host, int(udev.sys_number)
            )
        else:
            self._device = None
            cfg = { 'hdr_digest':  CNF.hdr_digest,
                    'data_digest': CNF.data_digest }
            if CNF.kato is not None:
                cfg['keep_alive_tmo'] = CNF.kato
            elif self._discovery_ctrl:
                # All the connections to Controllers (I/O and Discovery) are
                # persistent. Persistent connections MUST configure the KATO.
                # The kernel already assigns a default 2-minute KATO to I/O
                # controller connections, but it doesn't assign one to
                # Discovery controller (DC) connections. Here we set the default
                # DC connection KATO to match the default set by nvme-cli on
                # persistent DC connections (i.e. 30 sec).
                cfg['keep_alive_tmo'] = DC_KATO_DEFAULT

            LOG.debug('Controller._try_to_connect()       - %s Connecting to nvme control with cfg=%s', self.id, cfg)
            self._connect_op = AsyncOperationWithRetry(
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
            LOG.info('%s | %s - Connection established!', self.id, self.device)
            self._connect_attempts = 0
            UDEV.register_for_device_events(self.device, self._on_udev_notification)
        else:
            LOG.debug(
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
                LOG.error('%s Failed to connect to controller. %s', self.id, getattr(err, 'message', err))

            LOG.debug(
                'Controller._on_connect_fail()      - %s %s. Retry in %s sec.',
                self.id,
                err,
                self._retry_connect_tmr.get_timeout(),
            )
            self._retry_connect_tmr.start()
        else:
            LOG.debug(
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
        if not self._cancellable.is_cancelled():
            LOG.debug('Controller.cancel()                - %s', self.id)
            self._cancellable.cancel()

        if self._connect_op:
            self._connect_op.cancel()

    def kill(self):
        '''@brief Used to release all resources associated with this object.'''
        LOG.debug('Controller.kill()                  - %s', self.id)
        self._release_resources()

    def disconnect(self, disconnected_cb, keep_connection):
        '''@brief Issue an asynchronous disconnect command to a Controller.
        Once the async command has completed, the callback 'disconnected_cb'
        will be invoked. If a controller is already disconnected, then the
        callback will be added to the main loop's next idle slot to be executed
        ASAP.
        '''
        LOG.debug('Controller.disconnect()            - %s | %s', self.id, self.device)
        self._kill_ops()
        if self._ctrl and self._ctrl.connected() and not keep_connection:
            LOG.info('%s | %s - Disconnect initiated', self.id, self.device)
            op = AsyncOperationWithRetry(self._on_disconn_success, self._on_disconn_fail, self._ctrl.disconnect)
            op.run_async(disconnected_cb)
        else:
            # Defer callback to the next main loop's idle period. The callback
            # cannot be called directly as the current Controller object is in the
            # process of being disconnected and the callback will in fact delete
            # the object. This would invariably lead to unpredictable outcome.
            GLib.idle_add(disconnected_cb, self.tid, self.device)

    def _on_disconn_success(self, op_obj, data, disconnected_cb):  # pylint: disable=unused-argument
        LOG.debug('Controller._on_disconn_success()   - %s | %s', self.id, self.device)
        op_obj.kill()
        # Defer callback to the next main loop's idle period. The callback
        # cannot be called directly as the current Controller object is in the
        # process of being disconnected and the callback will in fact delete
        # the object. This would invariably lead to unpredictable outcome.
        GLib.idle_add(disconnected_cb, self.tid, self.device)

    def _on_disconn_fail(self, op_obj, err, fail_cnt, disconnected_cb):  # pylint: disable=unused-argument
        LOG.debug('Controller._on_disconn_fail()      - %s | %s: %s', self.id, self.device, err)
        op_obj.kill()
        # Defer callback to the next main loop's idle period. The callback
        # cannot be called directly as the current Controller object is in the
        # process of being disconnected and the callback will in fact delete
        # the object. This would invariably lead to unpredictable outcome.
        GLib.idle_add(disconnected_cb, self.tid, self.device)


# ******************************************************************************
class Service:  # pylint: disable=too-many-instance-attributes
    '''@brief Base class used to manage a STorage Appliance Service'''

    def __init__(self, reload_hdlr):
        self._lkc_file     = os.path.join(os.environ.get('RUNTIME_DIRECTORY'), 'last-known-config.pickle')
        self._loop         = GLib.MainLoop()
        self._cancellable  = Gio.Cancellable()
        self._resolver     = NameResolver()
        self._controllers  = self._load_last_known_config()
        self._dbus_iface   = None
        self._cfg_soak_tmr = None
        self._sysbus       = dasbus.connection.SystemMessageBus()

        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, self._stop_hdlr)  # CTRL-C
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self._stop_hdlr)  # systemctl stop stafd
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGHUP, reload_hdlr)  # systemctl reload stafd

        nvme_options = NvmeOptions()
        if not nvme_options.host_iface_supp or not nvme_options.discovery_supp:
            LOG.warning(
                'Kernel does not appear to support all the options needed to run this program. Consider updating to a later kernel version.'
            )

    def _release_resources(self):
        LOG.debug('Service._release_resources()')

        if not self._cancellable.is_cancelled():
            self._cancellable.cancel()

        if self._cfg_soak_tmr is not None:
            self._cfg_soak_tmr.kill()

        self._controllers.clear()

        self._sysbus.disconnect()

        self._cfg_soak_tmr = None
        self._resolver = None
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
            LOG.critical('exception: %s', ex)

        self._loop = None

    def info(self) -> dict:
        '''@brief Get the status info for this object (used for debug)'''
        nvme_options = NvmeOptions()
        return {
            'last known config file': self._lkc_file,
            'config soak timer': str(self._cfg_soak_tmr),
            'kernel support': {
                'TP8013': nvme_options.discovery_supp,
                'host_iface': nvme_options.host_iface_supp,
            },
            'system config': SYS_CNF.as_dict(),
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
        return self._controllers.get(TransportId(cid))

    def remove_controller(self, tid, device):
        '''@brief remove the specified controller object from the list of controllers'''
        controller = self._controllers.pop(tid, None)

        LOG.debug(
            'Service.remove_controller()        - %s %s: %s',
            tid,
            device,
            'controller already removed' if controller is None else 'controller is being removed',
        )

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

    def _on_final_disconnect(self, tid, device):
        '''Callback invoked after a controller is disconnected.
        THIS IS USED DURING PROCESS SHUTDOWN TO WAIT FOR ALL CONTROLLERS TO BE
        DISCONNECTED BEFORE EXITING THE PROGRAM. ONLY CALL ON SHUTDOWN!
        '''
        LOG.debug('Service._on_final_disconnect()     - %s %s', tid, device)
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
        '''@brief Start controllers configuration.'''
        # The configuration file may contain controllers and/or blacklist
        # elements with traddr specified as hostname instead of IP address.
        # Because of this, we need to remove those blacklisted elements before
        # running name resolution. And we will need to remove blacklisted
        # elements after name resolution is complete (i.e. in the calback
        # function _config_ctrls_finish)
        LOG.debug('Service._config_ctrls()')
        configured_controllers = remove_blacklisted(CNF.get_controllers())
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
    '''Clean up all resources (especially singletons)'''

    global UDEV  # pylint: disable=global-statement
    if UDEV:
        UDEV.clean()
        UDEV = None

    NvmeOptions.destroy()
