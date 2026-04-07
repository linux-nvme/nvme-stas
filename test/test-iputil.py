#!/usr/bin/python3
import json
import shutil
import logging
import unittest
import ipaddress
import subprocess
from staslib import iputil, log, stas, trid

IP = shutil.which('ip')


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
            cmd = [IP, '-j', 'address', 'show']
            p = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
            self.ifaces = json.loads(p.stdout.decode().strip())
        except subprocess.CalledProcessError:
            self.ifaces = []

    def test_get_interface(self):
        '''Check that get_interface() returns the right info'''
        ifaces = iputil.net_if_addrs()
        for iface in self.ifaces:
            for addr_entry in iface['addr_info']:
                addr = ipaddress.ip_address(addr_entry['local'])
                # Link local addresses may appear on more than one interface and therefore cannot be used.
                if not addr.is_link_local:
                    self.assertEqual(iface['ifname'], iputil.get_interface(ifaces, addr))

        self.assertEqual('', iputil.get_interface(ifaces, iputil.get_ipaddress_obj('255.255.255.255')))
        self.assertEqual('', iputil.get_interface(ifaces, ''))
        self.assertEqual('', iputil.get_interface(ifaces, None))

    @staticmethod
    def _is_ok_for_mac2iface(iface) -> bool:
        '''mac2iface can only work with interfaces that have a proper MAC
        address. One can use this function to filter out other interfaces
        configured on the system.'''
        if iface['link_type'] != 'ether':
            # Some esoteric interface types (e.g., gre) use the address
            # field to store something that is not a MAC address. Skip
            # them.
            return False
        if 'address' not in iface:
            return False
        if iface['address'] == '00:00:00:00:00:00':
            # All 0's is an invalid MAC address so do not bother.
            # In practice, it often appears as the address of the loopback
            # interface but it can also appear for other things like a gretap
            # or erspan interface.
            return False
        return True

    def test_mac2iface(self):
        # We only test the interfaces that have a MAC address, and a valid one.
        candidate_ifaces = [iface for iface in self.ifaces if self._is_ok_for_mac2iface(iface)]

        for iface in candidate_ifaces:
            if len([x for x in candidate_ifaces if x['address'] == iface['address']]) >= 2:
                # We need to be careful, sometimes we can have the same MAC address
                # on multiple interfaces. This happens with VLAN interfaces for
                # instance. mac2iface will obviously be confused when dealing with
                # those so let's skip the interfaces that have duplicate MAC.
                logging.warning('[%s] is not the only interface with address [%s]', iface['ifname'], iface['address'])
                continue

            self.assertEqual(iface['ifname'], iputil.mac2iface(iface['address']))

    def test_remove_invalid_addresses(self):
        good_tcp = trid.TID({'transport': 'tcp', 'traddr': '1.1.1.1', 'subsysnqn': '', 'trsvcid': '8009'})
        bad_tcp = trid.TID({'transport': 'tcp', 'traddr': '555.555.555.555', 'subsysnqn': '', 'trsvcid': '8009'})
        any_fc = trid.TID({'transport': 'fc', 'traddr': 'blah', 'subsysnqn': ''})
        bad_trtype = trid.TID({'transport': 'whatever', 'traddr': 'blah', 'subsysnqn': ''})

        l1 = [
            good_tcp,
            bad_tcp,
            any_fc,
            bad_trtype,
        ]
        l2 = stas.remove_invalid_addresses(l1)

        self.assertNotEqual(l1, l2)

        self.assertIn(good_tcp, l2)
        self.assertIn(any_fc, l2)  # We currently don't check for invalid FC (all FCs are allowed)

        self.assertNotIn(bad_tcp, l2)
        self.assertNotIn(bad_trtype, l2)

    def test_ip_equal(self):
        self.assertFalse(iputil.ip_equal(None, ipaddress.IPv4Address('1.1.1.1')))
        self.assertFalse(iputil.ip_equal(ipaddress.IPv4Address('1.1.1.1'), None))
        self.assertTrue(iputil.ip_equal(ipaddress.IPv4Address('1.1.1.1'), ipaddress.IPv4Address('1.1.1.1')))
        self.assertTrue(iputil.ip_equal(ipaddress.IPv4Address('1.2.3.4'), ipaddress.IPv6Address('::ffff:102:304')))

    def test_get_ipaddress_obj(self):
        # Invalid/empty input → None regardless of flag
        self.assertIsNone(iputil.get_ipaddress_obj('', ipv4_mapped_convert=True))
        self.assertIsNone(iputil.get_ipaddress_obj('not-an-ip', ipv4_mapped_convert=True))

        # Regular IPv4 address: no ipv4_mapped attribute, returned as-is
        self.assertEqual(ipaddress.IPv4Address('1.2.3.4'), iputil.get_ipaddress_obj('1.2.3.4', ipv4_mapped_convert=True))

        # Regular IPv6 address (not IPv4-mapped): no conversion, returned as-is
        self.assertEqual(ipaddress.IPv6Address('::1'), iputil.get_ipaddress_obj('::1', ipv4_mapped_convert=True))

        # IPv4-mapped IPv6 address with convert=True → returns the IPv4 equivalent
        self.assertEqual(ipaddress.IPv4Address('1.2.3.4'), iputil.get_ipaddress_obj('::ffff:1.2.3.4', ipv4_mapped_convert=True))

        # IPv4-mapped IPv6 address with convert=False → stays as IPv6
        self.assertEqual(ipaddress.IPv6Address('::ffff:102:304'), iputil.get_ipaddress_obj('::ffff:1.2.3.4', ipv4_mapped_convert=False))

if __name__ == "__main__":
    unittest.main()
