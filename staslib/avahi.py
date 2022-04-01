# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
''' Module that provides a way to retrieve discovered
    services from the Avahi daemon over D-Bus.
'''
import socket
import typing
import functools
import dasbus.error
import dasbus.connection
import dasbus.client.proxy
import dasbus.client.observer
from gi.repository import GLib
from staslib import stas

def txt2dict(txt:list):
    ''' @param txt: A list of list of integers. The integers are the ASCII value
                    of printable text characters.
    '''
    the_dict = dict()
    for list_of_chars in txt:
        try:
            string = functools.reduce(lambda accumulator,c: accumulator+chr(c), list_of_chars, '')
            key,val = string.split("=")
            the_dict[key] = val
        except Exception: # pylint: disable=broad-except
            pass

    return the_dict

#*******************************************************************************
class Avahi(): # pylint: disable=too-many-instance-attributes
    ''' @brief Avahi Server proxy. Set up the D-Bus connection to the Avahi
               daemon and register to be notified when services of a certain
               type (stype) are discovered or lost.
    '''

    DBUS_NAME                       = 'org.freedesktop.Avahi'
    DBUS_INTERFACE_SERVICE_BROWSER  = DBUS_NAME + '.ServiceBrowser'
    DBUS_INTERFACE_SERVICE_RESOLVER = DBUS_NAME + '.ServiceResolver'
    LOOKUP_USE_MULTICAST = 2

    IF_UNSPEC    = -1
    PROTO_INET   =  0
    PROTO_INET6  =  1
    PROTO_UNSPEC = -1

    LOOKUP_RESULT_CACHED    = 1   # This response originates from the cache
    LOOKUP_RESULT_WIDE_AREA = 2   # This response originates from wide area DNS
    LOOKUP_RESULT_MULTICAST = 4   # This response originates from multicast DNS
    LOOKUP_RESULT_LOCAL     = 8   # This record/service resides on and was announced by the local host
    LOOKUP_RESULT_OUR_OWN   = 16  # This service belongs to the same local client as the browser object
    LOOKUP_RESULT_STATIC    = 32  # The returned data has been defined statically by some configuration option

    result_flags = {
        LOOKUP_RESULT_CACHED:    'cache',
        LOOKUP_RESULT_WIDE_AREA: 'wan',
        LOOKUP_RESULT_MULTICAST: 'mcast',
        LOOKUP_RESULT_LOCAL:     'local',
        LOOKUP_RESULT_OUR_OWN:   'own',
        LOOKUP_RESULT_STATIC:    'static',
    }

    protos = {
        PROTO_INET:   'IPv4',
        PROTO_INET6:  'IPv6',
        PROTO_UNSPEC: 'uspecified'
    }

    result_flags_as_string = lambda flags: '+'.join((value for flag, value in Avahi.result_flags.items() if (flags & flag) != 0))
    protocol_as_string     = lambda proto: Avahi.protos.get(proto, 'unknown')

    #===========================================================================
    def __init__(self, logger, sysbus, change_cb):
        self._logger    = logger
        self._change_cb = change_cb
        self._services  = dict()
        self._sysbus    = sysbus
        self._stypes    = set()
        self._service_browsers = dict()

        # Avahi is an on-demand service. If, for some reason, the avahi-daemon
        # were to stop, we need to try to contact it for it to restart. For
        # example, when installing the avahi-daemon package on a running system,
        # the daemon doesn't get started right away. It needs another process to
        # access it over D-Bus to wake it up. The following timer is used to
        # periodically query the avahi-daemon until we successfully establish
        # first contact.
        self._kick_avahi_tmr = stas.GTimer(60, self._on_kick_avahi)

        # Subscribe for Avahi signals (i.e. events). This must be done before
        # any Browser or Resolver is created to avoid race conditions and
        # missed events.
        self._subscriptions = [
            self._sysbus.connection.signal_subscribe(Avahi.DBUS_NAME, Avahi.DBUS_INTERFACE_SERVICE_BROWSER,  'ItemNew',    None, None, 0, self._service_discovered),
            self._sysbus.connection.signal_subscribe(Avahi.DBUS_NAME, Avahi.DBUS_INTERFACE_SERVICE_BROWSER,  'ItemRemove', None, None, 0, self._service_removed),
            self._sysbus.connection.signal_subscribe(Avahi.DBUS_NAME, Avahi.DBUS_INTERFACE_SERVICE_BROWSER,  'Failure',    None, None, 0, self._failure_handler),
            self._sysbus.connection.signal_subscribe(Avahi.DBUS_NAME, Avahi.DBUS_INTERFACE_SERVICE_RESOLVER, 'Found',      None, None, 0, self._service_identified),
            self._sysbus.connection.signal_subscribe(Avahi.DBUS_NAME, Avahi.DBUS_INTERFACE_SERVICE_RESOLVER, 'Failure',    None, None, 0, self._failure_handler),
        ]

        self._avahi = self._sysbus.get_proxy(Avahi.DBUS_NAME, '/')

        self._avahi_watcher = dasbus.client.observer.DBusObserver(self._sysbus, Avahi.DBUS_NAME)
        self._avahi_watcher.service_available.connect(self._avahi_available)
        self._avahi_watcher.service_unavailable.connect(self._avahi_unavailable)
        self._avahi_watcher.connect_once_available()

    def kill(self):
        ''' @brief Clean up object
        '''
        self._logger.debug('Avahi.kill()')

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
        self._sysbus    = None

    def info(self) -> dict:
        ''' @brief return debug info about this object
        '''
        services = dict()
        for service, obj in self._services.items():
            interface, protocol, name, stype, domain = service
            key = '({}, {}, {}.{}, {})'.format(socket.if_indextoname(interface), Avahi.protos.get(protocol, 'unknown'), name, domain, stype)  # pylint: disable=consider-using-f-string
            services[key] = obj.get('data', {})

        info = {
            'avahi wake up timer': str(self._kick_avahi_tmr),
            'service types': list(self._stypes),
            'services': services,
        }

        return info

    def get_controllers(self) -> list:
        ''' @brief Get the discovery controllers as a list of dict()
                   as follows:
                   [
                       {
                           'transport': tcp,
                           'traddr': str(),
                           'trsvcid': str(),
                           'host-iface': str(),
                           'subsysnqn': 'nqn.2014-08.org.nvmexpress.discovery',
                       },
                       {
                           'transport': tcp,
                           'traddr': str(),
                           'trsvcid': str(),
                           'host-iface': str(),
                           'subsysnqn': 'nqn.2014-08.org.nvmexpress.discovery',
                       },
                       [...]
                   ]
        '''
        return [ service['data'] for service in self._services.values() if len(service['data']) ]

    def config_stypes(self, stypes:list):
        ''' @brief Configure the service types that we want to discover.
            @param stypes: A list of services types, e.g. ['_nvme-disc._tcp']
        '''
        self._stypes = set(stypes)
        success = self._configure_browsers()
        if not success:
            self._kick_avahi_tmr.start()

    def _disconnect(self):
        self._logger.debug('Avahi._disconnect()')
        for service in self._services.values():
            resolver = service.pop('resolver', None)
            if resolver is not None:
                try:
                    resolver.Free()
                    dasbus.client.proxy.disconnect_proxy(resolver)
                except (AttributeError, dasbus.error.DBusError) as ex:
                    self._logger.debug('Avahi._disconnect()                - Failed to Free() resolver. %s', ex)

        self._services = dict()

        for browser in self._service_browsers.values():
            try:
                browser.Free()
                dasbus.client.proxy.disconnect_proxy(browser)
            except (AttributeError, dasbus.error.DBusError) as ex:
                self._logger.debug('Avahi._disconnect()                - Failed to Free() browser. %s', ex)

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
        ''' @brief Hook up DBus signal handlers for signals from stafd.
        '''
        self._logger.info('avahi-daemon service available, zeroconf supported.')
        success = self._configure_browsers()
        if not success:
            self._kick_avahi_tmr.start()

    def _avahi_unavailable(self, _avahi_watcher):
        self._disconnect()
        self._logger.warning('avahi-daemon not available, zeroconf not supported.')
        self._kick_avahi_tmr.start()

    def _configure_browsers(self):
        stypes_cur    = set(self._service_browsers.keys())
        stypes_to_add = self._stypes - stypes_cur
        stypes_to_rm  = stypes_cur - self._stypes

        self._logger.debug('Avahi._configure_browsers()        - stypes_to_rm  = %s', list(stypes_to_rm))
        self._logger.debug('Avahi._configure_browsers()        - stypes_to_add = %s', list(stypes_to_add))

        for stype_to_rm in stypes_to_rm:
            browser = self._service_browsers.pop(stype_to_rm, None)
            if browser is not None:
                try:
                    browser.Free()
                    dasbus.client.proxy.disconnect_proxy(browser)
                except (AttributeError, dasbus.error.DBusError) as ex:
                    self._logger.debug('Avahi._configure_browsers()        - Failed to Free() browser. %s', ex)

            # Find the cached services corresponding to stype_to_rm and remove them
            services_to_rm = [ service for service in self._services if service[3] == stype_to_rm ]
            for service in services_to_rm:
                resolver = self._services.pop(service, {}).pop('resolver', None)
                if resolver is not None:
                    try:
                        resolver.Free()
                        dasbus.client.proxy.disconnect_proxy(resolver)
                    except (AttributeError, dasbus.error.DBusError) as ex:
                        self._logger.debug('Avahi._configure_browsers()        - Failed to Free() resolver. %s', ex)

        for stype in stypes_to_add:
            try:
                obj_path = self._avahi.ServiceBrowserNew(Avahi.IF_UNSPEC, Avahi.PROTO_UNSPEC, stype, 'local', Avahi.LOOKUP_USE_MULTICAST)
                self._service_browsers[stype] = self._sysbus.get_proxy(Avahi.DBUS_NAME, obj_path)
            except dasbus.error.DBusError as ex:
                self._logger.debug('Avahi._configure_browsers()        - Failed to contact avahi-daemon. %s', ex)
                self._logger.warning('avahi-daemon not available, operating w/o mDNS discovery.')
                return False

        return True

    def _service_discovered(self, _connection, _sender_name:str, _object_path:str, _interface_name:str, _signal_name:str, args:typing.Tuple[int, int, str, str, str, int], *_user_data):
        (interface, protocol, name, stype, domain, flags) = args
        self._logger.debug('Avahi._service_discovered()        - interface=%s (%s), protocol=%s, stype=%s, domain=%s, flags=%s %-14s name=%s',
                           interface, socket.if_indextoname(interface), Avahi.protocol_as_string(protocol), stype, domain, flags, '(' + Avahi.result_flags_as_string(flags) + '),', name)

        service = (interface, protocol, name, stype, domain)
        if service not in self._services:
            try:
                obj_path = self._avahi.ServiceResolverNew(interface, protocol, name, stype, domain, Avahi.PROTO_UNSPEC, Avahi.LOOKUP_USE_MULTICAST)
                self._services[service] = {
                    'resolver': self._sysbus.get_proxy(Avahi.DBUS_NAME, obj_path),
                    'data': {},
                }
            except dasbus.error.DBusError as ex:
                self._logger.warning('Failed to create resolver: "%s", "%s", "%s". %s', interface, name, stype, ex)

    def _service_removed(self, _connection, _sender_name:str, _object_path:str, _interface_name:str, _signal_name:str, args:typing.Tuple[int, int, str, str, str, int], *_user_data):
        (interface, protocol, name, stype, domain, flags) = args
        self._logger.debug('Avahi._service_removed()           - interface=%s (%s), protocol=%s, stype=%s, domain=%s, flags=%s %-14s name=%s',
                           interface, socket.if_indextoname(interface), Avahi.protocol_as_string(protocol), stype, domain, flags, '(' + Avahi.result_flags_as_string(flags) + '),', name)

        service  = (interface, protocol, name, stype, domain)
        resolver = self._services.pop(service, {}).pop('resolver', None)
        if resolver is not None:
            try:
                resolver.Free()
                dasbus.client.proxy.disconnect_proxy(resolver)
            except (AttributeError, dasbus.error.DBusError) as ex:
                self._logger.debug('Avahi._service_removed()           - Failed to Free() resolver. %s', ex)

        self._change_cb()

    def _service_identified(self, _connection, _sender_name:str, _object_path:str, _interface_name:str,
                           _signal_name:str, args:typing.Tuple[int, int, str, str, str, str, int, str, int, list, int], *_user_data):
        (interface, protocol, name, stype, domain, host, aprotocol, address, port, txt, flags) = args
        txt = txt2dict(txt)
        self._logger.debug('Avahi._service_identified()        - interface=%s (%s), protocol=%s, stype=%s, domain=%s, flags=%s %-14s name=%s, host=%s, aprotocol=%s, address=%s, port=%s, txt=%s',
                           interface, socket.if_indextoname(interface), Avahi.protocol_as_string(protocol), stype, domain, flags, '(' + Avahi.result_flags_as_string(flags) + '),',
                           name, host, Avahi.protocol_as_string(aprotocol), address, port, txt)

        service = (interface, protocol, name, stype, domain)
        if service in self._services:
            self._services[service]['data'] = {
                'transport':  txt.get('p', 'tcp'),
                'traddr':     address,
                'trsvcid':    str(port),
                'host-iface': socket.if_indextoname(interface),
                'subsysnqn':  txt.get('NQN', 'nqn.2014-08.org.nvmexpress.discovery') if stas.get_nvme_options().discovery_supp else 'nqn.2014-08.org.nvmexpress.discovery',
            }
        self._change_cb()

    def _failure_handler(self, _connection, _sender_name:str, _object_path:str, interface_name:str,
                         _signal_name:str, args:typing.Tuple[str], *_user_data):
        (error,) = args
        if 'ServiceResolver' not in interface_name or 'TimeoutError' not in error: # ServiceResolver may fire a timeout event after being Free'd(). This seems to be normal.
            self._logger.error('Avahi._failure_handler()    - name=%s, error=%s', interface_name, error)
