#!/usr/bin/python3
import os
import logging
import unittest
import unittest.mock
from staslib import conf

TEST_DIR = os.path.dirname(__file__)
EXPECTED_DCS = [
    {
        'subsysnqn': 'nqn.2014-08.org.nvmexpress.discovery',
        'traddr': '100.71.103.50',
        'transport': 'tcp',
        'trsvcid': '8009',
        'hostnqn': 'nqn.1988-11.com.dell:PowerEdge.R760.1234567',
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
        'hostnqn': 'nqn.1988-11.com.dell:PowerEdge.R760.1234567',
    },
    {
        'data-digest': False,
        'hdr-digest': False,
        'subsysnqn': 'nqn.1988-11.com.dell:powerstore:00:2a64abf1c5b81F6C4549',
        'traddr': '100.71.103.49',
        'transport': 'tcp',
        'trsvcid': '4420',
        'hostnqn': 'nqn.1988-11.com.dell:PowerEdge.R760.1234567',
    },
]


class Test(unittest.TestCase):
    """Unit tests for class NbftConf"""

    def test_dir_with_nbft_files(self):
        conf.NbftConf.destroy()  # Make sure singleton does not exist
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG') as captured:
            nbft_conf = conf.NbftConf(TEST_DIR)
            self.assertNotEqual(-1, captured.records[0].getMessage().find("NBFT location(s):"))
            self.assertEqual(nbft_conf.dcs, EXPECTED_DCS)
            self.assertEqual(nbft_conf.iocs, EXPECTED_IOCS)

    def test_host_iface_from_hfi(self):
        '''An HFI index resolves to the interface with that MAC address. An
        index past the table, or an HFI without a MAC, resolves to nothing.'''
        hfis = [{'mac_addr': '00:11:22:33:44:55'}, {}]
        data = {
            'hfi': hfis,
            'discovery': [
                {'uri': 'nvme+tcp://10.0.0.1:8009/', 'nqn': 'nqn.2014-08.org.nvmexpress.discovery', 'hfi_index': 0},
                {'uri': 'nvme+tcp://10.0.0.2:8009/', 'nqn': 'nqn.2014-08.org.nvmexpress.discovery', 'hfi_index': 5},
            ],
            'subsystem': [
                {'trtype': 'tcp', 'traddr': '10.0.0.3', 'trsvcid': '4420', 'subsys_nqn': 'nqn.a', 'hfi_indexes': [0]},
                {'trtype': 'tcp', 'traddr': '10.0.0.4', 'trsvcid': '4420', 'subsys_nqn': 'nqn.b', 'hfi_indexes': [1]},
            ],
        }
        conf.NbftConf.destroy()  # Make sure singleton does not exist
        self.addCleanup(conf.NbftConf.destroy)
        with unittest.mock.patch.object(conf.nbft, 'get_nbft_files', return_value={'/fake/NBFT': data}):
            with unittest.mock.patch.object(conf.iputil, 'mac2iface', return_value='eth7') as mac2iface:
                nbft_conf = conf.NbftConf('/fake')
        mac2iface.assert_called_with('00:11:22:33:44:55')
        self.assertEqual([dc.get('host-iface') for dc in nbft_conf.dcs], ['eth7', None])
        self.assertEqual([ioc.get('host-iface') for ioc in nbft_conf.iocs], ['eth7', None])

    def test_dir_without_nbft_files(self):
        if hasattr(self, 'assertNoLogs'):  # assertNoLogs only in Python 3.10 or later
            conf.NbftConf.destroy()  # Make sure singleton does not exist
            with self.assertNoLogs(logger=logging.getLogger(), level='DEBUG'):
                nbft_conf = conf.NbftConf('/tmp')
                self.assertEqual(nbft_conf.dcs, [])
                self.assertEqual(nbft_conf.iocs, [])


if __name__ == "__main__":
    unittest.main()
