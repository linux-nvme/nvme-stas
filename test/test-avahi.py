#!/usr/bin/python3
import os
import unittest
from staslib import stas, avahi
import dasbus.connection

class Test(unittest.TestCase):
    '''Unit tests for class Avahi'''

    def test_new(self):
        sysbus = dasbus.connection.SystemMessageBus()
        srv = avahi.Avahi(sysbus, lambda:"ok")
        self.assertEqual(srv.info(), {'avahi wake up timer': '60.0s [off]', 'service types': [], 'services': {}})
        self.assertEqual(srv.get_controllers(), [])
        self.assertEqual(srv._on_kick_avahi(), False)
        with self.assertLogs(logger=stas.LOG, level='INFO') as captured:
            srv._avahi_available(None)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].getMessage(), "avahi-daemon service available, zeroconf supported.")
        with self.assertLogs(logger=stas.LOG, level='WARN') as captured:
            srv._avahi_unavailable(None)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].getMessage(), "avahi-daemon not available, zeroconf not supported.")
        srv.kill()
        self.assertEqual(srv.info(), {'avahi wake up timer': 'None', 'service types': [], 'services': {}})

if __name__ == '__main__':
    unittest.main()
