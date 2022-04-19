#!/usr/bin/python3
import os
import unittest
from staslib import stas

if __name__ == '__main__':

    class StasProcessConfUnitTest(unittest.TestCase):
        '''Process config unit tests'''

        FNAME = '/tmp/stas-process-config-test'

        @classmethod
        def setUpClass(cls):
            '''Create a temporary configuration file'''
            conf = [
                '[Global]\n',
                'tron=true\n',
                'kato=200\n',
                'ip-family=ipv6\n',
                '[Controllers]\n',
                'controller=transport=tcp;traddr=100.100.100.100;host-iface=enp0s8\n',
                'blacklist=transport=tcp;traddr=10.10.10.10\n',
            ]
            with open(StasProcessConfUnitTest.FNAME, 'w') as f:  #  # pylint: disable=unspecified-encoding
                f.writelines(conf)

        @classmethod
        def tearDownClass(cls):
            '''Delete the temporary configuration file'''
            if os.path.exists(StasProcessConfUnitTest.FNAME):
                os.remove(StasProcessConfUnitTest.FNAME)

        def test_config(self):
            '''Check we can read the temporary configuration file'''
            cnf = stas.get_configuration(StasProcessConfUnitTest.FNAME)
            self.assertTrue(cnf.tron)
            self.assertFalse(cnf.hdr_digest)
            self.assertFalse(cnf.data_digest)
            self.assertTrue(cnf.persistent_connections)
            self.assertFalse(cnf.ignore_iface)
            self.assertIn(6, cnf.ip_family)
            self.assertNotIn(4, cnf.ip_family)
            self.assertEqual(cnf.kato, 200)
            self.assertEqual(
                cnf.get_controllers(),
                [
                    {'transport': 'tcp', 'traddr': '100.100.100.100', 'host-iface': 'enp0s8'},
                ],
            )

            self.assertEqual(cnf.get_blacklist(), [{'transport': 'tcp', 'traddr': '10.10.10.10'}])

            self.assertEqual(cnf.get_stypes(), ['_nvme-disc._tcp'])

            self.assertTrue(cnf.zeroconf_enabled())

    class StasSysConfUnitTest(unittest.TestCase):
        '''Sys config unit tests'''

        FNAME = '/tmp/stas-sys-config-test'
        NQN = 'nqn.2014-08.org.nvmexpress:uuid:9aae2691-b275-4b64-8bfe-5da429a2bab9'
        ID = '56529e15-0f3e-4ede-87e2-63932a4adb99'
        SYMNAME = 'Bart-Simpson'

        @classmethod
        def setUpClass(cls):
            '''Create a temporary configuration file'''
            conf = [
                '[Host]\n',
                f'nqn={StasSysConfUnitTest.NQN}\n',
                f'id={StasSysConfUnitTest.ID}\n',
                f'symname={StasSysConfUnitTest.SYMNAME}\n',
            ]
            with open(StasSysConfUnitTest.FNAME, 'w') as f:  #  # pylint: disable=unspecified-encoding
                f.writelines(conf)

        @classmethod
        def tearDownClass(cls):
            '''Delete the temporary configuration file'''
            if os.path.exists(StasSysConfUnitTest.FNAME):
                os.remove(StasSysConfUnitTest.FNAME)

        def test_config(self):
            '''Check we can read the temporary configuration file'''
            cnf = stas.SysConfiguration(StasSysConfUnitTest.FNAME)
            self.assertEqual(cnf.hostnqn, StasSysConfUnitTest.NQN)
            self.assertEqual(cnf.hostid, StasSysConfUnitTest.ID)
            self.assertEqual(cnf.hostsymname, StasSysConfUnitTest.SYMNAME)

    unittest.main()
