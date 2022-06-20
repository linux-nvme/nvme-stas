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
import pyudev
from staslib import defs, log, trid

try:
    from pyudev.glib import MonitorObserver
except (ModuleNotFoundError, AttributeError):
    from staslib.glibudev import MonitorObserver  # pylint: disable=relative-beyond-top-level,ungrouped-imports

# ******************************************************************************
class Udev:
    '''@brief Udev event monitor. Provide a way to register for udev events.'''

    __instance = None
    __initialized = False

    def __init__(self):
        if self.__initialized:  # Singleton - only init once
            return
        self.__initialized = True

        self._device_event_registry = dict()
        self._action_event_registry = dict()
        self._context = pyudev.Context()
        self._monitor = pyudev.Monitor.from_netlink(self._context)
        self._monitor.filter_by(subsystem='nvme')
        self._observer = MonitorObserver(self._monitor)
        self._sig_id = self._observer.connect('device-event', self._device_event)
        self._monitor.start()

    def __new__(cls):
        '''This is used to make this class a singleton'''
        if cls.__instance is None:
            cls.__instance = super(Udev, cls).__new__(cls)

        return cls.__instance

    def release_resources(self):
        '''Rlease all resources used by this object'''
        if self._observer and self._sig_id is not None:
            self._observer.disconnect(self._sig_id)

        if self._monitor is not None:
            self._monitor.remove_filter()

        self._sig_id = None
        self._monitor = None
        self._context = None
        self._observer = None
        self._device_event_registry = None
        self._action_event_registry = None

    @classmethod
    def destroy(cls):
        '''This is used to destroy this singleton class'''
        if cls.__instance is not None:
            cls.__instance.release_resources()

        cls.__instance = None
        cls.__initialized = False

    def get_nvme_device(self, sys_name):
        '''@brief Get the udev device object associated with an nvme device.
        @param sys_name: The device system name (e.g. 'nvme1')
        @return A pyudev.device._device.Device object
        '''
        device_node = os.path.join('/dev', sys_name)
        try:
            return pyudev.Devices.from_device_file(self._context, device_node)
        except pyudev.DeviceNotFoundByFileError as ex:
            log.LOG.error("Udev.get_nvme_device() - Error: %s", ex)
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

        subsysnqn = device.attributes.get('subsysnqn')
        if subsysnqn is not None and subsysnqn.decode() != defs.WELL_KNOWN_DISC_NQN:
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
        return trid.TID(cid)


def clean():
    '''Clean up all resources (especially singletons)'''
    Udev.destroy()
