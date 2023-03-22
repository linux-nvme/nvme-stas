#!/usr/bin/python3
import unittest
from staslib import defs, udev


class DummyDevice:
    ...


class Test(unittest.TestCase):
    '''Unit tests for class Udev'''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def tearDownClass(cls):
        '''Release resources'''
        udev.shutdown()

    def test_get_device(self):
        dev = udev.UDEV.get_nvme_device('null')
        self.assertEqual(dev.device_node, '/dev/null')

    def test_get_bad_device(self):
        self.assertIsNone(udev.UDEV.get_nvme_device('bozo'))

    def test_get_key_from_attr(self):
        device = udev.UDEV.get_nvme_device('null')

        devname = udev.UDEV.get_key_from_attr(device, 'uevent', 'DEVNAME=', '\n')
        self.assertEqual(devname, 'null')

        devname = udev.UDEV.get_key_from_attr(device, 'uevent', 'DEVNAME', '\n')
        self.assertEqual(devname, 'null')

        devmode = udev.UDEV.get_key_from_attr(device, 'uevent', 'DEVMODE', '\n')
        self.assertEqual(devmode, '0666')

        bogus = udev.UDEV.get_key_from_attr(device, 'bogus', 'BOGUS', '\n')
        self.assertEqual(bogus, '')

    def test_is_dc_device(self):
        device = DummyDevice()
        device.children = ['vera', 'Chuck', 'Dave']
        device.attributes = {}

        self.assertFalse(udev.UDEV.is_dc_device(device))

        device.attributes = {'subsysnqn': defs.WELL_KNOWN_DISC_NQN.encode('utf-8')}
        self.assertTrue(udev.UDEV.is_dc_device(device))

        device.attributes = {'cntrltype': 'discovery'.encode('utf-8')}
        self.assertTrue(udev.UDEV.is_dc_device(device))

        device.attributes = {}
        device.children = []
        self.assertTrue(udev.UDEV.is_dc_device(device))

    def test_is_ioc_device(self):
        device = DummyDevice()
        device.children = []
        device.attributes = {}

        self.assertFalse(udev.UDEV.is_ioc_device(device))

        device.attributes = {'cntrltype': 'io'.encode('utf-8')}
        self.assertTrue(udev.UDEV.is_ioc_device(device))

        device.attributes = {}
        device.children = ['vera', 'Chuck', 'Dave']
        self.assertTrue(udev.UDEV.is_ioc_device(device))


if __name__ == '__main__':
    unittest.main()
