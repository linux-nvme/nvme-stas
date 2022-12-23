# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''nvme-stas configuration module'''

import re
import os
import sys
import logging
import configparser
from staslib import defs, singleton, timeparse

__TOKEN_RE = re.compile(r'\s*;\s*')
__OPTION_RE = re.compile(r'\s*=\s*')


def parse_controller(controller):
    '''@brief Parse a "controller" entry. Controller entries are strings
           composed of several configuration parameters delimited by
           semi-colons. Each configuration parameter is specified as a
           "key=value" pair.
    @return A dictionary of key-value pairs.
    '''
    options = dict()
    tokens = __TOKEN_RE.split(controller)
    for token in tokens:
        if token:
            try:
                option, val = __OPTION_RE.split(token)
                options[option.strip()] = val.strip()
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


class SvcConf(metaclass=singleton.Singleton):  # pylint: disable=too-many-public-methods
    '''Read and cache configuration file.'''

    def __init__(self, default_conf=None, conf_file='/dev/null'):
        self._defaults = default_conf if default_conf else {}

        self._valid_conf = {}
        for section, option in self._defaults:
            self._valid_conf.setdefault(section, set()).add(option)

        self._conf_file = conf_file
        self.reload()

    def reload(self):
        '''@brief Reload the configuration file.'''
        self._config = self.read_conf_file()

    @property
    def conf_file(self):  # pylint: disable=missing-function-docstring
        return self._conf_file

    def set_conf_file(self, fname):  # pylint: disable=missing-function-docstring
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
        return self.__get_bool(
            'Discovery controller connection management', 'persistent-connections'
        ) or self.__get_bool('Global', 'persistent-connections')

    @property
    def zeroconf_persistence_sec(self):  # pylint: disable=invalid-name
        '''@brief return the "zeroconf-connections-persistence" config parameter, in seconds'''
        value = self.__get_value('Discovery controller connection management', 'zeroconf-connections-persistence')
        return timeparse.timeparse(value)

    @property
    def ignore_iface(self):
        '''@brief return the "ignore-iface" config parameter'''
        return self.__get_bool('Global', 'ignore-iface')

    @property
    def ip_family(self):
        '''@brief return the "ip-family" config parameter.
        @rtype tuple
        '''
        family = self.__get_value('Global', 'ip-family')

        if family == 'ipv4':
            return (4,)
        if family == 'ipv6':
            return (6,)

        return (4, 6)

    @property
    def pleo_enabled(self):
        '''@brief return the "pleo" config parameter'''
        return self.__get_value('Global', 'pleo') == 'enabled'

    @property
    def udev_rule_enabled(self):
        '''@brief return the "udev-rule" config parameter'''
        return self.__get_value('Global', 'udev-rule') == 'enabled'

    @property
    def disconnect_scope(self):
        '''@brief return the disconnect scope (i.e. which connections are affected by DLPE removal)'''
        disconnect_scope = self.__get_value(
            'I/O controller connection management',
            'disconnect-scope',
            ('only-stas-connections', 'all-connections-matching-disconnect-trtypes', 'no-disconnect'),
        )
        return disconnect_scope

    @property
    def disconnect_trtypes(self):
        '''@brief return the type(s) of transport that will be audited
        as part of I/O controller connection management, when "disconnect-scope" is set to
        "all-connections-matching-disconnect-trtypes"'''
        value = self.__get_value('I/O controller connection management', 'disconnect-trtypes')
        value = set(value.split('+'))  # Use set() to eliminate potential duplicates

        trtypes = set()
        for trtype in value:
            if trtype not in ('tcp', 'rdma', 'fc'):
                logging.warning(
                    'File:%s, Section: [I/O controller connection management], Invalid "disconnect-trtypes=%s". Default will be used',
                    self.conf_file,
                    trtype,
                )
            else:
                trtypes.add(trtype)

        if len(trtypes) == 0:
            value = self._defaults[('I/O controller connection management', 'disconnect-trtypes')]
            trtypes = value.split('+')

        return list(trtypes)

    @property
    def connect_attempts_on_ncc(self):
        '''@brief Return the number of connection attempts that will be made
        when the NCC bit (Not Connected to CDC) is asserted.'''
        value = self.__get_int('I/O controller connection management', 'connect-attempts-on-ncc')

        if value == 1:  # 1 is invalid. A minimum of 2 is required (with the exception of 0, which is valid).
            value = 2

        return value

    @property
    def nr_io_queues(self):
        '''@brief return the "Number of I/O queues" config parameter'''
        return self.__get_int('Global', 'nr-io-queues')

    @property
    def nr_write_queues(self):
        '''@brief return the "Number of write queues" config parameter'''
        return self.__get_int('Global', 'nr-write-queues')

    @property
    def nr_poll_queues(self):
        '''@brief return the "Number of poll queues" config parameter'''
        return self.__get_int('Global', 'nr-poll-queues')

    @property
    def queue_size(self):
        '''@brief return the "Queue size" config parameter'''
        return self.__get_int('Global', 'queue-size', range(16, 1025))

    @property
    def reconnect_delay(self):
        '''@brief return the "Reconnect delay" config parameter'''
        return self.__get_int('Global', 'reconnect-delay')

    @property
    def ctrl_loss_tmo(self):
        '''@brief return the "Controller loss timeout" config parameter'''
        return self.__get_int('Global', 'ctrl-loss-tmo')

    @property
    def duplicate_connect(self):
        '''@brief return the "Duplicate connections" config parameter'''
        value = self.__get_value('Global', 'duplicate-connect')
        return value if value in ('true', 'false') else None

    @property
    def disable_sqflow(self):
        '''@brief return the "Disable sqflow" config parameter'''
        value = self.__get_value('Global', 'disable-sqflow')
        return value if value in ('true', 'false') else None

    @property
    def kato(self):
        '''@brief return the "kato" config parameter'''
        return self.__get_int('Global', 'kato')

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
        controller_list = self.__get_list('Controllers', 'controller')
        controllers = [parse_controller(controller) for controller in controller_list]
        for controller in controllers:
            try:
                # replace 'nqn' key by 'subsysnqn', if present.
                controller['subsysnqn'] = controller.pop('nqn')
            except KeyError:
                pass
        return controllers

    def get_excluded(self):
        '''@brief Return the list of excluded controllers in the config file.
        Each excluded controller is in the form of a dictionary
        as follows. All the keys are optional.
        {
            'transport':  [TRANSPORT],
            'traddr':     [TRADDR],
            'trsvcid':    [TRSVCID],
            'host-iface': [IFACE],
            'subsysnqn':  [NQN],
        }
        '''
        controller_list = self.__get_list('Controllers', 'exclude')

        # 2022-09-20: Look for "blacklist". This is for backwards compatibility
        # with releases 1.0 to 1.1.6. This is to be phased out (i.e. remove by 2024)
        controller_list += self.__get_list('Controllers', 'blacklist')

        excluded = [parse_controller(controller) for controller in controller_list]
        for controller in excluded:
            controller.pop('host-traddr', None)  # remove host-traddr
            try:
                # replace 'nqn' key by 'subsysnqn', if present.
                controller['subsysnqn'] = controller.pop('nqn')
            except KeyError:
                pass
        return excluded

    def get_stypes(self):
        '''@brief Get the DNS-SD/mDNS service types.'''
        return ['_nvme-disc._tcp'] if self.zeroconf_enabled() else list()

    def zeroconf_enabled(self):  # pylint: disable=missing-function-docstring
        return self.__get_value('Service Discovery', 'zeroconf') == 'enabled'

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

        # Configuration validation.
        invalid_sections = set()
        for section in config.sections():
            if section not in self._valid_conf:
                invalid_sections.add(section)
            else:
                invalid_options = set()
                for option in config.options(section):
                    if option not in self._valid_conf.get(section, []):
                        invalid_options.add(option)

                if len(invalid_options) != 0:
                    logging.error(
                        'File:%s, section [%s] contains invalid options: %s',
                        self.conf_file,
                        section,
                        invalid_options,
                    )

        if len(invalid_sections) != 0:
            logging.error(
                'File:%s, contains invalid sections: %s',
                self.conf_file,
                invalid_sections,
            )

        return config

    def __get_bool(self, section, option):
        text = self.__get_value(section, option)
        return text == 'true'

    def __get_int(self, section, option, expected_range=None):
        text = self.__get_value(section, option)
        if text is None:
            value = self._defaults.get((section, option), None)
        else:
            try:
                value = int(text)
            except (ValueError, TypeError):
                logging.warning(
                    'File:%s, Section: [%s], Invalid "%s=%s". Default will be used',
                    self.conf_file,
                    section,
                    option,
                    text,
                )
                value = self._defaults.get((section, option), None)
            else:
                if expected_range is not None and value not in expected_range:
                    logging.warning(
                        'File:%s, Section: [%s], %s=%s is not within range %s..%s',
                        self.conf_file,
                        section,
                        option,
                        value,
                        min(expected_range),
                        max(expected_range),
                    )
                    value = self._defaults.get((section, option), None)

        return value

    def __get_value(self, section, option, expected_range=None):
        lst = self.__get_list(section, option)
        if len(lst) == 0:
            return None

        value = lst[0]
        if expected_range is not None and value not in expected_range:
            logging.warning(
                'File:%s, Section:[%s], Invalid "%s=%s". Default will be used',
                self.conf_file,
                section,
                option,
                value,
            )
            value = self._defaults.get((section, option), None)
        return value

    def __get_list(self, section, option):
        try:
            value = self._config.get(section=section, option=option)
        except (configparser.NoSectionError, configparser.NoOptionError, KeyError):
            value = self._defaults.get((section, option), [])
            if not isinstance(value, list):
                value = [value]
        return value if value is not None else list()


