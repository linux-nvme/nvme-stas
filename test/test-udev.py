#!/usr/bin/python3
import os
import unittest
from staslib import udev

UDEV = udev.Udev()

class Test(unittest.TestCase):
    '''Unit tests for class Udev'''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def test_get_device(self):
        dev = UDEV.get_nvme_device('null')
        self.assertEqual(dev.device_node, '/dev/null')

    def test_get_bad_device(self):
        self.assertIsNone(UDEV.get_nvme_device('bozo'))


if __name__ == '__main__':
    unittest.main()
