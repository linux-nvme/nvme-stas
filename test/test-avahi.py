#!/usr/bin/python3
import os
import unittest
from staslib import avahi
import dasbus.connection

class Test(unittest.TestCase):
    '''Unit tests for class Avahi'''

    def test_new(self):
        sysbus = dasbus.connection.SystemMessageBus()
        srv = avahi.Avahi(sysbus, lambda:"ok")
        self.assertEqual(srv.info(), {'avahi wake up timer': '60.0s [off]', 'service types': [], 'services': {}})
        self.assertEqual(srv.get_controllers(), [])

if __name__ == '__main__':
    unittest.main()
