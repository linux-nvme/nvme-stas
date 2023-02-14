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
    def _get_host_iface(device):
        host_iface = Udev._get_property(device, 'NVME_HOST_IFACE')
        if not host_iface:
            # We'll try to find the interface from the source address on
            # the connection. Only available if kernel exposes the source
            # address (src_addr) in the "address" attribute.
            src_addr = Udev.get_key_from_attr(device, 'address', 'src_addr=')
            host_iface = iputil.get_interface(src_addr)
        return host_iface

    @staticmethod
    def get_tid(device):
        '''@brief return the Transport ID associated with a udev device'''
        cid = {
            'transport': Udev._get_property(device, 'NVME_TRTYPE'),
            'traddr': Udev._get_property(device, 'NVME_TRADDR'),
            'trsvcid': Udev._get_property(device, 'NVME_TRSVCID'),
            'host-traddr': Udev._get_property(device, 'NVME_HOST_TRADDR'),
            'host-iface': Udev._get_host_iface(device),
            'subsysnqn': Udev._get_attribute(device, 'subsysnqn'),
        }
        return trid.TID(cid)


UDEV = Udev()  # Singleton


def shutdown():
    '''Destroy the UDEV singleton'''
    global UDEV  # pylint: disable=global-statement,global-variable-not-assigned
    UDEV.release_resources()
    del UDEV
