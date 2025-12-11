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
import functools
import configparser
from urllib.parse import urlparse
from staslib import defs, iputil, nbft, singleton, timeparse

__TOKEN_RE = re.compile(r'\s*;\s*')
__OPTION_RE = re.compile(r'\s*=\s*')


class InvalidOption(Exception):
    '''Exception raised when an invalid option value is detected'''


def _parse_controller(controller):
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


def _parse_single_val(text):
    if isinstance(text, str):
        return text
    if not isinstance(text, list) or len(text) == 0:
        return None

    return text[-1]


def _parse_list(text):
    return text if isinstance(text, list) else [text]


def _to_int(text):
    try:
        return int(_parse_single_val(text))
    except (ValueError, TypeError):
        raise InvalidOption  # pylint: disable=raise-missing-from


def _to_bool(text, positive='true'):
    return _parse_single_val(text).lower() == positive


def _to_ncc(text):
    value = _to_int(text)
    if value == 1:  # 1 is invalid. A minimum of 2 is required (with the exception of 0, which is valid).
        value = 2
    return value


def _to_ip_family(text):
    return tuple((4 if text == 'ipv4' else 6 for text in _parse_single_val(text).split('+')))


# ******************************************************************************
class OrderedMultisetDict(dict):
    '''This class is used to change the behavior of configparser.ConfigParser
    and allow multiple configuration parameters with the same key. The
    result is a list of values, where values are sorted by the order they
    appear in the file.
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

    OPTION_CHECKER = {
        'Global': {
            'tron': {
                'convert': _to_bool,
                'default': False,
                'txt-chk': lambda text: _parse_single_val(text).lower() in ('false', 'true'),
            },
            'kato': {
                'convert': _to_int,
            },
            'pleo': {
                'convert': functools.partial(_to_bool, positive='enabled'),
                'default': True,
                'txt-chk': lambda text: _parse_single_val(text).lower() in ('disabled', 'enabled'),
            },
            'ip-family': {
                'convert': _to_ip_family,
                'default': (4, 6),
                'txt-chk': lambda text: _parse_single_val(text) in ('ipv4', 'ipv6', 'ipv4+ipv6', 'ipv6+ipv4'),
            },
            'queue-size': {
                'convert': _to_int,
                'rng-chk': lambda value: None if value in range(16, 1025) else range(16, 1025),
            },
            'hdr-digest': {
                'convert': _to_bool,
                'default': False,
                'txt-chk': lambda text: _parse_single_val(text).lower() in ('false', 'true'),
            },
            'data-digest': {
                'convert': _to_bool,
                'default': False,
                'txt-chk': lambda text: _parse_single_val(text).lower() in ('false', 'true'),
            },
            'ignore-iface': {
                'convert': _to_bool,
                'default': False,
                'txt-chk': lambda text: _parse_single_val(text).lower() in ('false', 'true'),
            },
            'nr-io-queues': {
                'convert': _to_int,
            },
            'ctrl-loss-tmo': {
                'convert': _to_int,
            },
            'disable-sqflow': {
                'convert': _to_bool,
                'txt-chk': lambda text: _parse_single_val(text).lower() in ('false', 'true'),
            },
            'nr-poll-queues': {
                'convert': _to_int,
            },
            'nr-write-queues': {
                'convert': _to_int,
            },
            'reconnect-delay': {
                'convert': _to_int,
            },
        },
        'Service Discovery': {
            'zeroconf': {
                'convert': functools.partial(_to_bool, positive='enabled'),
                'default': True,
                'txt-chk': lambda text: _parse_single_val(text).lower() in ('disabled', 'enabled'),
            },
        },
        'Discovery controller connection management': {
            'persistent-connections': {
                'convert': _to_bool,
                'default': True,
                'txt-chk': lambda text: _parse_single_val(text).lower() in ('false', 'true'),
            },
            'zeroconf-connections-persistence': {
                'convert': lambda text: timeparse.timeparse(_parse_single_val(text)),
                'default': timeparse.timeparse('72hours'),
            },
        },
        'I/O controller connection management': {
            'disconnect-scope': {
                'convert': _parse_single_val,
                'default': 'only-stas-connections',
                'txt-chk': lambda text: _parse_single_val(text)
                in ('only-stas-connections', 'all-connections-matching-disconnect-trtypes', 'no-disconnect'),
            },
            'disconnect-trtypes': {
                # Use set() to eliminate potential duplicates
                'convert': lambda text: set(_parse_single_val(text).split('+')),
                'default': [
                    'tcp',
                ],
                'lst-chk': ('tcp', 'rdma', 'fc'),
            },
            'connect-attempts-on-ncc': {
                'convert': _to_ncc,
                'default': 0,
            },
        },
        'Controllers': {
            'controller': {
                'convert': _parse_list,
                'default': [],
            },
            'exclude': {
                'convert': _parse_list,
                'default': [],
            },
            ### BEGIN: LEGACY SECTION TO BE REMOVED ###
            'blacklist': {
                'convert': _parse_list,
                'default': [],
            },
            ### END: LEGACY SECTION TO BE REMOVED ###
        },
    }

    def __init__(self, default_conf=None, conf_file='/dev/null'):
        self._config = None
        self._defaults = default_conf if default_conf else {}

        if self._defaults is not None and len(self._defaults) != 0:
            self._valid_conf = {}
            for section, option in self._defaults:
                self._valid_conf.setdefault(section, set()).add(option)
        else:
            self._valid_conf = None

        self._conf_file = conf_file
        self.reload()

    def reload(self):
        '''@brief Reload the configuration file.'''
        self._config = self._read_conf_file()

    @property
    def conf_file(self):
        '''Return the configuration file name'''
        return self._conf_file

    def set_conf_file(self, fname):
        '''Set the configuration file name and reload config'''
        self._conf_file = fname
        self.reload()

    def get_option(self, section, option, ignore_default=False):  # pylint: disable=too-many-locals
        '''Retrieve @option from @section, convert raw text to
        appropriate object type, and validate.'''
        try:
            checker = self.OPTION_CHECKER[section][option]
        except KeyError:
            logging.error('Requesting invalid section=%s and/or option=%s', section, option)
            raise

        default = checker.get('default', None)

        try:
            text = self._config.get(section=section, option=option)
        except (configparser.NoSectionError, configparser.NoOptionError, KeyError):
            return None if ignore_default else self._defaults.get((section, option), default)

        return self._check(text, section, option, default)

    tron = property(functools.partial(get_option, section='Global', option='tron'))
    kato = property(functools.partial(get_option, section='Global', option='kato'))
    ip_family = property(functools.partial(get_option, section='Global', option='ip-family'))
    queue_size = property(functools.partial(get_option, section='Global', option='queue-size'))
    hdr_digest = property(functools.partial(get_option, section='Global', option='hdr-digest'))
    data_digest = property(functools.partial(get_option, section='Global', option='data-digest'))
    ignore_iface = property(functools.partial(get_option, section='Global', option='ignore-iface'))
    pleo_enabled = property(functools.partial(get_option, section='Global', option='pleo'))
    nr_io_queues = property(functools.partial(get_option, section='Global', option='nr-io-queues'))
    ctrl_loss_tmo = property(functools.partial(get_option, section='Global', option='ctrl-loss-tmo'))
    disable_sqflow = property(functools.partial(get_option, section='Global', option='disable-sqflow'))
    nr_poll_queues = property(functools.partial(get_option, section='Global', option='nr-poll-queues'))
    nr_write_queues = property(functools.partial(get_option, section='Global', option='nr-write-queues'))
    reconnect_delay = property(functools.partial(get_option, section='Global', option='reconnect-delay'))

    zeroconf_persistence_sec = property(
        functools.partial(
            get_option, section='Discovery controller connection management', option='zeroconf-connections-persistence'
        )
    )

    disconnect_scope = property(
        functools.partial(get_option, section='I/O controller connection management', option='disconnect-scope')
    )
    disconnect_trtypes = property(
        functools.partial(get_option, section='I/O controller connection management', option='disconnect-trtypes')
    )
    connect_attempts_on_ncc = property(
        functools.partial(get_option, section='I/O controller connection management', option='connect-attempts-on-ncc')
    )

    @property  # pylint chokes on this when defined as zeroconf_enabled=property(...). Works fine using a decorator...
    def zeroconf_enabled(self):
        '''Return whether zeroconf is enabled'''
        return self.get_option(section='Service Discovery', option='zeroconf')

    @property
    def stypes(self):
        '''@brief Get the DNS-SD/mDNS service types.'''
        return ['_nvme-disc._tcp', '_nvme-disc._udp'] if self.zeroconf_enabled else list()

    @property
    def persistent_connections(self):
        '''@brief return the "persistent-connections" config parameter'''
        section = 'Discovery controller connection management'
        option = 'persistent-connections'

        value = self.get_option(section, option, ignore_default=True)
        if value is not None:
            return value

        return self._defaults.get((section, option), True)

    def get_controllers(self):
        '''@brief Return the list of controllers in the config file.
        Each controller is in the form of a dictionary as follows.
        Note that some of the keys are optional.
        {
            'transport':          [TRANSPORT],
            'traddr':             [TRADDR],
            'trsvcid':            [TRSVCID],
            'subsysnqn':          [NQN],
            'host-traddr':        [TRADDR],
            'host-iface':         [IFACE],
            'host-nqn':           [NQN],
            'dhchap-secret':      [KEY],
            'dhchap-ctrl-secret': [KEY],
            'hdr-digest':         [BOOL]
            'data-digest':        [BOOL]
            'nr-io-queues':       [NUMBER]
            'nr-write-queues':    [NUMBER]
            'nr-poll-queues':     [NUMBER]
            'queue-size':         [SIZE]
            'kato':               [KATO]
            'reconnect-delay':    [SECONDS]
            'ctrl-loss-tmo':      [SECONDS]
            'disable-sqflow':     [BOOL]
        }
        '''
        controller_list = self.get_option('Controllers', 'controller')
        cids = [_parse_controller(controller) for controller in controller_list]
        for cid in cids:
            try:
                # replace 'nqn' key by 'subsysnqn', if present.
                cid['subsysnqn'] = cid.pop('nqn')
            except KeyError:
                pass

            # Verify values of the options used to overload the matching [Global] options
            for option in cid:
                if option in self.OPTION_CHECKER['Global']:
                    value = self._check(cid[option], 'Global', option, None)
                    if value is not None:
                        cid[option] = value

        return cids

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
        controller_list = self.get_option('Controllers', 'exclude')

        # 2022-09-20: Look for "blacklist". This is for backwards compatibility
        # with releases 1.0 to 1.1.x. This is to be phased out (i.e. remove by 2024)
        controller_list += self.get_option('Controllers', 'blacklist')

        excluded = [_parse_controller(controller) for controller in controller_list]
        for controller in excluded:
            controller.pop('host-traddr', None)  # remove host-traddr
            try:
                # replace 'nqn' key by 'subsysnqn', if present.
                controller['subsysnqn'] = controller.pop('nqn')
            except KeyError:
                pass
        return excluded

    def _check(self, text, section, option, default):
        checker = self.OPTION_CHECKER[section][option]
        text_checker = checker.get('txt-chk', None)
        if text_checker is not None and not text_checker(text):
            logging.warning(
                'File:%s [%s]: %s - Text check found invalid value "%s". Default will be used',
                self.conf_file,
                section,
                option,
                text,
            )
            return self._defaults.get((section, option), default)

        converter = checker.get('convert', None)
        try:
            value = converter(text)
        except InvalidOption:
            logging.warning(
                'File:%s [%s]: %s - Data converter found invalid value "%s". Default will be used',
                self.conf_file,
                section,
                option,
                text,
            )
            return self._defaults.get((section, option), default)

        value_in_range = checker.get('rng-chk', None)
        if value_in_range is not None:
            expected_range = value_in_range(value)
            if expected_range is not None:
                logging.warning(
                    'File:%s [%s]: %s - "%s" is not within range %s..%s. Default will be used',
                    self.conf_file,
                    section,
                    option,
                    value,
                    min(expected_range),
                    max(expected_range),
                )
                return self._defaults.get((section, option), default)

        list_checker = checker.get('lst-chk', None)
        if list_checker:
            values = set()
            for item in value:
                if item not in list_checker:
                    logging.warning(
                        'File:%s [%s]: %s - List checker found invalid item "%s" will be ignored.',
                        self.conf_file,
                        section,
                        option,
                        item,
                    )
                else:
                    values.add(item)

            if len(values) == 0:
                return self._defaults.get((section, option), default)

            value = list(values)

        return value

    def _read_conf_file(self):
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

        # Parse Configuration and validate.
        if self._valid_conf is not None:
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
                            'File:%s [%s] contains invalid options: %s',
                            self.conf_file,
                            section,
                            invalid_options,
                        )

            if len(invalid_sections) != 0:
                logging.error(
                    'File:%s contains invalid sections: %s',
                    self.conf_file,
                    invalid_sections,
                )

        return config


# ******************************************************************************
class SysConf(metaclass=singleton.Singleton):
    '''Read and cache the host configuration file.'''

    def __init__(self, conf_file=defs.SYS_CONF_FILE):
        self._config = None
        self._conf_file = conf_file
        self.reload()

    def reload(self):
        '''@brief Reload the configuration file.'''
        self._config = self._read_conf_file()

    @property
    def conf_file(self):
        '''Return the configuration file name'''
        return self._conf_file

    def set_conf_file(self, fname):
        '''Set the configuration file name and reload config'''
        self._conf_file = fname
        self.reload()

    def as_dict(self):
        '''Return configuration as a dictionary'''
        return {
            'hostnqn': self.hostnqn,
            'hostid': self.hostid,
            'hostkey': self.hostkey,
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
            value = self.__get_value('Host', 'nqn', defs.NVME_HOSTNQN)
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
            value = self.__get_value('Host', 'id', defs.NVME_HOSTID)
        except FileNotFoundError as ex:
            sys.exit(f'Error reading mandatory Host ID (see stasadm --help): {ex}')

        return value

    @property
    def hostkey(self):
        '''@brief return the host key
        @return: Host key
        @raise: Host key is optional, but mandatory if authorization will be performed.
        '''
        try:
            value = self.__get_value('Host', 'key', defs.NVME_HOSTKEY)
        except FileNotFoundError as ex:
            logging.debug('Host key undefined: %s', ex)
            value = None

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

    def _read_conf_file(self):
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
            'dhchap_secret': defs.KERNEL_VERSION >= defs.KERNEL_HOSTKEY_MIN_VERSION,
            'dhchap_ctrl_secret': defs.KERNEL_VERSION >= defs.KERNEL_CTRLKEY_MIN_VERSION,
        }

        # If some of the options are False, we need to check whether they can be
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

    @property
    def dhchap_hostkey_supp(self):
        '''This option allows specifying the host DHCHAP key used for authentication.'''
        return self._supported_options['dhchap_secret']

    @property
    def dhchap_ctrlkey_supp(self):
        '''This option allows specifying the controller DHCHAP key used for authentication.'''
        return self._supported_options['dhchap_ctrl_secret']


# ******************************************************************************
class NbftConf(metaclass=singleton.Singleton):  # pylint: disable=too-few-public-methods
    '''Read and cache configuration file.'''

    def __init__(self, root_dir=defs.NBFT_SYSFS_PATH):
        self._disc_ctrls = []
        self._subs_ctrls = []

        nbft_files = nbft.get_nbft_files(root_dir)
        if len(nbft_files):
            logging.info('NBFT location(s): %s', list(nbft_files.keys()))

        for data in nbft_files.values():
            hfis = data.get('hfi', [])
            discovery = data.get('discovery', [])
            subsystem = data.get('subsystem', [])
            host = data.get('host', {})
            hostnqn = host.get('nqn', None) if host.get('host_nqn_configured', False) else None

            self._disc_ctrls.extend(NbftConf.__nbft_disc_to_cids(hostnqn, discovery, hfis))
            self._subs_ctrls.extend(NbftConf.__nbft_subs_to_cids(hostnqn, subsystem, hfis))

    dcs = property(lambda self: self._disc_ctrls)
    iocs = property(lambda self: self._subs_ctrls)

    def get_controllers(self):
        '''Retrieve the list of controllers. Stafd only cares about
        discovery controllers. Stacd only cares about I/O controllers.'''

        # For now, only return DCs. There are still unanswered questions
        # regarding I/O controllers, e.g. what if multipathing has been
        # configured.
        return self.dcs if defs.PROG_NAME == 'stafd' else []

    @staticmethod
    def __nbft_disc_to_cids(hostnqn, discovery, hfis):
        cids = []

        for ctrl in discovery:
            cid = NbftConf.__uri2cid(ctrl['uri'])
            cid['subsysnqn'] = ctrl['nqn']
            if hostnqn:
                cid['host-nqn'] = hostnqn

            host_iface = NbftConf.__get_host_iface(ctrl.get('hfi_index'), hfis)
            if host_iface:
                cid['host-iface'] = host_iface

            cids.append(cid)

        return cids

    @staticmethod
    def __nbft_subs_to_cids(hostnqn, subsystem, hfis):
        cids = []

        for ctrl in subsystem:
            cid = {
                'transport': ctrl['trtype'],
                'traddr': ctrl['traddr'],
                'trsvcid': ctrl['trsvcid'],
                'subsysnqn': ctrl['subsys_nqn'],
                'hdr-digest': ctrl['pdu_header_digest_required'],
                'data-digest': ctrl['data_digest_required'],
            }
            if hostnqn:
                cid['host-nqn'] = hostnqn

            indexes = ctrl.get('hfi_indexes')
            if isinstance(indexes, list) and len(indexes) > 0:
                host_iface = NbftConf.__get_host_iface(indexes[0], hfis)
                if host_iface:
                    cid['host-iface'] = host_iface

            cids.append(cid)

        return cids

    @staticmethod
    def __get_host_iface(indx, hfis):
        if indx is None or indx >= len(hfis):
            return None

        mac = hfis[indx].get('mac_addr')
        if mac is None:
            return None

        return iputil.mac2iface(mac)

    @staticmethod
    def __uri2cid(uri: str):
        '''Convert a URI of the form "nvme+tcp://100.71.103.50:8009/" to a Controller ID'''
        obj = urlparse(uri)
        return {
            'transport': obj.scheme.split('+')[1],
            'traddr': obj.hostname,
            'trsvcid': str(obj.port),
        }
