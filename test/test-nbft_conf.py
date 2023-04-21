#!/usr/bin/python3
import os
import unittest
from staslib import conf

TEST_DIR = os.path.dirname(__file__)
EXPECTED_DCS = [
    {
        'subsysnqn': 'nqn.2014-08.org.nvmexpress.discovery',
        'traddr': '100.71.103.50',
        'transport': 'tcp',
        'trsvcid': '8009',
    }
]
EXPECTED_IOCS = [
    {
        'data-digest': False,
        'hdr-digest': False,
        'subsysnqn': 'nqn.1988-11.com.dell:powerstore:00:2a64abf1c5b81F6C4549',
        'traddr': '100.71.103.48',
        'transport': 'tcp',
        'trsvcid': '4420',
    },
    {
        'data-digest': False,
        'hdr-digest': False,
        'subsysnqn': 'nqn.1988-11.com.dell:powerstore:00:2a64abf1c5b81F6C4549',
        'traddr': '100.71.103.49',
        'transport': 'tcp',
        'trsvcid': '4420',
    },
]


class Test(unittest.TestCase):
    """Unit tests for class NbftConf"""

    def test_nbft_matches(self):
        conf.NbftConf.destroy()  # Make sure singleton does not exist
        nbft_conf = conf.NbftConf(TEST_DIR)
        self.assertEqual(nbft_conf.dcs, EXPECTED_DCS)
        self.assertEqual(nbft_conf.iocs, EXPECTED_IOCS)


if __name__ == "__main__":
    unittest.main()
