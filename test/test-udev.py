#!/usr/bin/python3
import json
import shutil
import logging
import unittest
import ipaddress
import subprocess
from staslib import defs, iputil, log, trid, udev

IP = shutil.which('ip')

TRADDR4 = '1.2.3.4'
TRADDR4_REV = '4.3.2.1'
TRADDR6 = 'FE80::aaaa:BBBB:cccc:dddd'
TRADDR6_REV = 'fe80::DDDD:cccc:bbbb:AAAA'


def traddr(family, reverse=False):
    if reverse:
        return TRADDR4_REV if family == 4 else TRADDR6_REV
    return TRADDR4 if family == 4 else TRADDR6


def get_tids_to_test(family, src_ip, ifname):
    return [
        (
            1,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ip,
                    'host-iface': ifname,
                }
            ),
            True,
        ),
        (
            2,
            trid.TID(
                {
                    'transport': 'blah',
                    'traddr': traddr(family),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ip,
                    'host-iface': ifname,
                }
            ),
            False,
        ),
        (
            3,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family, reverse=True),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ip,
                    'host-iface': ifname,
                }
            ),
            False,
        ),
        (
            4,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family),
                    'trsvcid': '8010',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ip,
                    'host-iface': ifname,
                }
            ),
            False,
        ),
        (
            5,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': '255.255.255.255',
                    'host-iface': ifname,
                }
            ),
            False,
        ),
        (
            6,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ip,
                    'host-iface': 'blah',
                }
            ),
            False,
        ),
        (
            7,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family),
                    'trsvcid': '8009',
                    'subsysnqn': 'bob',
                    'host-traddr': src_ip,
                    'host-iface': ifname,
                }
            ),
            False,
        ),
        (
            8,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-iface': ifname,
                }
            ),
            True,
        ),
        (
            9,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ip,
                }
            ),
            True,
        ),
        (
            10,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                }
            ),
            True,
        ),
        (
            11,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ip,
                    'host-iface': ifname,
                }
            ),
            True,
        ),
        (
            12,
            trid.TID(
                {
                    'transport': 'tcp',
                    'traddr': traddr(family),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-iface': ifname,
                }
            ),
            True,
        ),
    ]


class DummyDevice:
    ...


