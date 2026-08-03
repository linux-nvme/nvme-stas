#!/usr/bin/python3
import os
import tempfile
import unittest
from staslib import nbft

TEST_DIR = os.path.dirname(__file__)
NBFT_FILE = os.path.join(TEST_DIR, "NBFT")
EMPTY_NBFT_FILE = os.path.join(TEST_DIR, "NBFT-Empty")
NBFT_DATA = {
    "discovery": [
        {
            "hfi_index": 0,
            "nqn": "nqn.2014-08.org.nvmexpress.discovery",
            "uri": "nvme+tcp://100.71.103.50:8009/",
        }
    ],
    "hfi": [
        {
            "dhcp_duid": b"",
            "dhcp_duid_len": 0,
            "dhcp_iaid": 0,
            "dhcp_server_ipaddr": "100.71.245.254",
            "flags": 7,
            "gateway_ipaddr": "100.71.245.254",
            "ip_origin": 82,
            "ipaddr": "100.71.245.232",
            "mac_addr": "b0:26:28:e8:7c:0e",
            "pcidev": "0:40:0.0",
            "pcie_seg_num": 0,
            "primary_dns_ipaddr": "100.64.0.5",
            "route_metric": 500,
            "secondary_dns_ipaddr": "100.64.0.6",
            "subnet_mask_prefix": 24,
            "trtype": "tcp",
            "vlan": 0,
        }
    ],
    "host": {
        "flags": 7,
        "id": "44454c4c-3400-1036-8038-b2c04f313233",
        "nqn": "nqn.1988-11.com.dell:PowerEdge.R760.1234567",
    },
    "subsystem": [
        {
            "asqsz": 0,
            "cipeec": 0,
            "controller_id": 5,
            "cto": 0,
            "flags": 81,
            "hfi_indexes": [0],
            "naed": 0,
            "nceec": 0,
            "nid": "c82404ed9c15f53b8ccf0968002e0fca",
            "nid_type": "nguid",
            "nsid": 148,
            "subsys_nqn": "nqn.1988-11.com.dell:powerstore:00:2a64abf1c5b81F6C4549",
            "subsys_port_id": 0,
            "traddr": "100.71.103.48",
            "trflags": 0,
            "trsvcid": "4420",
            "trtype": "tcp",
        },
        {
            "asqsz": 0,
            "cipeec": 0,
            "controller_id": 4166,
            "cto": 0,
            "flags": 81,
            "hfi_indexes": [0],
            "naed": 0,
            "nceec": 0,
            "nid": "c82404ed9c15f53b8ccf0968002e0fca",
            "nid_type": "nguid",
            "nsid": 148,
            "subsys_nqn": "nqn.1988-11.com.dell:powerstore:00:2a64abf1c5b81F6C4549",
            "subsys_port_id": 0,
            "traddr": "100.71.103.49",
            "trflags": 0,
            "trsvcid": "4420",
            "trtype": "tcp",
        },
    ],
}


class Test(unittest.TestCase):
    """Unit tests for NBFT"""

    def setUp(self):
        self.expected_nbft = {
            NBFT_FILE: NBFT_DATA,
            EMPTY_NBFT_FILE: {},
        }

    def test_dir_with_nbft_files(self):
        """Make sure we get expected data when reading from binary NBFT file"""
        actual_nbft = nbft.get_nbft_files(TEST_DIR)
        self.assertEqual(actual_nbft, self.expected_nbft)

    def test_dir_without_nbft_files(self):
        actual_nbft = nbft.get_nbft_files("/tmp")
        self.assertEqual(actual_nbft, {})

    def test_corrupt_nbft_file(self):
        """Make sure a corrupt/garbage NBFT binary does not crash and returns {}"""
        with tempfile.TemporaryDirectory() as tmpdir:
            corrupt_file = os.path.join(tmpdir, 'NBFT')
            with open(corrupt_file, 'wb') as f:
                f.write(b'\xca\xfe\xba\xbe' * 64)  # 256 bytes of garbage
            result = nbft.get_nbft_files(tmpdir)
            self.assertEqual(result, {corrupt_file: {}})


if __name__ == "__main__":
    unittest.main()
