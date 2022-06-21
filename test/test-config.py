#!/usr/bin/python3
import os
import unittest
from staslib import conf


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
        cnf = conf.Configuration()
        cnf.conf_file = StasProcessConfUnitTest.FNAME
        self.assertEqual(cnf.conf_file, StasProcessConfUnitTest.FNAME)
        self.assertTrue(cnf.tron)
        self.assertFalse(cnf.hdr_digest)
        self.assertFalse(cnf.data_digest)
        self.assertTrue(cnf.persistent_connections)
        self.assertTrue(cnf.udev_rule_enabled)
        self.assertFalse(cnf.sticky_connections)
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

    FNAME_1 = '/tmp/stas-sys-config-test-1'
    FNAME_2 = '/tmp/stas-sys-config-test-2'
    FNAME_3 = '/tmp/stas-sys-config-test-3'
    FNAME_4 = '/tmp/stas-sys-config-test-4'
    NQN = 'nqn.2014-08.org.nvmexpress:uuid:9aae2691-b275-4b64-8bfe-5da429a2bab9'
    ID = '56529e15-0f3e-4ede-87e2-63932a4adb99'
    SYMNAME = 'Bart-Simpson'

    DATA = {
        FNAME_1: [
            '[Host]\n',
            f'nqn={NQN}\n',
            f'id={ID}\n',
            f'symname={SYMNAME}\n',
        ],
        FNAME_2: [
            '[Host]\n',
            f'nqn=file:///dev/null\n',
        ],
        FNAME_3: [
            '[Host]\n',
            f'nqn=qnq.2014-08.org.nvmexpress:uuid:9aae2691-b275-4b64-8bfe-5da429a2bab9\n',
            f'id={ID}\n',
        ],
        FNAME_4: [
            '[Host]\n',
            f'nqn=file:///some/non/exisiting/file/!@#\n',
            f'id=file:///some/non/exisiting/file/!@#\n',
            f'symname=file:///some/non/exisiting/file/!@#\n',
        ],
    }

    @classmethod
    def setUpClass(cls):
        '''Create a temporary configuration file'''
        for file, conf in StasSysConfUnitTest.DATA.items():
            with open(file, 'w') as f:  #  # pylint: disable=unspecified-encoding
                f.writelines(conf)

    @classmethod
    def tearDownClass(cls):
        '''Delete the temporary configuration file'''
        for file in StasSysConfUnitTest.DATA.keys():
            if os.path.exists(file):
                os.remove(file)

    def test_config_1(self):
        '''Check we can read the temporary configuration file'''
        cnf = conf.SysConfiguration()
        cnf.conf_file = StasSysConfUnitTest.FNAME_1
        self.assertEqual(cnf.conf_file, StasSysConfUnitTest.FNAME_1)
        self.assertEqual(cnf.hostnqn, StasSysConfUnitTest.NQN)
        self.assertEqual(cnf.hostid, StasSysConfUnitTest.ID)
        self.assertEqual(cnf.hostsymname, StasSysConfUnitTest.SYMNAME)
        self.assertEqual(
            cnf.as_dict(),
            {
                'hostnqn': StasSysConfUnitTest.NQN,
                'hostid': StasSysConfUnitTest.ID,
                'symname': StasSysConfUnitTest.SYMNAME,
            },
        )

    def test_config_2(self):
        '''Check we can read from /dev/null or missing 'id' definition'''
        cnf = conf.SysConfiguration()
        cnf.conf_file = StasSysConfUnitTest.FNAME_2
        self.assertEqual(cnf.conf_file, StasSysConfUnitTest.FNAME_2)
        self.assertIsNone(cnf.hostnqn)
        self.assertIsNone(cnf.hostsymname)

    def test_config_3(self):
        '''Check we can read an invalid NQN string'''
        cnf = conf.SysConfiguration()
        cnf.conf_file = StasSysConfUnitTest.FNAME_3
        self.assertEqual(cnf.conf_file, StasSysConfUnitTest.FNAME_3)
        self.assertRaises(SystemExit, lambda: cnf.hostnqn)
        self.assertEqual(cnf.hostid, StasSysConfUnitTest.ID)
        self.assertIsNone(cnf.hostsymname)

    def test_config_4(self):
        '''Check we can read the temporary configuration file'''
        cnf = conf.SysConfiguration()
        cnf.conf_file = StasSysConfUnitTest.FNAME_4
        self.assertEqual(cnf.conf_file, StasSysConfUnitTest.FNAME_4)
        self.assertRaises(SystemExit, lambda: cnf.hostnqn)
        self.assertRaises(SystemExit, lambda: cnf.hostid)
        self.assertIsNone(cnf.hostsymname)

    def test_config_missing_file(self):
        '''Check what happens when conf file is missing'''
        cnf = conf.SysConfiguration()
        cnf.conf_file = '/just/some/ramdom/file/name'
        self.assertIsNone(cnf.hostsymname)


if __name__ == '__main__':
    unittest.main()