class Test(unittest.TestCase):
    '''Unit tests for class Udev'''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def setUp(self):
        log.init(syslog=False)
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)

        # Retrieve the list of Interfaces and all the associated IP addresses
        # using standard bash utility (ip address).
        try:
            cmd = [IP, '-j', 'address', 'show']
            p = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
            ifaces = json.loads(p.stdout.decode().strip())
        except subprocess.CalledProcessError:
            ifaces = []

        self.ifaces = {}
        for iface in ifaces:
            addr_info = iface.get('addr_info')
            if addr_info:
                ifname = iface['ifname']
                self.ifaces[ifname] = {}
                for info in addr_info:
                    family = 4 if info['family'] == 'inet' else 6
                    self.ifaces[ifname].setdefault(family, []).append(info['local'])

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

    def test__cid_matches_tid(self):
        for ifname, addrs in self.ifaces.items():
            ##############################################
            # IPV4

            ipv4_addrs = addrs.get(4, [])
            for src_ipv4 in ipv4_addrs:
                cid = {
                    'transport': 'tcp',
                    'traddr': traddr(4),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ipv4,
                    'host-iface': ifname,
                    'src-addr': src_ipv4,
                }
                cid_legacy = {
                    'transport': 'tcp',
                    'traddr': traddr(4),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ipv4,
                    'host-iface': ifname,
                    'src-addr': '',  # Legacy
                }
                for case_id, tid, match in get_tids_to_test(4, src_ipv4, ifname):
                    self.assertEqual(match, udev.UDEV._cid_matches_tid(tid, cid), msg=f'Test Case {case_id} failed')
                    if case_id != 8:
                        self.assertEqual(
                            match, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case {case_id} failed'
                        )

                cid_legacy = {
                    'transport': 'tcp',
                    'traddr': traddr(4),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': '',
                    'host-iface': '',
                    'src-addr': '',  # Legacy
                }
                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(4),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-traddr': '1.1.1.1',
                    }
                )
                self.assertEqual(True, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case A4.1 failed')

                cid_legacy = {
                    'transport': 'tcp',
                    'traddr': traddr(4),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': '',
                    'host-iface': ifname,
                    'src-addr': '',  # Legacy
                }
                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(4),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                    }
                )
                self.assertEqual(True, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case A4.2 failed')
                self.assertEqual(
                    True, udev.UDEV._cid_matches_tcp_tid_legacy(tid, cid_legacy), msg=f'Legacy Test Case A4.3 failed'
                )

                cid_legacy = {
                    'transport': 'tcp',
                    'traddr': traddr(4),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ipv4,
                    'host-iface': '',
                    'src-addr': '',  # Legacy
                }
                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(4),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-traddr': '1.1.1.1',
                    }
                )
                self.assertEqual(False, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case B4 failed')

                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(4),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-iface': 'blah',
                    }
                )
                self.assertEqual(False, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case C4 failed')

                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(4),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-iface': ifname,
                    }
                )
                self.assertEqual(True, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case D4 failed')

                cid_legacy = {
                    'transport': 'tcp',
                    'traddr': traddr(4),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': '',
                    'host-iface': ifname,
                    'src-addr': '',  # Legacy
                }
                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(4),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-traddr': '1.1.1.1',
                        'host-iface': 'blah',
                    }
                )
                self.assertEqual(False, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case E4 failed')

                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(4),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-traddr': '1.1.1.1',
                    }
                )
                self.assertEqual(False, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case F4 failed')

                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(4),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-traddr': ipv4_addrs[0],
                    }
                )
                match = len(ipv4_addrs) == 1 and iputil.get_ipaddress_obj(
                    ipv4_addrs[0], ipv4_mapped_convert=True
                ) == iputil.get_ipaddress_obj(tid.host_traddr, ipv4_mapped_convert=True)
                self.assertEqual(match, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case G4 failed')

            ##############################################
            # IPV6

            ipv6_addrs = addrs.get(6, [])
            for src_ipv6 in ipv6_addrs:
                cid = {
                    'transport': 'tcp',
                    'traddr': traddr(6),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ipv6,
                    'host-iface': ifname,
                    'src-addr': src_ipv6,
                }
                cid_legacy = {
                    'transport': 'tcp',
                    'traddr': traddr(6),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ipv6,
                    'host-iface': ifname,
                    'src-addr': '',  # Legacy
                }
                for case_id, tid, match in get_tids_to_test(6, src_ipv6, ifname):
                    self.assertEqual(match, udev.UDEV._cid_matches_tid(tid, cid), msg=f'Test Case {case_id} failed')
                    self.assertEqual(
                        match, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case {case_id} failed'
                    )

                cid_legacy = {
                    'transport': 'tcp',
                    'traddr': traddr(6),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': '',
                    'host-iface': '',
                    'src-addr': '',  # Legacy
                }
                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(6),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-traddr': 'AAAA::FFFF',
                    }
                )
                self.assertEqual(True, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case A6.1 failed')

                cid_legacy = {
                    'transport': 'tcp',
                    'traddr': traddr(6),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': '',
                    'host-iface': ifname,
                    'src-addr': '',  # Legacy
                }
                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(6),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                    }
                )
                self.assertEqual(True, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case A6.2 failed')
                self.assertEqual(
                    True, udev.UDEV._cid_matches_tcp_tid_legacy(tid, cid_legacy), msg=f'Legacy Test Case A6.3 failed'
                )

                cid_legacy = {
                    'transport': 'tcp',
                    'traddr': traddr(6),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': src_ipv6,
                    'host-iface': '',
                    'src-addr': '',  # Legacy
                }
                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(6),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-traddr': 'AAAA::FFFF',
                    }
                )
                self.assertEqual(False, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case B6 failed')

                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(6),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-iface': 'blah',
                    }
                )
                self.assertEqual(False, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case C6 failed')

                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(6),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-iface': ifname,
                    }
                )
                self.assertEqual(True, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case D6 failed')

                cid_legacy = {
                    'transport': 'tcp',
                    'traddr': traddr(6),
                    'trsvcid': '8009',
                    'subsysnqn': 'hello',
                    'host-traddr': '',
                    'host-iface': ifname,
                    'src-addr': '',  # Legacy
                }
                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(6),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-traddr': 'AAA::BBBB',
                        'host-iface': 'blah',
                    }
                )
                self.assertEqual(False, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case E6 failed')

                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(6),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-traddr': 'AAA::BBB',
                    }
                )
                self.assertEqual(False, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case F6 failed')

                tid = trid.TID(
                    {
                        'transport': 'tcp',
                        'traddr': traddr(6),
                        'trsvcid': '8009',
                        'subsysnqn': 'hello',
                        'host-traddr': ipv6_addrs[0],
                    }
                )
                match = len(ipv6_addrs) == 1 and iputil.get_ipaddress_obj(
                    ipv6_addrs[0], ipv4_mapped_convert=True
                ) == iputil.get_ipaddress_obj(tid.host_traddr, ipv4_mapped_convert=True)
                self.assertEqual(match, udev.UDEV._cid_matches_tid(tid, cid_legacy), msg=f'Legacy Test Case G6 failed')

            ##############################################
            # FC
            cid = {
                'transport': 'fc',
                'traddr': 'ABC',
                'trsvcid': '',
                'subsysnqn': 'hello',
                'host-traddr': 'AAA::BBBB',
                'host-iface': '',
                'src-addr': '',
            }
            tid = trid.TID(
                {
                    'transport': 'fc',
                    'traddr': 'ABC',
                    'trsvcid': '',
                    'subsysnqn': 'hello',
                    'host-traddr': 'AAA::BBBB',
                }
            )
            self.assertEqual(True, udev.UDEV._cid_matches_tid(tid, cid), msg=f'Test Case FC-1 failed')

            tid = trid.TID(
                {
                    'transport': 'fc',
                    'traddr': 'ABC',
                    'trsvcid': '',
                    'subsysnqn': 'hello',
                    'host-traddr': 'BBBB::AAA',
                }
            )
            self.assertEqual(False, udev.UDEV._cid_matches_tid(tid, cid), msg=f'Test Case FC-2 failed')

            ##############################################
            # RDMA
            cid = {
                'transport': 'rdma',
                'traddr': '2.3.4.5',
                'trsvcid': '4444',
                'subsysnqn': 'hello',
                'host-traddr': '5.4.3.2',
                'host-iface': '',
                'src-addr': '',
            }
            tid = trid.TID(
                {
                    'transport': 'rdma',
                    'traddr': '2.3.4.5',
                    'trsvcid': '4444',
                    'subsysnqn': 'hello',
                    'host-traddr': '5.4.3.2',
                }
            )
            self.assertEqual(True, udev.UDEV._cid_matches_tid(tid, cid), msg=f'Test Case RDMA-1 failed')

            tid = trid.TID(
                {
                    'transport': 'rdma',
                    'traddr': '2.3.4.5',
                    'trsvcid': '4444',
                    'subsysnqn': 'hello',
                    'host-traddr': '5.5.6.6',
                }
            )
            self.assertEqual(False, udev.UDEV._cid_matches_tid(tid, cid), msg=f'Test Case RDMA-2 failed')

            tid = trid.TID(
                {
                    'transport': 'rdma',
                    'traddr': '2.3.4.5',
                    'trsvcid': '4444',
                    'subsysnqn': 'hello',
                }
            )
            self.assertEqual(True, udev.UDEV._cid_matches_tid(tid, cid), msg=f'Test Case RDMA-3 failed')


if __name__ == '__main__':
    unittest.main()
