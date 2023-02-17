#!/usr/bin/python3
import unittest
from staslib import udev


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


if __name__ == '__main__':
    unittest.main()
