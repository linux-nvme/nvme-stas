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
from libnvme3 import nvme
from staslib import defs, iputil, nbft, singleton, timeparse

__TOKEN_RE = re.compile(r'\s*;\s*')

_LIBNVME_CTX = None

# The keys libnvme accepts in an exclusion entry. Anything else makes the
# entry inert (see _libnvme_excluded()).
_EXCLUSION_KEYS = frozenset(('transport', 'traddr', 'trsvcid', 'nqn', 'host-traddr', 'host-iface', 'hostnqn', 'hostid'))


class InvalidOption(Exception):
    '''Exception raised when an invalid option value is detected'''


def _parse_controller(controller):
    '''Parse a "controller" config entry. Entries are semicolon-delimited
    "key=value" pairs. Returns a dict of the parsed pairs.'''
    options = dict()
    tokens = __TOKEN_RE.split(controller)
    for token in tokens:
        if token:
            try:
                option, val = token.split('=', 1)
                options[option.strip()] = val.strip()
            except ValueError:
                pass

    return options


def libnvme_ctx():
    '''Return the libnvme context used to read libnvme's host-wide config files.

    This context is only ever used to read files; it never connects. It
    therefore declares no owner, for the same reason staslib/nbft.py does not.
    Tests can redirect the files it reads with ctx.set_test_base_dir().
    '''
    global _LIBNVME_CTX  # pylint: disable=global-statement
    if _LIBNVME_CTX is None:
        _LIBNVME_CTX = nvme.GlobalCtx()
    return _LIBNVME_CTX


def _libnvme_excluded():
    '''Return libnvme's host-wide exclusion list, in the same format as the
    "exclude=" entries of stafd.conf/stacd.conf.

    The list (/etc/nvme/exclusions.conf and /etc/nvme/exclusions.conf.d/) is
    read live, on every call. It is a host-wide file that other tools
    ("nvme exclusion add", "nvme disconnect --exclude") write behind our back,
    so an entry added there must take effect on the next connection attempt
    without reloading stafd/stacd.
    '''
    ctx = libnvme_ctx()
    try:
        entries = list(nvme.exclusion_entries(ctx, None))  # name=None: the main list
        for name in nvme.exclusion_lists(ctx):  # named drop-in lists
            entries.extend(nvme.exclusion_entries(ctx, name))
    except OSError as ex:
        # A list we can't read must never block connectivity.
        logging.warning('Unable to read libnvme\'s exclusion list: %s', ex)
        return []

    excluded = []
    for entry in entries:
        cid = _parse_controller(entry)

        # libnvme ignores an entry it cannot parse: an unknown key, a bare
        # token, or an empty value makes the whole entry match nothing. We
        # must do the same, and not merely skip the offending key. Note that
        # "subsysnqn=" is one of those unknown keys: it is a documented typo
        # for "nqn=" that libnvme deliberately leaves inert, yet it happens to
        # be the spelling our own matching uses.
        if not cid or any(key not in _EXCLUSION_KEYS or not val for key, val in cid.items()):
            continue

        try:
            # libnvme spells the subsystem NQN "nqn".
            cid['subsysnqn'] = cid.pop('nqn')
        except KeyError:
            pass

        # Our TIDs carry no hostid, so an entry naming one is resolved here
        # instead of at match time: our own hostid is satisfied by definition,
        # another host's can never match anything here. Only look up our
        # hostid if an entry asks for it.
        satisfied = 'hostid' in cid
        if satisfied and cid.pop('hostid') != SysConf().hostid:
            continue

        # _excluded() reads an empty dict as "matches everything", which is
        # exactly what an entry naming only our hostid means.
        excluded.append(cid)

    return excluded


def _parse_single_val(text):
    if isinstance(text, str):
        return text
    if not isinstance(text, list) or not text:
        return None

    return text[-1]


def _parse_list(text):
    return text if isinstance(text, list) else [text]


def _to_int(text):
    try:
        return int(_parse_single_val(text))
    except (ValueError, TypeError):
        raise InvalidOption from None


def _to_bool(text, positive='true'):
    val = _parse_single_val(text)
    return val is not None and val.lower() == positive


def _to_ncc(text):
    value = _to_int(text)
    if value == 1:  # 1 is invalid. A minimum of 2 is required (with the exception of 0, which is valid).
        value = 2
    return value