# ******************************************************************************
class SysConf(metaclass=singleton.Singleton):
    '''Read and cache the host configuration file.'''

    def __init__(self, conf_file=defs.SYS_CONF_FILE):
        self._conf_file = conf_file
        self.reload()

    def reload(self):
        '''@brief Reload the configuration file.'''
        self._config = self.read_conf_file()

    @property
    def conf_file(self):  # pylint: disable=missing-function-docstring
        return self._conf_file

    def set_conf_file(self, fname):  # pylint: disable=missing-function-docstring
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

        if value is not None and not value.startswith('nqn.'):
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
            logging.warning('Error reading host symbolic name (will remain undefined): %s', ex)
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

        try:
            with open(file) as f:  # pylint: disable=unspecified-encoding
                return f.readline().split()[0]
        except IndexError:
            return None


# ******************************************************************************
class NvmeOptions(metaclass=singleton.Singleton):
    '''Object used to read and cache contents of file /dev/nvme-fabrics.
    Note that this file was not readable prior to Linux 5.16.
    '''

    def __init__(self):
        # Supported options can be determined by looking at the kernel version
        # or by reading '/dev/nvme-fabrics'. The ability to read the options
        # from '/dev/nvme-fabrics' was only introduced in kernel 5.17, but may
        # have been backported to older kernels. In any case, if the kernel
        # version meets the minimum version for that option, then we don't
        # even need to read '/dev/nvme-fabrics'.
        self._supported_options = {
            'discovery': defs.KERNEL_VERSION >= defs.KERNEL_TP8013_MIN_VERSION,
            'host_iface': defs.KERNEL_VERSION >= defs.KERNEL_IFACE_MIN_VERSION,
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
            except (OSError, FileNotFoundError):
                logging.warning('Cannot determine which NVMe options the kernel supports')
            else:
                for option, supported in self._supported_options.items():
                    if not supported:
                        self._supported_options[option] = option in options

    def __str__(self):
        return f'supported options: {self._supported_options}'

    def get(self):
        '''get the supported options as a dict'''
        return self._supported_options

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
