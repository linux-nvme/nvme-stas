# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''Module that provides a way to retrieve discovered
services from the Avahi daemon over D-Bus.
'''

import socket
import typing
import logging
import functools
import dasbus.error
import dasbus.connection
import dasbus.client.proxy
import dasbus.client.observer
from gi.repository import GLib
from staslib import defs, conf, gutil, iputil


def _txt2dict(txt: list):
    '''@param txt: A list of list of integers. The integers are the ASCII value
    of printable text characters.
    '''
    the_dict = dict()
    for list_of_chars in txt:
        try:
            string = functools.reduce(lambda accumulator, c: accumulator + chr(c), list_of_chars, '')
            if string.isprintable():
                key, val = string.split('=')
                if key:  # Make sure the key is not an empty string
                    the_dict[key.lower()] = val
        except ValueError:
            pass

    return the_dict


def _proto2trans(protocol):
    '''Return the matching transport for the given protocol.'''
    if protocol is None:
        return None

    protocol = protocol.strip().lower()
    if protocol == 'tcp':
        return 'tcp'

    if protocol in ('roce', 'iwarp', 'rdma'):
        return 'rdma'

    return None


def mk_service_key(interface, protocol, name, stype, domain):
    '''Return a tuple used as a service key (unique identifier)'''
    return (interface, protocol, name, stype, domain)


def fmt_service_str(interface, protocol, name, stype, domain, flags):  # pylint: disable=too-many-arguments
    '''Return service identifier as a string'''
    return (
        f'interface={interface}:{(socket.if_indextoname(interface) + ","):<9} '
        f'protocol={Avahi.protocol_as_string(protocol)}, '
        f'stype={stype}, '
        f'domain={domain}, '
        f'flags={flags}:{(Avahi.result_flags_as_string(flags) + ","):<12} '
        f'name={name}'
    )


class ValueRange:
    '''Implement a range of values with ceiling. Once the ceiling has been
    reached, then any further request for a new value will return the
    ceiling (i.e last value).'''

    def __init__(self, values: list):
        self._values = values
        self._index = 0

    def get_next(self):
        '''Get the next value (or last value if ceiling was reached)'''
        value = self._values[self._index]
        if self._index >= 0:
            self._index += 1
            if self._index >= len(self._values):
                self._index = -1
        return value

    def reset(self):
        '''Reset the range to start from the beginning'''
        self._index = 0


# ******************************************************************************
class Service:  # pylint: disable=too-many-instance-attributes
    '''Object used to keep track of the services discovered from the avahi-daemon'''

    interface_name = property(lambda self: self._interface_name)
    interface = property(lambda self: self._interface_id)
    ip_family = property(lambda self: self._ip_family)
    reachable = property(lambda self: self._reachable)
    protocol = property(lambda self: self._protocol_id)
    key_str = property(lambda self: self._key_str)
    domain = property(lambda self: self._domain)
    stype = property(lambda self: self._stype)
    data = property(lambda self: self._data)
    name = property(lambda self: self._name)
    key = property(lambda self: self._key)
    ip = property(lambda self: self._ip)

    def __init__(self, args, identified_cback):
        self._identified_cback = identified_cback
        self._interface_id = args[0]
        self._protocol_id = args[1]
        self._name = args[2]
        self._stype = args[3]
        self._domain = args[4]
        self._flags = args[5]
        self._ip_family = 4 if self._protocol_id == Avahi.PROTO_INET else 6

        self._interface_name = socket.if_indextoname(self._interface_id).strip()
        self._protocol_name = Avahi.protocol_as_string(self._protocol_id)
        self._flags_str = '(' + Avahi.result_flags_as_string(self._flags) + '),'

        self._key = mk_service_key(self._interface_id, self._protocol_id, self._name, self._stype, self._domain)
        self._key_str = f'({self._interface_name}, {self._protocol_name}, {self._name}.{self._domain}, {self._stype})'

        self._id = fmt_service_str(
            self._interface_id, self._protocol_id, self._name, self._stype, self._domain, self._flags
        )

        self._connect_check_retry_tmo = ValueRange([2, 5, 10, 30, 60, 300, 600])
        self._connect_check_retry_tmr = gutil.GTimer(
            self._connect_check_retry_tmo.get_next(), self._on_connect_check_retry
        )

        self._ip = None
        self._resolver = None
        self._data = {}
        self._reachable = False
        self._connect_checker = None

    def info(self):
        '''Return debug info'''
        info = self._data
        info['reachable'] = str(self._reachable)
        return info

    def __str__(self):
        return self._id

    def set_identity(self, transport, address, port, txt):  # pylint: disable=too-many-arguments
        '''Complete identification and check connectivity (if needed)
        Return True if identification is complete. Return False if
        we need to check connectivity.
        '''
        traddr = address.strip()
        trsvcid = str(port).strip()
        # host-iface permitted for tcp alone and not rdma
        host_iface = self._interface_name if transport == 'tcp' else ''
        self._data = {
            'transport': transport,
            'traddr': traddr,
            'trsvcid': trsvcid,
            # host-iface permitted for tcp alone and not rdma
            'host-iface': host_iface,
            'subsysnqn': (
                txt.get('nqn', defs.WELL_KNOWN_DISC_NQN).strip()
                if conf.NvmeOptions().discovery_supp
                else defs.WELL_KNOWN_DISC_NQN
            ),
        }

        self._ip = iputil.get_ipaddress_obj(traddr, ipv4_mapped_convert=True)

        if transport != 'tcp':
            self._reachable = True
            self._identified_cback()
            return

        self._connect_check(verbose=True)  # Enable verbosity on first attempt

    def _connect_check(self, verbose=False):
        self._reachable = False
        connect_checker = gutil.TcpChecker(
            self._data['traddr'],
            self._data['trsvcid'],
            self._data['host-iface'],
            verbose,
            self._tcp_connect_check_cback,
        )

        try:
            connect_checker.connect()
        except RuntimeError as err:
            logging.error('Unable to verify connectivity: %s', err)
            connect_checker.close()
            connect_checker = None

        self._connect_checker = connect_checker

    def _tcp_connect_check_cback(self, connected):
        if self._connect_checker is not None:
            self._connect_checker.close()
            self._connect_checker = None
            self._reachable = connected

            if self._reachable:
                self._identified_cback()
            else:
                # Restart the timer but with incremented timeout
                self._connect_check_retry_tmr.start(self._connect_check_retry_tmo.get_next())

    def _on_connect_check_retry(self):
        self._connect_check()
        return GLib.SOURCE_REMOVE

    def set_resolver(self, resolver):
        '''Set the resolver object'''
        self._resolver = resolver

    def close(self):
        '''Close this object and release all resources'''
        if self._connect_checker is not None:
            self._connect_checker.close()
            self._connect_checker = None

        if self._resolver is not None:
            try:
                self._resolver.Free()
                dasbus.client.proxy.disconnect_proxy(self._resolver)
            except (AttributeError, dasbus.error.DBusError) as ex:
                logging.debug('Service.close()                    - Failed to Free() resolver. %s', ex)
            self._resolver = None


# ******************************************************************************
class Avahi:  # pylint: disable=too-many-instance-attributes
    '''@brief Avahi Server proxy. Set up the D-Bus connection to the Avahi
    daemon and register to be notified when services of a certain
    type (stype) are discovered or lost.
    '''

    DBUS_NAME = 'org.freedesktop.Avahi'
    DBUS_INTERFACE_SERVICE_BROWSER = DBUS_NAME + '.ServiceBrowser'
    DBUS_INTERFACE_SERVICE_RESOLVER = DBUS_NAME + '.ServiceResolver'
    LOOKUP_USE_MULTICAST = 2

    IF_UNSPEC = -1
    PROTO_INET = 0
    PROTO_INET6 = 1
    PROTO_UNSPEC = -1

    LOOKUP_RESULT_LOCAL = 8  # This record/service resides on and was announced by the local host
    LOOKUP_RESULT_CACHED = 1  # This response originates from the cache
    LOOKUP_RESULT_STATIC = 32  # The returned data has been defined statically by some configuration option
    LOOKUP_RESULT_OUR_OWN = 16  # This service belongs to the same local client as the browser object
    LOOKUP_RESULT_WIDE_AREA = 2  # This response originates from wide area DNS
    LOOKUP_RESULT_MULTICAST = 4  # This response originates from multicast DNS

    result_flags = {
        LOOKUP_RESULT_LOCAL: 'local',
        LOOKUP_RESULT_CACHED: 'cache',
        LOOKUP_RESULT_STATIC: 'static',
        LOOKUP_RESULT_OUR_OWN: 'own',
        LOOKUP_RESULT_WIDE_AREA: 'wan',
        LOOKUP_RESULT_MULTICAST: 'mcast',
    }

    protos = {PROTO_INET: 'IPv4', PROTO_INET6: 'IPv6', PROTO_UNSPEC: 'uspecified'}

    @classmethod
    def result_flags_as_string(cls, flags):
        '''Convert flags to human-readable string'''
        return '+'.join((value for flag, value in Avahi.result_flags.items() if (flags & flag) != 0))

    @classmethod
    def protocol_as_string(cls, proto):
        '''Convert protocol codes to human-readable strings'''
        return Avahi.protos.get(proto, 'unknown')

    # ==========================================================================
    def __init__(self, sysbus, change_cb):
        self._change_cb = change_cb
        self._services = dict()
        self._sysbus = sysbus
        self._stypes = set()
        self._service_browsers = dict()

        # Avahi is an on-demand service. If, for some reason, the avahi-daemon
        # were to stop, we need to try to contact it for it to restart. For
        # example, when installing the avahi-daemon package on a running system,
        # the daemon doesn't get started right away. It needs another process to
        # access it over D-Bus to wake it up. The following timer is used to
        # periodically query the avahi-daemon until we successfully establish
        # first contact.
        self._kick_avahi_tmr = gutil.GTimer(60, self._on_kick_avahi)

        # Subscribe for Avahi signals (i.e. events). This must be done before
        # any Browser or Resolver is created to avoid race conditions and
        # missed events.
        self._subscriptions = [
            self._sysbus.connection.signal_subscribe(
                Avahi.DBUS_NAME,
                Avahi.DBUS_INTERFACE_SERVICE_BROWSER,
                'ItemNew',
                None,
                None,
                0,
                self._service_discovered,
            ),
            self._sysbus.connection.signal_subscribe(
                Avahi.DBUS_NAME,
                Avahi.DBUS_INTERFACE_SERVICE_BROWSER,
                'ItemRemove',
                None,
                None,
                0,
                self._service_removed,
            ),
            self._sysbus.connection.signal_subscribe(
                Avahi.DBUS_NAME, Avahi.DBUS_INTERFACE_SERVICE_BROWSER, 'Failure', None, None, 0, self._failure_handler
            ),
            self._sysbus.connection.signal_subscribe(
                Avahi.DBUS_NAME, Avahi.DBUS_INTERFACE_SERVICE_RESOLVER, 'Found', None, None, 0, self._service_identified
            ),
            self._sysbus.connection.signal_subscribe(
                Avahi.DBUS_NAME, Avahi.DBUS_INTERFACE_SERVICE_RESOLVER, 'Failure', None, None, 0, self._failure_handler
            ),
        ]

        self._avahi = self._sysbus.get_proxy(Avahi.DBUS_NAME, '/')

        self._avahi_watcher = dasbus.client.observer.DBusObserver(self._sysbus, Avahi.DBUS_NAME)
        self._avahi_watcher.service_available.connect(self._avahi_available)
        self._avahi_watcher.service_unavailable.connect(self._avahi_unavailable)
        self._avahi_watcher.connect_once_available()

    def kill(self):
        '''@brief Clean up object'''
        logging.debug('Avahi.kill()')

        self._kick_avahi_tmr.kill()
        self._kick_avahi_tmr = None

        for subscription in self._subscriptions:
            self._sysbus.connection.signal_unsubscribe(subscription)
        self._subscriptions = list()

        self._disconnect()

        self._avahi_watcher.service_available.disconnect()
        self._avahi_watcher.service_unavailable.disconnect()
        self._avahi_watcher.disconnect()
        self._avahi_watcher = None

        dasbus.client.proxy.disconnect_proxy(self._avahi)
        self._avahi = None

        self._change_cb = None
        self._sysbus = None

    def info(self) -> dict:
        '''@brief return debug info about this object'''
        info = {
            'avahi wake up timer': str(self._kick_avahi_tmr),
            'service types': list(self._stypes),
            'services': {service.key_str: service.info() for service in self._services.values()},
        }

        return info

    def get_controllers(self) -> list:
        '''@brief Get the discovery controllers as a list of dict()
        as follows:
        [
            {
                'transport': tcp,
                'traddr': str(),
                'trsvcid': str(),
                'subsysnqn': 'nqn.2014-08.org.nvmexpress.discovery',
                'host-traddr': str(),
                'host-iface': str(),
                'host-nqn': str(),
            },
            {
                'transport': tcp,
                'traddr': str(),
                'trsvcid': str(),
                'subsysnqn': 'nqn.2014-08.org.nvmexpress.discovery',
                'host-traddr': str(),
                'host-iface': str(),
                'host-nqn': str(),
            },
            [...]
        ]
        '''
        return [service.data for service in self._services.values() if service.reachable]

    def config_stypes(self, stypes: list):
        '''@brief Configure the service types that we want to discover.
        @param stypes: A list of services types, e.g. ['_nvme-disc._tcp']
        '''
        self._stypes = set(stypes)
        success = self._configure_browsers()
        if not success:
            self._kick_avahi_tmr.start()

    def kick_start(self):
        '''@brief We use this to kick start the Avahi
        daemon (i.e. socket activation).
        '''
        self._kick_avahi_tmr.clear()

    def _remove_service(self, service_to_rm: typing.Tuple[int, int, str, str, str]):
        service = self._services.pop(service_to_rm)
        if service is not None:
            service.close()

    def _disconnect(self):
        logging.debug('Avahi._disconnect()')
        for service in self._services.values():
            service.close()

        self._services.clear()

        for browser in self._service_browsers.values():
            try:
                browser.Free()
                dasbus.client.proxy.disconnect_proxy(browser)
            except (AttributeError, dasbus.error.DBusError) as ex:
                logging.debug('Avahi._disconnect()                - Failed to Free() browser. %s', ex)

        self._service_browsers = dict()

    def _on_kick_avahi(self):
        try:
            # try to contact avahi-daemon. This is just a wake
            # up call in case the avahi-daemon was sleeping.
            self._avahi.GetVersionString()
        except dasbus.error.DBusError:
            return GLib.SOURCE_CONTINUE

        return GLib.SOURCE_REMOVE

    def _avahi_available(self, _avahi_watcher):
        '''@brief Hook up DBus signal handlers for signals from stafd.'''
        logging.info('avahi-daemon service available, zeroconf supported.')
        success = self._configure_browsers()
        if not success:
            self._kick_avahi_tmr.start()

    def _avahi_unavailable(self, _avahi_watcher):
        self._disconnect()
        logging.warning('avahi-daemon not available, zeroconf not supported.')
        self._kick_avahi_tmr.start()

    def _configure_browsers(self):
        stypes_cur = set(self._service_browsers.keys())
        stypes_to_add = self._stypes - stypes_cur
        stypes_to_rm = stypes_cur - self._stypes

        logging.debug('Avahi._configure_browsers()        - stypes_to_rm  = %s', list(stypes_to_rm))
        logging.debug('Avahi._configure_browsers()        - stypes_to_add = %s', list(stypes_to_add))

        for stype_to_rm in stypes_to_rm:
            browser = self._service_browsers.pop(stype_to_rm, None)
            if browser is not None:
                try:
                    browser.Free()
                    dasbus.client.proxy.disconnect_proxy(browser)
                except (AttributeError, dasbus.error.DBusError) as ex:
                    logging.debug('Avahi._configure_browsers()        - Failed to Free() browser. %s', ex)

            # Find the cached services corresponding to stype_to_rm and remove them
            services_to_rm = [service.key for service in self._services.values() if service.stype == stype_to_rm]
            for service_to_rm in services_to_rm:
                self._remove_service(service_to_rm)

        for stype in stypes_to_add:
            try:
                obj_path = self._avahi.ServiceBrowserNew(
                    Avahi.IF_UNSPEC, Avahi.PROTO_UNSPEC, stype, 'local', Avahi.LOOKUP_USE_MULTICAST
                )
                self._service_browsers[stype] = self._sysbus.get_proxy(Avahi.DBUS_NAME, obj_path)
            except dasbus.error.DBusError as ex:
                logging.debug('Avahi._configure_browsers()        - Failed to contact avahi-daemon. %s', ex)
                logging.warning('avahi-daemon not available, operating w/o mDNS discovery.')
                return False

        return True

    def _service_discovered(
        self,
        _connection,
        _sender_name: str,
        _object_path: str,
        _interface_name: str,
        _signal_name: str,
        args: typing.Tuple[int, int, str, str, str, int],
        *_user_data,
    ):
        service = Service(args, self._change_cb)
        logging.debug('Avahi._service_discovered()        - %s', service)

        if service.key not in self._services:
            try:
                obj_path = self._avahi.ServiceResolverNew(
                    service.interface,
                    service.protocol,
                    service.name,
                    service.stype,
                    service.domain,
                    Avahi.PROTO_UNSPEC,
                    Avahi.LOOKUP_USE_MULTICAST,
                )
                service.set_resolver(self._sysbus.get_proxy(Avahi.DBUS_NAME, obj_path))
            except dasbus.error.DBusError as ex:
                logging.warning('Failed to create resolver - %s: %s', service, ex)

            self._services[service.key] = service

    def _service_removed(
        self,
        _connection,
        _sender_name: str,
        _object_path: str,
        _interface_name: str,
        _signal_name: str,
        args: typing.Tuple[int, int, str, str, str, int],
        *_user_data,
    ):
        (interface, protocol, name, stype, domain, flags) = args
        logging.debug(
            'Avahi._service_removed()           - %s',
            fmt_service_str(interface, protocol, name, stype, domain, flags),
        )

        service_key = mk_service_key(interface, protocol, name, stype, domain)
        self._remove_service(service_key)
        if self._change_cb is not None:
            self._change_cb()

    def _service_identified(  # pylint: disable=too-many-locals
        self,
        _connection,
        _sender_name: str,
        _object_path: str,
        _interface_name: str,
        _signal_name: str,
        args: typing.Tuple[int, int, str, str, str, str, int, str, int, list, int],
        *_user_data,
    ):
        (interface, protocol, name, stype, domain, host, aprotocol, address, port, txt, flags) = args
        txt = _txt2dict(txt)
        logging.debug(
            'Avahi._service_identified()        - %s, host=%s, aprotocol=%s, port=%s, address=%s, txt=%s',
            fmt_service_str(interface, protocol, name, stype, domain, flags),
            host,
            Avahi.protocol_as_string(aprotocol),
            port,
            address,
            txt,
        )

        service_key = mk_service_key(interface, protocol, name, stype, domain)
        service = self._services.get(service_key, None)
        if service is not None:
            transport = _proto2trans(txt.get('p'))
            if transport is not None:
                service.set_identity(transport, address, port, txt)
            else:
                logging.error(
                    'Received invalid/undefined protocol in mDNS TXT field: address=%s, iface=%s, TXT=%s',
                    address,
                    socket.if_indextoname(interface).strip(),
                    txt,
                )

            self._check_for_duplicate_ips()

    def _failure_handler(
        self,
        _connection,
        _sender_name: str,
        _object_path: str,
        interface_name: str,
        _signal_name: str,
        args: typing.Tuple[str],
        *_user_data,
    ):
        (error,) = args
        if 'ServiceResolver' not in interface_name or 'TimeoutError' not in error:
            # ServiceResolver may fire a timeout event after being Free'd(). This seems to be normal.
            logging.error('Avahi._failure_handler()    - name=%s, error=%s', interface_name, error)

    def _check_for_duplicate_ips(self):
        '''This is to identify misconfigured networks where the
        same IP addresses are discovered on two or more interfaces.'''
        ips = {}
        for service in self._services.values():
            if service.ip is not None:
                ips.setdefault(service.ip.compressed, []).append(service.interface_name)

        for ip, ifaces in ips.items():
            if len(ifaces) > 1:
                logging.error('IP address %s was found on multiple interfaces: %s', ip, ','.join(ifaces))
