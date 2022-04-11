#!/usr/bin/python3
import os
import unittest
from staslib import stas

if __name__ == '__main__':
    class StasConfigurationUnitTest(unittest.TestCase):
        ''' Unit tests
        '''
        test_fname = '/tmp/stas-test-config'

        @classmethod
        def setUpClass(cls):
            ''' Create a temporary configuration file '''
            conf = [
                '[Global]\n',
                'tron=true\n',
                'kato=200\n',
                'ip-family=ipv6\n',
                '[Controllers]\n',
                'controller=transport=tcp;traddr=100.100.100.100;host-iface=enp0s8\n',
                'blacklist=transport=tcp;traddr=10.10.10.10\n',
            ]
            with open(StasConfigurationUnitTest.test_fname, 'w') as f: #  # pylint: disable=unspecified-encoding
                f.writelines(conf)

        @classmethod
        def tearDownClass(cls):
            ''' Delete the temporary configuration file '''
            if os.path.exists(StasConfigurationUnitTest.test_fname):
                os.remove(StasConfigurationUnitTest.test_fname)

        def test_config(self):
            ''' Check we can read the temporary configuration file '''
            cnf = stas.get_configuration(StasConfigurationUnitTest.test_fname)
            self.assertTrue(cnf.tron)
            self.assertFalse(cnf.hdr_digest)
            self.assertFalse(cnf.data_digest)
            self.assertTrue(cnf.persistent_connections)
            self.assertFalse(cnf.ignore_iface)
            self.assertIn(6, cnf.ip_family)
            self.assertNotIn(4, cnf.ip_family)
            self.assertEqual(cnf.kato, 200)
            self.assertEqual(cnf.get_controllers(), [
                                 {
                                     'transport':  'tcp',
                                     'traddr':     '100.100.100.100',
                                     'host-iface': 'enp0s8'
                                 },
                             ])

            self.assertEqual(cnf.get_blacklist(), [
                                {
                                    'transport':  'tcp',
                                    'traddr':     '10.10.10.10'
                                }
                            ])

            self.assertEqual(cnf.get_stypes(), ['_nvme-disc._tcp'])

            self.assertTrue(cnf.zeroconf_enabled())

    unittest.main()

