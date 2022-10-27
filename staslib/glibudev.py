# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''This module defines a way to map pyudev events to GLib signals'''
from gi.repository import GLib, GObject


class MonitorObserver(GObject.Object):
    '''
    An observer for device events integrating into the :mod:`gi.repository.GLib`
    mainloop.

    This class is a child of :class:`gi.repository.GObject.Object`. It
    inherits :class:`~gi.repository.GObject.Object` to turn device
    events into glib signals.

    @example:
    import pyudev

    def device_event_cback(device):
        print(f'{device.sys_name}: {device.action}')

    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='blah-blah')
    observer = MonitorObserver(monitor, device_event_cback)
    monitor.start()
    '''

    __gsignals__ = {
        'device-event': (
            GObject.SIGNAL_RUN_LAST,
            GObject.TYPE_NONE,
            (GObject.TYPE_PYOBJECT,),
        ),
    }

    def __init__(self, monitor, cback):
        GObject.Object.__init__(self)
        self._monitor = monitor
        self._cback = cback

        self._event_source = GLib.io_add_watch(
            self._monitor.fileno(),
            GLib.PRIORITY_DEFAULT,
            GLib.IO_IN,
            self._process_udev_event,
        )

    def _release_resources(self):
        if self._event_source is not None:
            GLib.source_remove(self._event_source)

        self._event_source = None
        self._monitor = None
        self._cback = None

    def _process_udev_event(self, source, condition):  # pylint: disable=unused-argument
        if condition == GLib.IO_IN:
            device = self._monitor.poll(timeout=0)
            if device is not None:
                self.emit('device-event', device)
        return GLib.SOURCE_CONTINUE

    def kill(self):
        '''Terminate object and clean up'''
        self._release_resources()

    def do_device_event(self, device):
        '''Signal handler. The name of this method is
        "do_[name-of-the-signal]" with hyphens replaced by underscores.'''
        self._cback(None, device)
