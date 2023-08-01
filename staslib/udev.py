# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''This module provides functions to access nvme devices using the pyudev module'''

import os
import time
import logging
import pyudev
from gi.repository import GLib
from staslib import defs, iputil, trid


# ******************************************************************************
class Udev:
    '''@brief Udev event monitor. Provide a way to register for udev events.
    WARNING: THE singleton.Singleton PATTERN CANNOT BE USED WITH THIS CLASS.
    IT INTERFERES WITH THE pyudev INTERNALS, WHICH CAUSES OBJECT CLEAN UP TO FAIL.
    '''

    def __init__(self):
        self._log_event_soak_time = 0
        self._log_event_count = 0
        self._device_event_registry = dict()
        self._action_event_registry = dict()
        self._context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(self._context)
        self._monitor.filter_by(subsystem='nvme')
        self._event_source = GLib.io_add_watch(
            self._monitor.fileno(),
            GLib.PRIORITY_HIGH,
            GLib.IO_IN,
            self._process_udev_event,
        )
        self._monitor.start()

    def release_resources(self):
        '''Release all resources used by this object'''
        if self._event_source is not None:
            GLib.source_remove(self._event_source)

        if self._monitor is not None:
            self._monitor.remove_filter()

        self._event_source = None
        self._monitor = None
        self._context = None
        self._device_event_registry = None
        self._action_event_registry = None

    def get_nvme_device(self, sys_name):
        '''@brief Get the udev device object associated with an nvme device.
        @param sys_name: The device system name (e.g. 'nvme1')
        @return A pyudev.device._device.Device object
        '''
        device_node = os.path.join('/dev', sys_name)
        try:
            return pyudev.Devices.from_device_file(self._context, device_node)
        except pyudev.DeviceNotFoundByFileError as ex:
            logging.error("Udev.get_nvme_device() - Error: %s", ex)
            return None

    def is_action_cback_registered(self, action: str, user_cback):
        '''Returns True if @user_cback is registered for @action. False otherwise.
        @param action: one of 'add', 'remove', 'change'.
        @param user_cback: A callback function with this signature: cback(udev_obj)
        '''
        return user_cback in self._action_event_registry.get(action, set())

    def register_for_action_events(self, action: str, user_cback):
        '''@brief Register a callback function to be called when udev events
        for a specific action are received.
        @param action: one of 'add', 'remove', 'change'.
        '''
        self._action_event_registry.setdefault(action, set()).add(user_cback)

    def unregister_for_action_events(self, action: str, user_cback):
        '''@brief The opposite of register_for_action_events()'''
        try:
            self._action_event_registry.get(action, set()).remove(user_cback)
        except KeyError:  # Raise if user_cback already removed
            pass

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
        if sys_name and sys_name != 'nvme?':
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
        subsysnqn = device.attributes.get('subsysnqn')
        if subsysnqn is not None and subsysnqn.decode() == defs.WELL_KNOWN_DISC_NQN:
            return True

        # Note: Prior to 5.18 linux didn't expose the cntrltype through
        # the sysfs. So, this may return None on older kernels.
        cntrltype = device.attributes.get('cntrltype')
        if cntrltype is not None and cntrltype.decode() == 'discovery':
            return True

        # Imply Discovery controller based on the absence of children.
        # Discovery Controllers have no children devices
        if len(list(device.children)) == 0:
            return True

        return False

    @staticmethod
    def is_ioc_device(device):
        '''@brief check whether device refers to an I/O Controller'''
        # Note: Prior to 5.18 linux didn't expose the cntrltype through
        # the sysfs. So, this may return None on older kernels.
        cntrltype = device.attributes.get('cntrltype')
        if cntrltype is not None and cntrltype.decode() == 'io':
            return True

        # Imply I/O controller based on the presence of children.
        # I/O Controllers have children devices
        if len(list(device.children)) != 0:
            return True

        return False

    @staticmethod
    def _cid_matches_tcp_tid_legacy(tid, cid):  # pylint: disable=too-many-return-statements,too-many-branches
        '''On kernels older than 6.1, the src_addr parameter is not available
        from the sysfs. Therefore, we need to infer a match based on other
        parameters. And there are a few cases where we're simply not sure
        whether an existing connection (cid) matches the candidate
        connection (tid).
        '''
        cid_host_iface = cid['host-iface']
        cid_host_traddr = iputil.get_ipaddress_obj(cid['host-traddr'], ipv4_mapped_convert=True)

        if not cid_host_iface:  # cid.host_iface is undefined
            if not cid_host_traddr:  # cid.host_traddr is undefined
                # When the existing cid.src_addr, cid.host_traddr, and cid.host_iface
                # are all undefined (which can only happen on kernels prior to 6.1),
                # we can't know for sure on which interface an existing connection
                # was made. In this case, we can only declare a match if both
                # tid.host_iface and tid.host_traddr are undefined as well.
                logging.debug(
                    'Udev._cid_matches_tcp_tid_legacy() - cid=%s, tid=%s - Not enough info. Assume "match" but this could be wrong.',
                    cid,
                    tid,
                )
                return True

            # cid.host_traddr is defined. If tid.host_traddr is also
            # defined, then it must match the existing cid.host_traddr.
            if tid.host_traddr:
                tid_host_traddr = iputil.get_ipaddress_obj(tid.host_traddr, ipv4_mapped_convert=True)
                if tid_host_traddr != cid_host_traddr:
                    return False

            # If tid.host_iface is defined, then the interface where
            # the connection is located must match. If tid.host_iface
            # is not defined, then we don't really care on which
            # interface the connection was made and we can skip this test.
            if tid.host_iface:
                # With the existing cid.host_traddr, we can find the
                # interface of the exisiting connection.
                connection_iface = iputil.get_interface(str(cid_host_traddr))
                if tid.host_iface != connection_iface:
                    return False

            return True

        # cid.host_iface is defined
        if not cid_host_traddr:  # cid.host_traddr is undefined
            if tid.host_iface and tid.host_iface != cid_host_iface:
                return False

            if tid.host_traddr:
                # It's impossible to tell the existing connection source
                # address. So, we can't tell if it matches tid.host_traddr.
                # However, if the existing host_iface has only one source
                # address assigned to it, we can assume that the source
                # address used for the existing connection is that address.
                if_addrs = iputil.net_if_addrs().get(cid_host_iface, {4: [], 6: []})
                tid_host_traddr = iputil.get_ipaddress_obj(tid.host_traddr, ipv4_mapped_convert=True)
                source_addrs = if_addrs[tid_host_traddr.version]
                if len(source_addrs) != 1:
                    return False

                src_addr0 = iputil.get_ipaddress_obj(source_addrs[0], ipv4_mapped_convert=True)
                if src_addr0 != tid_host_traddr:
                    return False

            return True

        # cid.host_traddr is defined
        if tid.host_iface and tid.host_iface != cid_host_iface:
            return False

        if tid.host_traddr:
            tid_host_traddr = iputil.get_ipaddress_obj(tid.host_traddr, ipv4_mapped_convert=True)
            if tid_host_traddr != cid_host_traddr:
                return False

        return True

    @staticmethod
    def _cid_matches_tid(tid, cid):  #  pylint: disable=too-many-return-statements,too-many-branches
        '''Check if existing controller's cid matches candidate controller's tid.
        @param cid: The Connection ID of an existing controller (from the sysfs).
        @param tid: The Transport ID of a candidate controller.

        We're trying to find if an existing connection (specified by cid) can
        be re-used for the candidate controller (specified by tid).

        We do not have a match if the candidate's tid.transport, tid.traddr,
        tid.trsvcid, and tid.subsysnqn are not identical to those of the cid.
        These 4 parameters are mandatory for a match.

        The tid.host_traddr and tid.host_iface depend on the transport type.
        These parameters may not apply or have a different syntax/meaning
        depending on the transport type.

        For TCP only:
            With regards to the candidate's tid.host_traddr and tid.host_iface,
            if those are defined but do not match the existing cid.host_traddr
            and cid.host_iface, we may still be able to find a match by taking
            the existing cid.src_addr into consideration since that parameter
            identifies the actual source address of the connection and therefore
            can be used to infer the interface of the connection. However, the
            cid.src_addr can only be read from the sysfs starting with kernel
            6.1.
        '''
        # 'transport', 'traddr', 'trsvcid', 'subsysnqn', and 'host-nqn' must exactly match.
        if (
            cid['transport'] != tid.transport
            or cid['trsvcid'] != tid.trsvcid
            or cid['subsysnqn'] != tid.subsysnqn
            or cid['host-nqn'] != tid.host_nqn
        ):
            return False

        if tid.transport in ('tcp', 'rdma'):
            # Need to convert to ipaddress objects to properly
            # handle all variations of IPv6 addresses.
            tid_traddr = iputil.get_ipaddress_obj(tid.traddr, ipv4_mapped_convert=True)
            cid_traddr = iputil.get_ipaddress_obj(cid['traddr'], ipv4_mapped_convert=True)
        else:
            cid_traddr = cid['traddr']
            tid_traddr = tid.traddr

        if cid_traddr != tid_traddr:
            return False

        # We need to know the type of transport to compare 'host-traddr' and
        # 'host-iface'. These parameters don't apply to all transport types
        # and may have a different meaning/syntax.
        if tid.transport == 'tcp':
            if tid.host_traddr or tid.host_iface:
                src_addr = iputil.get_ipaddress_obj(cid['src-addr'], ipv4_mapped_convert=True)
                if not src_addr:
                    # For legacy kernels (i.e. older than 6.1), the existing cid.src_addr
                    # is always undefined. We need to use advanced logic to determine
                    # whether cid and tid match.
                    return Udev._cid_matches_tcp_tid_legacy(tid, cid)

                # The existing controller's cid.src_addr is always defined for kernel
                # 6.1 and later. We can use the existing controller's cid.src_addr to
                # find the interface on which the connection was made and therefore
                # match it to the candidate's tid.host_iface. And the cid.src_addr
                # can also be used to match the candidate's tid.host_traddr.
                if tid.host_traddr:
                    tid_host_traddr = iputil.get_ipaddress_obj(tid.host_traddr, ipv4_mapped_convert=True)
                    if tid_host_traddr != src_addr:
                        return False

                # host-iface is an optional tcp-only parameter.
                if tid.host_iface and tid.host_iface != iputil.get_interface(str(src_addr)):
                    return False

        elif tid.transport == 'fc':
            # host-traddr is mandatory for FC.
            if tid.host_traddr != cid['host-traddr']:
                return False

        elif tid.transport == 'rdma':
            # host-traddr is optional for RDMA and is expressed as an IP address.
            if tid.host_traddr:
                tid_host_traddr = iputil.get_ipaddress_obj(tid.host_traddr, ipv4_mapped_convert=True)
                cid_host_traddr = iputil.get_ipaddress_obj(cid['host-traddr'], ipv4_mapped_convert=True)
                if tid_host_traddr != cid_host_traddr:
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

            cid = self.get_cid(device)
            if not self._cid_matches_tid(tid, cid):
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

            cid = self.get_cid(device)
            if not self._cid_matches_tid(tid, cid):
                continue

            return device

        return None

    def get_nvme_ioc_tids(self, transports):
        '''@brief  Find all the I/O controller nvme devices in the system.
        @return A list of pyudev.device._device.Device objects
        '''
        tids = []
        for device in self._context.list_devices(subsystem='nvme'):
            if device.properties.get('NVME_TRTYPE', '') not in transports:
                continue

            if not self.is_ioc_device(device):
                continue

            tids.append(self.get_tid(device))

        return tids

    def _process_udev_event(self, event_source, condition):  # pylint: disable=unused-argument
        if condition == GLib.IO_IN:
            event_count = 0
            while True:
                try:
                    device = self._monitor.poll(timeout=0)
                except EnvironmentError as ex:
                    device = None
                    # This event seems to happen in bursts.  So, let's suppress
                    # logging for 2 seconds to avoid filling the syslog.
                    self._log_event_count += 1
                    now = time.time()
                    if now > self._log_event_soak_time:
                        logging.debug('Udev._process_udev_event()         - %s [%s]', ex, self._log_event_count)
                        self._log_event_soak_time = now + 2
                        self._log_event_count = 0

                if device is None:
                    break

                event_count += 1
                self._device_event(device, event_count)

        return GLib.SOURCE_CONTINUE

    @staticmethod
    def __cback_names(action_cbacks, device_cback):
        names = []
        for cback in action_cbacks:
            names.append(cback.__name__ + '()')
        if device_cback:
            names.append(device_cback.__name__ + '()')
        return names

    def _device_event(self, device, event_count):
        action_cbacks = self._action_event_registry.get(device.action, set())
        device_cback = self._device_event_registry.get(device.sys_name, None)

        logging.debug(
            'Udev._device_event()               - %-8s %-6s  %-8s  %s',
            f'{device.sys_name}:',
            device.action,
            f'{event_count:2}:{device.sequence_number}',
            self.__cback_names(action_cbacks, device_cback),
        )

        for action_cback in action_cbacks:
            GLib.idle_add(action_cback, device)

        if device_cback is not None:
            GLib.idle_add(device_cback, device)

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
    def get_key_from_attr(device, attr, key, delim=','):
        '''Get attribute specified by attr, which is composed of key=value pairs.
        Then return the value associated with key.
        @param device: The Device object
        @param attr: The device's attribute to get
        @param key: The key to look for in the attribute
        @param delim: Delimiter used between key=value pairs.
        @example:
            "address" attribute contains "trtype=tcp,traddr=10.10.1.100,trsvcid=4420,host_traddr=10.10.1.50"
        '''
        attr_str = Udev._get_attribute(device, attr)
        if not attr_str:
            return ''

        if key[-1] != '=':
            key += '='
        start = attr_str.find(key)
        if start < 0:
            return ''
        start += len(key)

        end = attr_str.find(delim, start)
        if end < 0:
            return attr_str[start:]

        return attr_str[start:end]

    @staticmethod
    def get_tid(device):
        '''@brief return the Transport ID associated with a udev device'''
        cid = Udev.get_cid(device)
        if cid['transport'] == 'tcp':
            src_addr = cid['src-addr']
            if not cid['host-iface'] and src_addr:
                # We'll try to find the interface from the source address on
                # the connection. Only available if kernel exposes the source
                # address (src_addr) in the "address" attribute.
                cid['host-iface'] = iputil.get_interface(src_addr)

        return trid.TID(cid)

    @staticmethod
    def get_cid(device):
        '''@brief return the Connection ID associated with a udev device'''
        cid = {
            'transport': Udev._get_property(device, 'NVME_TRTYPE'),
            'traddr': Udev._get_property(device, 'NVME_TRADDR'),
            'trsvcid': Udev._get_property(device, 'NVME_TRSVCID'),
            'host-traddr': Udev._get_property(device, 'NVME_HOST_TRADDR'),
            'host-iface': Udev._get_property(device, 'NVME_HOST_IFACE'),
            'subsysnqn': Udev._get_attribute(device, 'subsysnqn'),
            'src-addr': Udev.get_key_from_attr(device, 'address', 'src_addr='),
            'host-nqn': Udev._get_attribute(device, 'hostnqn'),
        }
        return cid


UDEV = Udev()  # Singleton


def shutdown():
    '''Destroy the UDEV singleton'''
    global UDEV  # pylint: disable=global-statement,global-variable-not-assigned
    UDEV.release_resources()
    del UDEV