def _to_ip_family(text):
    return tuple((4 if token == 'ipv4' else 6 for token in _parse_single_val(text).split('+')))


# ******************************************************************************
class OrderedMultisetDict(dict):
    '''This class is used to change the behavior of configparser.ConfigParser
    and allow multiple configuration parameters with the same key. The
    result is a list of values, where values are sorted by the order they
    appear in the file.

    Note: configparser internally joins repeated keys with '\\n' when
    strict=False. __getitem__ splits on '\\n' to reconstruct the list, so
    callers always receive a list of strings rather than a single newline-
    joined string.
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

    OPTION_CHECKER = {
        'Global': {
            'tron': {
                'convert': _to_bool,
                'default': False,
                'txt-chk': lambda text: str(_parse_single_val(text)).lower() in ('false', 'true'),
            },
            'pleo': {
                'convert': functools.partial(_to_bool, positive='enabled'),
                'default': True,
                'txt-chk': lambda text: str(_parse_single_val(text)).lower() in ('disabled', 'enabled'),
            },
            'ip-family': {
                'convert': _to_ip_family,
                'default': (4, 6),
                'txt-chk': lambda text: _parse_single_val(text) in ('ipv4', 'ipv6', 'ipv4+ipv6', 'ipv6+ipv4'),
            },
            'ignore-iface': {
                'convert': _to_bool,
                'default': False,
                'txt-chk': lambda text: str(_parse_single_val(text)).lower() in ('false', 'true'),
            },
        },
        'Service Discovery': {
            'zeroconf': {
                'convert': functools.partial(_to_bool, positive='enabled'),
                'default': True,
                'txt-chk': lambda text: str(_parse_single_val(text)).lower() in ('disabled', 'enabled'),
            },
        },
        'Discovery controller connection management': {
            'persistent-connections': {
                'convert': _to_bool,
                'default': True,
                'txt-chk': lambda text: str(_parse_single_val(text)).lower() in ('false', 'true'),
            },
            'zeroconf-connections-persistence': {
                'convert': lambda text: timeparse.timeparse(_parse_single_val(text)),
                'default': timeparse.timeparse('72hours'),
            },
        },
        'I/O controller connection management': {
            'honor-fabric-zoning': {
                'convert': functools.partial(_to_bool, positive='yes'),
                'default': True,
                'txt-chk': lambda text: str(_parse_single_val(text)).lower() in ('yes', 'no'),
            },
            'connect-attempts-on-ncc': {
                'convert': _to_ncc,
                'default': 0,
            },
        },
        'Controllers': {
            'exclude': {
                'convert': _parse_list,
                'default': [],
            },
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
        '''Reload the configuration file.'''
        self._config = self._read_conf_file()

    @property
    def conf_file(self):
        '''Return the configuration file name'''
        return self._conf_file

    def set_conf_file(self, fname):
        '''Set the configuration file name and reload config'''
        self._conf_file = fname
        self.reload()

    def get_option(self, section, option, ignore_default=False):
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
    ip_family = property(functools.partial(get_option, section='Global', option='ip-family'))
    ignore_iface = property(functools.partial(get_option, section='Global', option='ignore-iface'))
    pleo_enabled = property(functools.partial(get_option, section='Global', option='pleo'))

    zeroconf_persistence_sec = property(
        functools.partial(
            get_option, section='Discovery controller connection management', option='zeroconf-connections-persistence'
        )
    )

    honor_fabric_zoning = property(
        functools.partial(get_option, section='I/O controller connection management', option='honor-fabric-zoning')
    )
    connect_attempts_on_ncc = property(
        functools.partial(get_option, section='I/O controller connection management', option='connect-attempts-on-ncc')
    )

    @property
    def zeroconf_enabled(self):
        '''Return whether zeroconf is enabled'''
        return self.get_option(section='Service Discovery', option='zeroconf')

    @property
    def stypes(self):
        '''Return the DNS-SD/mDNS service types to browse.'''
        return ['_nvme-disc._tcp', '_nvme-disc._udp'] if self.zeroconf_enabled else list()

    @property
    def persistent_connections(self):
        '''Return the "persistent-connections" config parameter.'''
        section = 'Discovery controller connection management'
        option = 'persistent-connections'

        # Use ignore_default=True so we can distinguish "not set in file" from
        # "set to false". The per-daemon default (stafd vs stacd) differs and is
        # held in self._defaults rather than in OPTION_CHECKER, so we fall back
        # to that dict explicitly.
        value = self.get_option(section, option, ignore_default=True)
        if value is not None:
            return value

        return self._defaults.get((section, option), True)

    def get_excluded(self):
        '''Return the list of excluded controllers. This is the union of the
        "exclude=" entries of this daemon's config file and libnvme's host-wide
        exclusion list: a controller is excluded if it matches either.

        Each entry is a dict with optional keys:
        {
            'transport':   [TRANSPORT],
            'traddr':      [TRADDR],
            'trsvcid':     [TRSVCID],
            'host-iface':  [IFACE],
            'host-traddr': [TRADDR],   (libnvme entries only)
            'hostnqn':     [NQN],      (libnvme entries only)
            'subsysnqn':   [NQN],
        }

        Note that "exclude=" is deprecated in favour of libnvme's list, and
        that the two are not read the same way: "exclude=" is read from the
        config file we already hold, whereas libnvme's list is re-read from
        disk on every call (see _libnvme_excluded()).
        '''
        controller_list = self.get_option('Controllers', 'exclude')
        excluded = [_parse_controller(controller) for controller in controller_list]
        for controller in excluded:
            controller.pop('host-traddr', None)  # remove host-traddr
            try:
                # replace 'nqn' key by 'subsysnqn', if present.
                controller['subsysnqn'] = controller.pop('nqn')
            except KeyError:
                pass

        # An entry that sets no field would match every controller.
        excluded = [controller for controller in excluded if controller]

        return excluded + _libnvme_excluded()

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
        '''Read and return a ConfigParser for the configuration file (if it exists).'''
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
class ConnConf(metaclass=singleton.Singleton):
    '''Connectivity configuration: which controllers to connect to, and with
    what parameters.

    This is libnvme's INI format, read through libnvme's own parser, so that
    nvme-stas, the nvme-cli tools and nvme-discoverd all understand one format
    and there is only ever one implementation of it. nvme-stas keeps its own
    file, /etc/nvme/nvme-stas.conf: a host must be able to run nvme-stas and
    nvme-discoverd side by side, each connecting its own controllers, so they
    never share a connectivity file even though they share its format.

    libnvme resolves the whole cascade - type defaults, the file's [Host]
    section, the endpoint section, and the "controller =" line - before we see
    anything, and hands back one entry per controller with its parameters
    already merged. A [Subsystem] with several "controller =" lines arrives as
    several entries, one per path.
    '''

    # Parameters we hand to the kernel as-is. Everything else libnvme resolves
    # is carried through untouched for whoever knows what to do with it (the
    # credentials, for instance, which ctrl.py reads straight from the TID).
    _NUMERIC = frozenset(
        (
            'keep-alive-tmo',
            'tos',
            'queue-size',
            'nr-io-queues',
            'ctrl-loss-tmo',
            'nr-poll-queues',
            'nr-write-queues',
            'reconnect-delay',
            'fast-io-fail-tmo',
        )
    )
    _BOOLEAN = frozenset(('tls', 'concat', 'hdr-digest', 'data-digest', 'disable-sqflow'))

    def __init__(self, conf_file=defs.NVME_STAS_CONF_FILE):
        self._conf_file = conf_file
        self._connections = list()
        self._dc_defaults = dict()
        self._ioc_defaults = dict()
        self._host = dict()
        self.reload()

    @property
    def conf_file(self):
        '''Return the configuration file name'''
        return self._conf_file

    def set_conf_file(self, fname):
        '''Set the configuration file name and reload the configuration'''
        self._conf_file = fname
        self.reload()

    def reload(self):
        '''Re-read the configuration file.

        A file that does not validate is rejected and the last known good
        configuration is left running: a fat-fingered edit must never tear down
        working connections. An absent file is not an error - it simply
        configures no controllers.

        Return True if the configuration was (re)loaded, False if the file was
        rejected and the previous one kept.
        '''
        ctx = libnvme_ctx()
        try:
            nvme.config_validate(ctx, self._conf_file)
            connections = nvme.config_read(ctx, self._conf_file)
            defaults = nvme.config_defaults(ctx, self._conf_file)
            host = nvme.config_host(ctx, self._conf_file)
        except (OSError, ValueError) as ex:
            logging.error(
                'File:%s - Invalid connectivity configuration, keeping the previous one: %s', self._conf_file, ex
            )
            return False

        self._connections = connections
        self._dc_defaults = self._params(defaults.get('dc', {}))
        self._ioc_defaults = self._params(defaults.get('ioc', {}))
        self._host = host
        logging.debug('ConnConf.reload()                  - %s connection(s)', len(connections))
        return True

    def get_controllers(self, discovery: bool):
        '''Return the configured controllers as controller-identifier dicts.

        @discovery selects which half of the file to return: the
        [Discovery Controller] sections when True, the [Subsystem] sections
        when False. One file serves both daemons.
        '''
        return [self._to_cid(conn) for conn in self._connections if conn.get('is_dc', False) == discovery]

    def defaults(self, discovery: bool):
        '''Return the default connection parameters for a controller we
        discovered, which is in no file and so has no parameters of its own.

        These are the top-level file's defaults for the controller's class. A
        drop-in's are deliberately out of reach: a controller found over mDNS,
        or in a discovery log page, cannot be attributed to one.
        '''
        return self._dc_defaults if discovery else self._ioc_defaults

    hostnqn = property(lambda self: self._host.get('hostnqn'))
    hostid = property(lambda self: self._host.get('hostid'))
    hostsymname = property(lambda self: self._host.get('hostsymname'))

    def _params(self, params: dict):
        '''Convert libnvme's parameters to the types the kernel expects,
        dropping anything we cannot represent.'''
        out = dict()
        for option, text in params.items():
            value = self._value(option, text)
            if value is not None:
                out[option] = value

        return out

    def _to_cid(self, conn: dict):
        '''Translate one libnvme connection into a controller-identifier dict.'''
        cid = {
            'transport': conn.get('transport', ''),
            'traddr': conn.get('traddr', ''),
            'trsvcid': conn.get('trsvcid', ''),
            'subsysnqn': conn.get('subsysnqn', ''),
            # libnvme spells the host binding with underscores, we use hyphens.
            'host-traddr': conn.get('host_traddr', ''),
            'host-iface': conn.get('host_iface', ''),
            'hostnqn': conn.get('hostnqn', ''),
        }

        # Carried for the connection, not for the transport ID: a file's
        # [Host] section applies to every connection in it.
        for key in ('hostid', 'hostsymname'):
            if conn.get(key):
                cid[key] = conn[key]

        cid.update(self._params(conn.get('params', {})))

        return cid

    def _value(self, option, text):
        '''Convert a parameter to the type the kernel expects, or return None
        to leave it unset so that the kernel default applies.

        libnvme has already validated the file, so anything rejected here is a
        value we cannot represent rather than a malformed one.
        '''
        if not text:
            # "key =" resets a parameter to the kernel default: leave it out.
            return None

        if option in self._NUMERIC:
            try:
                return int(text)
            except (ValueError, TypeError):
                logging.warning(
                    'File:%s: %s - invalid value "%s", the kernel default will be used',
                    self._conf_file,
                    option,
                    text,
                )
                return None

        if option in self._BOOLEAN:
            return text.strip().lower() in ('1', 'y', 'yes', 't', 'true', 'on')

        return text


# ******************************************************************************
class SysConf(metaclass=singleton.Singleton):
    '''The host's system-wide identity, as the nvme-cli family records it in
    /etc/nvme/hostnqn and /etc/nvme/hostid.

    The host symbolic name is not here. It has no system-wide file, and is
    named in the connectivity configuration's [Host] section, which ConnConf
    reads. Nor is the KXCHAP secret: it is a connection parameter, and comes
    from the connectivity configuration with the rest of them.
    '''

    def __init__(self, hostnqn_file=defs.NVME_HOSTNQN, hostid_file=defs.NVME_HOSTID):
        self._hostnqn_file = hostnqn_file
        self._hostid_file = hostid_file

    def as_dict(self):
        '''Return the host identity as a dictionary'''
        return {
            'hostnqn': self.hostnqn,
            'hostid': self.hostid,
        }

    @property
    def hostnqn(self):
        '''Return the host NQN. Exits the program if it cannot be determined,
        as it is mandatory.'''
        value = self._read(self._hostnqn_file)
        if value is None:
            sys.exit(f'Error reading mandatory Host NQN from {self._hostnqn_file}')

        if not value.startswith('nqn.'):
            sys.exit(f'Error Host NQN "{value}" should start with "nqn."')
        if len(value) > 223:
            sys.exit(f'Error Host NQN is too long ({len(value)} chars, max 223 per NVMe spec)')

        return value

    @property
    def hostid(self):
        '''Return the host ID. Exits the program if it cannot be determined,
        as it is mandatory.'''
        value = self._read(self._hostid_file)
        if value is None:
            sys.exit(f'Error reading mandatory Host ID from {self._hostid_file}')

        return value

    @staticmethod
    def _read(fname):
        '''Return the first word of the first line of @fname, or None if the
        file is missing or holds nothing usable.'''
        try:
            with open(fname) as f:
                return f.readline().split()[0]
        except (OSError, IndexError):
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
        #
        # The keys must match the option names the kernel prints in
        # '/dev/nvme-fabrics'. TP4201 renamed DHCHAP to KXCHAP in the libnvme
        # API, but the kernel option names are unchanged.
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
                with open('/dev/nvme-fabrics') as f:
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
    def kxchap_hostkey_supp(self):
        '''This option allows specifying the host KXCHAP key used for authentication.'''
        return self._supported_options['dhchap_secret']

    @property
    def kxchap_ctrlkey_supp(self):
        '''This option allows specifying the controller KXCHAP key used for authentication.'''
        return self._supported_options['dhchap_ctrl_secret']


# NBFT bit positions the libnvme Python bindings no longer decode for us --
# they hand back the raw descriptor "flags"/"trflags" field instead (NVMe
# Boot Specification: Host Descriptor Flags / SSNS Transport Specific Flags).
_NBFT_HOST_HOSTNQN_CONFIGURED = 1 << 2
_NBFT_SSNS_PDU_HEADER_DIGEST = 1 << 1
_NBFT_SSNS_DATA_DIGEST = 1 << 2


# ******************************************************************************
class NbftConf(metaclass=singleton.Singleton):
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
            hostnqn = host.get('nqn', None) if host.get('flags', 0) & _NBFT_HOST_HOSTNQN_CONFIGURED else None

            self._disc_ctrls.extend(NbftConf.__nbft_disc_to_cids(hostnqn, discovery, hfis))
            self._subs_ctrls.extend(NbftConf.__nbft_subs_to_cids(hostnqn, subsystem, hfis))

    dcs = property(lambda self: self._disc_ctrls)
    iocs = property(lambda self: self._subs_ctrls)

    @staticmethod
    def __nbft_disc_to_cids(hostnqn, discovery, hfis):
        cids = []

        for ctrl in discovery:
            cid = NbftConf.__uri2cid(ctrl['uri'])
            cid['subsysnqn'] = ctrl['nqn']
            if hostnqn:
                cid['hostnqn'] = hostnqn

            host_iface = NbftConf.__get_host_iface(ctrl.get('hfi_index'), hfis)
            if host_iface:
                cid['host-iface'] = host_iface

            cids.append(cid)

        return cids

    @staticmethod
    def __nbft_subs_to_cids(hostnqn, subsystem, hfis):
        cids = []

        for ctrl in subsystem:
            trflags = ctrl.get('trflags', 0)
            cid = {
                'transport': ctrl['trtype'],
                'traddr': ctrl['traddr'],
                'trsvcid': ctrl['trsvcid'],
                'subsysnqn': ctrl['subsys_nqn'],
                'hdr-digest': bool(trflags & _NBFT_SSNS_PDU_HEADER_DIGEST),
                'data-digest': bool(trflags & _NBFT_SSNS_DATA_DIGEST),
            }
            if hostnqn:
                cid['hostnqn'] = hostnqn

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
            'transport': obj.scheme.partition('+')[2],
            'traddr': obj.hostname,
            'trsvcid': str(obj.port) if obj.port is not None else '',
        }
