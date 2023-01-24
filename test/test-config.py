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
        data = [
            '[Global]\n',
            'tron=true\n',
            'kato=200\n',
            'ip-family=ipv6\n',
            '[Controllers]\n',
            'controller=transport=tcp;traddr=100.100.100.100;host-iface=enp0s8\n',
            'blacklist=transport=tcp;traddr=10.10.10.10\n',
        ]
        with open(StasProcessConfUnitTest.FNAME, 'w') as f:  #  # pylint: disable=unspecified-encoding
            f.writelines(data)

    @classmethod
    def tearDownClass(cls):
        '''Delete the temporary configuration file'''
        if os.path.exists(StasProcessConfUnitTest.FNAME):
            os.remove(StasProcessConfUnitTest.FNAME)

    def test_config(self):
        '''Check we can read the temporary configuration file'''
        service_conf = conf.SvcConf()
        service_conf.set_conf_file(StasProcessConfUnitTest.FNAME)
        self.assertEqual(service_conf.conf_file, StasProcessConfUnitTest.FNAME)
        self.assertTrue(service_conf.tron)
        self.assertFalse(service_conf.hdr_digest)
        self.assertFalse(service_conf.data_digest)
        self.assertTrue(service_conf.persistent_connections)
        self.assertTrue(service_conf.udev_rule_enabled)
        self.assertTrue(service_conf.sticky_connections)
        self.assertFalse(service_conf.ignore_iface)
        self.assertIn(6, service_conf.ip_family)
        self.assertNotIn(4, service_conf.ip_family)
        self.assertEqual(service_conf.kato, 200)
        self.assertEqual(
            service_conf.get_controllers(),
            [
                {'transport': 'tcp', 'traddr': '100.100.100.100', 'host-iface': 'enp0s8'},
            ],
        )

        self.assertEqual(service_conf.get_blacklist(), [{'transport': 'tcp', 'traddr': '10.10.10.10'}])

        stypes = service_conf.get_stypes()
        self.assertIn('_nvme-disc._tcp', stypes)

        self.assertTrue(service_conf.zeroconf_enabled())


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
            'nqn=file:///dev/null\n',
        ],
        FNAME_3: [
            '[Host]\n',
            'nqn=qnq.2014-08.org.nvmexpress:uuid:9aae2691-b275-4b64-8bfe-5da429a2bab9\n',
            f'id={ID}\n',
        ],
        FNAME_4: [
            '[Host]\n',
            'nqn=file:///some/non/exisiting/file/!@#\n',
            'id=file:///some/non/exisiting/file/!@#\n',
            'symname=file:///some/non/exisiting/file/!@#\n',
        ],
    }

    @classmethod
    def setUpClass(cls):
        '''Create a temporary configuration file'''
        for file, data in StasSysConfUnitTest.DATA.items():
            with open(file, 'w') as f:  #  # pylint: disable=unspecified-encoding
                f.writelines(data)

    @classmethod
    def tearDownClass(cls):
        '''Delete the temporary configuration file'''
        for file in StasSysConfUnitTest.DATA.keys():
            if os.path.exists(file):
                os.remove(file)

    def test_config_1(self):
        '''Check we can read the temporary configuration file'''
        system_conf = conf.SysConf()
        system_conf.set_conf_file(StasSysConfUnitTest.FNAME_1)
        self.assertEqual(system_conf.conf_file, StasSysConfUnitTest.FNAME_1)
        self.assertEqual(system_conf.hostnqn, StasSysConfUnitTest.NQN)
        self.assertEqual(system_conf.hostid, StasSysConfUnitTest.ID)
        self.assertEqual(system_conf.hostsymname, StasSysConfUnitTest.SYMNAME)
        self.assertEqual(
            system_conf.as_dict(),
            {
                'hostnqn': StasSysConfUnitTest.NQN,
                'hostid': StasSysConfUnitTest.ID,
                'symname': StasSysConfUnitTest.SYMNAME,
            },
        )

    def test_config_2(self):
        '''Check we can read from /dev/null or missing 'id' definition'''
        system_conf = conf.SysConf()
        system_conf.set_conf_file(StasSysConfUnitTest.FNAME_2)
        self.assertEqual(system_conf.conf_file, StasSysConfUnitTest.FNAME_2)
        self.assertIsNone(system_conf.hostnqn)
        self.assertIsNone(system_conf.hostsymname)

    def test_config_3(self):
        '''Check we can read an invalid NQN string'''
        system_conf = conf.SysConf()
        system_conf.set_conf_file(StasSysConfUnitTest.FNAME_3)
        self.assertEqual(system_conf.conf_file, StasSysConfUnitTest.FNAME_3)
        self.assertRaises(SystemExit, lambda: system_conf.hostnqn)
        self.assertEqual(system_conf.hostid, StasSysConfUnitTest.ID)
        self.assertIsNone(system_conf.hostsymname)

    def test_config_4(self):
        '''Check we can read the temporary configuration file'''
        system_conf = conf.SysConf()
        system_conf.set_conf_file(StasSysConfUnitTest.FNAME_4)
        self.assertEqual(system_conf.conf_file, StasSysConfUnitTest.FNAME_4)
        self.assertRaises(SystemExit, lambda: system_conf.hostnqn)
        self.assertRaises(SystemExit, lambda: system_conf.hostid)
        self.assertIsNone(system_conf.hostsymname)

    def test_config_missing_file(self):
        '''Check what happens when conf file is missing'''
        system_conf = conf.SysConf()
        system_conf.set_conf_file('/just/some/ramdom/file/name')
        self.assertIsNone(system_conf.hostsymname)


if __name__ == '__main__':
    unittest.main()
