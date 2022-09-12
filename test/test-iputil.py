#!/usr/bin/python3
import os
import json
import logging
import unittest
import subprocess
from staslib import iputil, log


class Test(unittest.TestCase):
    '''iputil.py unit tests'''

    def setUp(self):
        log.init(syslog=False)
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)

        # Retrieve the list of Interfaces and all the associated IP addresses
        # using standard bash utility (ip address). We'll use this to make sure
        # iputil.get_interface() returns the same data as "ip address".
        try:
            cmd = ['ip', '-j', 'address', 'show']
            p = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
            self.ifaces = json.loads(p.stdout.decode().strip())
        except subprocess.CalledProcessError:
            self.ifaces = []

    def test_iputil(self):
        '''Check coner cases'''
        for iface in self.ifaces:
            for addr_entry in iface['addr_info']:
                self.assertEqual(iface['ifname'], iputil.get_interface(addr_entry['local']))

        self.assertEqual('', iputil.get_interface('255.255.255.255'))


if __name__ == "__main__":
    unittest.main()
