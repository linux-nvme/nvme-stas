#!/usr/bin/python3
import os
import unittest
from staslib import defs, stas
from libnvme import nvme
from argparse import ArgumentParser

TEST_DIR = os.path.dirname(__file__)
NBFT_DATA = {
    "discovery": [
        {
            "hfi": 1,
            "index": 1,
            "nqn": "nqn.2014-08.org.nvmexpress.discovery",
            "uri": "nvme+tcp://100.71.103.50:8009/",
        }
    ],
    "hfi": [
        {
            "dhcp_override": 1,
            "dhcp_server_ipaddr": "100.71.245.254",
            "gateway_ipaddr": "100.71.245.254",
            "index": 1,
            "ip_origin": 82,
            "ipaddr": "100.71.245.232",
            "mac_addr": "b0:26:28:e8:7c:0e",
            "pcidev": "0:40:0.0",
            "primary_dns_ipaddr": "100.64.0.5",
            "route_metric": 500,
            "secondary_dns_ipaddr": "100.64.0.6",
            "subnet_mask_prefix": 24,
            "this_hfi_is_default_route": 1,
            "trtype": "tcp",
            "vlan": 0,
        }
    ],
    "host": {
        "host_id_configured": True,
        "host_nqn_configured": True,
        "id": "44454c4c-3400-1036-8038-b2c04f313233",
        "nqn": "nqn.1988-11.com.dell:PowerEdge.R760.1234567",
        "primary_admin_host_flag": "not indicated",
    },
    "subsystem": [
        {
            "asqsz": 0,
            "controller_id": 5,
            "data_digest_required": 0,
            "hfis": [1],
            "index": 1,
            "nid": "c82404ed9c15f53b8ccf0968002e0fca",
            "nid_type": "nguid",
            "nsid": 148,
            "num_hfis": 1,
            "pdu_header_digest_required": 0,
            "subsys_nqn": "nqn.1988-11.com.dell:powerstore:00:2a64abf1c5b81F6C4549",
            "subsys_port_id": 0,
            "traddr": "100.71.103.48",
            "trsvcid": "4420",
            "trtype": "tcp",
        },
        {
            "asqsz": 0,
            "controller_id": 4166,
            "data_digest_required": 0,
            "hfis": [1],
            "index": 2,
            "nid": "c82404ed9c15f53b8ccf0968002e0fca",
            "nid_type": "nguid",
            "nsid": 148,
            "num_hfis": 1,
            "pdu_header_digest_required": 0,
            "subsys_nqn": "nqn.1988-11.com.dell:powerstore:00:2a64abf1c5b81F6C4549",
            "subsys_port_id": 0,
            "traddr": "100.71.103.49",
            "trsvcid": "4420",
            "trtype": "tcp",
        },
    ],
}


class Test(unittest.TestCase):
    """Unit tests for NBFT"""

    def setUp(self):
        # Depending on the version of libnvme installed
        # we may or may not have access to NBFT support.
        nbft_get = getattr(nvme, 'nbft_get', None)
        if defs.HAS_NBFT_SUPPORT:
            nbft_file = os.path.join(TEST_DIR, "NBFT")
            self.expected_nbft = {nbft_file: NBFT_DATA}
        else:
            self.expected_nbft = {}

    def test_dir_with_nbft_files(self):
        """Make sure we get expected data when reading from binary NBFT file"""
        actual_nbft = stas.get_nbft_files(TEST_DIR)
        self.assertEqual(actual_nbft, self.expected_nbft)

    def test_dir_without_nbft_files(self):
        actual_nbft = stas.get_nbft_files('/tmp')
        self.assertEqual(actual_nbft, {})


if __name__ == "__main__":
    unittest.main()
