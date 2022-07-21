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
from staslib import defs, singleton

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


class SvcConf(metaclass=singleton.Singleton):
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
            ('Global', 'sticky-connections'): 'enabled',
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
