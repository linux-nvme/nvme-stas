#!/usr/bin/python3
import logging
import unittest
from staslib import avahi
import dasbus.connection
import subprocess

class Test(unittest.TestCase):
    '''Unit tests for class Avahi'''

    def test_new(self):
        sysbus = dasbus.connection.SystemMessageBus()
        srv = avahi.Avahi(sysbus, lambda:"ok")
        self.assertEqual(srv.info(), {'avahi wake up timer': '60.0s [off]', 'service types': [], 'services': {}})
        self.assertEqual(srv.get_controllers(), [])

        try:
            # Check that the Avahi daemon is running
            subprocess.run(['systemctl', 'is-active', 'avahi-daemon.service'], check=True)
            self.assertFalse(srv._on_kick_avahi())
        except subprocess.CalledProcessError:
            self.assertTrue(srv._on_kick_avahi())

        with self.assertLogs(logger=logging.getLogger(), level='INFO') as captured:
            srv._avahi_available(None)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].getMessage(), "avahi-daemon service available, zeroconf supported.")
        with self.assertLogs(logger=logging.getLogger(), level='WARN') as captured:
            srv._avahi_unavailable(None)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].getMessage(), "avahi-daemon not available, zeroconf not supported.")
        srv.kill()
        self.assertEqual(srv.info(), {'avahi wake up timer': 'None', 'service types': [], 'services': {}})

if __name__ == '__main__':
    unittest.main()
