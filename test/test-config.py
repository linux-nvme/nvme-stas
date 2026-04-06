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
            '\n',
            '[I/O controller connection management]\n',
            'disconnect-scope = joe\n',
            'disconnect-trtypes = bob\n',
            'connect-attempts-on-ncc = 1\n',
            '\n',
            '[Controllers]\n',
            'controller=transport=tcp;traddr=100.100.100.100;host-iface=enp0s8\n',
            'controller=transport=tcp;traddr=100.100.100.200;host-iface=enp0s7;dhchap-ctrl-secret=super-secret;hdr-digest=true;data-digest=true;nr-io-queues=8;nr-write-queues=6;nr-poll-queues=4;queue-size=400;kato=71;reconnect-delay=13;ctrl-loss-tmo=666;disable-sqflow=true\n',
            'exclude=transport=tcp;traddr=10.10.10.10\n',
        ]
        with open(StasProcessConfUnitTest.FNAME, 'w') as f:
            f.writelines(data)

    @classmethod
    def tearDownClass(cls):
        '''Delete the temporary configuration file'''
        if os.path.exists(StasProcessConfUnitTest.FNAME):
            os.remove(StasProcessConfUnitTest.FNAME)

    def test_config(self):
        '''Check we can read the temporary configuration file'''

        default_conf = {
            ('Global', 'tron'): False,
            ('Global', 'hdr-digest'): False,
            ('Global', 'data-digest'): False,
            ('Global', 'kato'): None,  # None to let the driver decide the default
            ('Global', 'nr-io-queues'): None,  # None to let the driver decide the default
            ('Global', 'nr-write-queues'): None,  # None to let the driver decide the default
            ('Global', 'nr-poll-queues'): None,  # None to let the driver decide the default
            ('Global', 'queue-size'): None,  # None to let the driver decide the default
            ('Global', 'reconnect-delay'): None,  # None to let the driver decide the default
            ('Global', 'ctrl-loss-tmo'): None,  # None to let the driver decide the default
            ('Global', 'disable-sqflow'): None,  # None to let the driver decide the default
            ('Global', 'ignore-iface'): False,
            ('Global', 'ip-family'): (4, 6),
            ('Discovery controller connection management', 'persistent-connections'): True,
            ('Global', 'pleo'): True,
            ('Service Discovery', 'zeroconf'): True,
            ('Controllers', 'controller'): list(),
            ('Controllers', 'exclude'): list(),
            ('I/O controller connection management', 'disconnect-scope'): 'only-stas-connections',
            ('I/O controller connection management', 'disconnect-trtypes'): ['tcp'],
            ('I/O controller connection management', 'connect-attempts-on-ncc'): 0,
        }

        service_conf = conf.SvcConf(default_conf=default_conf)
        service_conf.set_conf_file(StasProcessConfUnitTest.FNAME)
        self.assertEqual(service_conf.conf_file, StasProcessConfUnitTest.FNAME)
        self.assertTrue(service_conf.tron)
        self.assertTrue(getattr(service_conf, 'tron'))
        self.assertFalse(service_conf.hdr_digest)
        self.assertFalse(service_conf.data_digest)
        self.assertTrue(service_conf.persistent_connections)
        self.assertTrue(service_conf.pleo_enabled)
        self.assertEqual(service_conf.disconnect_scope, 'only-stas-connections')
        self.assertEqual(service_conf.disconnect_trtypes, ['tcp'])
        self.assertFalse(service_conf.ignore_iface)
        self.assertIn(6, service_conf.ip_family)
        self.assertNotIn(4, service_conf.ip_family)
        self.assertEqual(service_conf.kato, 200)
        self.assertEqual(
            service_conf.get_controllers(),
            [
                {
                    'transport': 'tcp',
                    'traddr': '100.100.100.100',
                    'host-iface': 'enp0s8',
                },
                {
                    'transport': 'tcp',
                    'traddr': '100.100.100.200',
                    'host-iface': 'enp0s7',
                    'dhchap-ctrl-secret': 'super-secret',
                    'hdr-digest': True,
                    'data-digest': True,
                    'nr-io-queues': 8,
                    'nr-write-queues': 6,
                    'nr-poll-queues': 4,
                    'queue-size': 400,
                    'kato': 71,
                    'reconnect-delay': 13,
                    'ctrl-loss-tmo': 666,
                    'disable-sqflow': True,
                },
            ],
        )

        self.assertEqual(service_conf.get_excluded(), [{'transport': 'tcp', 'traddr': '10.10.10.10'}])

        stypes = service_conf.stypes
        self.assertIn('_nvme-disc._tcp', stypes)

        self.assertTrue(service_conf.zeroconf_enabled)
        self.assertEqual(service_conf.connect_attempts_on_ncc, 2)
        data = [
            '[I/O controller connection management]\n',
            'disconnect-trtypes = tcp+rdma+fc\n',
            'connect-attempts-on-ncc = hello\n',
        ]
        with open(StasProcessConfUnitTest.FNAME, 'w') as f:
            f.writelines(data)
        service_conf.reload()
        self.assertEqual(service_conf.connect_attempts_on_ncc, 0)
        self.assertEqual(set(service_conf.disconnect_trtypes), set(['fc', 'tcp', 'rdma']))

        data = [
            '[Global]\n',
            'ip-family=ipv4\n',
        ]
        with open(StasProcessConfUnitTest.FNAME, 'w') as f:
            f.writelines(data)
        service_conf.reload()
        self.assertIn(4, service_conf.ip_family)
        self.assertNotIn(6, service_conf.ip_family)

        data = [
            '[Global]\n',
            'ip-family=ipv4+ipv6\n',
        ]
        with open(StasProcessConfUnitTest.FNAME, 'w') as f:
            f.writelines(data)
        service_conf.reload()
        self.assertIn(4, service_conf.ip_family)
        self.assertIn(6, service_conf.ip_family)

        data = [
            '[Global]\n',
            'ip-family=ipv6+ipv4\n',
        ]
        with open(StasProcessConfUnitTest.FNAME, 'w') as f:
            f.writelines(data)
        service_conf.reload()
        self.assertIn(4, service_conf.ip_family)
        self.assertIn(6, service_conf.ip_family)

        self.assertRaises(KeyError, service_conf.get_option, 'Babylon', 5)

    def test__parse_single_val(self):
        self.assertEqual(conf._parse_single_val('hello'), 'hello')
        self.assertIsNone(conf._parse_single_val(None))
        self.assertEqual(conf._parse_single_val(['hello', 'goodbye']), 'goodbye')


class StasSysConfUnitTest(unittest.TestCase):
    '''Sys config unit tests'''

    FNAME_1 = '/tmp/stas-sys-config-test-1'
    FNAME_2 = '/tmp/stas-sys-config-test-2'
    FNAME_3 = '/tmp/stas-sys-config-test-3'
    FNAME_4 = '/tmp/stas-sys-config-test-4'
    NQN = 'nqn.2014-08.org.nvmexpress:uuid:9aae2691-b275-4b64-8bfe-5da429a2bab9'
    ID = '56529e15-0f3e-4ede-87e2-63932a4adb99'
    KEY = 'DHHC-1:03:qwertyuioplkjhgfdsazxcvbnm0123456789QWERTYUIOPLKJHGFDSAZXCVBNM010101010101010101010101010101:'
    SYMNAME = 'Bart-Simpson'

    DATA = {
        FNAME_1: [
            '[Host]\n',
            f'nqn={NQN}\n',
            f'id={ID}\n',
            f'key={KEY}\n',
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
            'nqn=file:///some/non/existing/file/!@#\n',
            'id=file:///some/non/existing/file/!@#\n',
            'symname=file:///some/non/existing/file/!@#\n',
        ],
    }

    @classmethod
    def setUpClass(cls):
        '''Create a temporary configuration file'''
        for file, data in StasSysConfUnitTest.DATA.items():
            with open(file, 'w') as f:
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
                'hostkey': StasSysConfUnitTest.KEY,
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


class TestParseController(unittest.TestCase):
    '''Unit tests for conf._parse_controller() — a pure function.'''

    def test_empty_string_returns_empty_dict(self):
        self.assertEqual(conf._parse_controller(''), {})

    def test_malformed_token_with_no_equals_is_silently_skipped(self):
        # Token without '=' causes ValueError in unpacking → silently ignored
        result = conf._parse_controller('noequalsign')
        self.assertEqual(result, {})

    def test_token_with_extra_equals_is_silently_skipped(self):
        # 'key=val=extra' splits into 3 parts → ValueError → silently ignored
        result = conf._parse_controller('key=val=extra')
        self.assertEqual(result, {})

    def test_mixed_valid_and_malformed_tokens(self):
        result = conf._parse_controller('transport=tcp;noequalsign;traddr=10.10.10.10')
        self.assertEqual(result, {'transport': 'tcp', 'traddr': '10.10.10.10'})


class TestSvcConfEdgeCases(unittest.TestCase):
    '''Edge-case tests for SvcConf validation: out-of-range values, invalid
    sections/options.  These tests rely on the SvcConf singleton having been
    initialised with a default_conf (which happens in StasProcessConfUnitTest),
    so they are defined after that class.
    '''

    FNAME_OOR = '/tmp/stas-test-svc-oor.conf'
    FNAME_BADSEC = '/tmp/stas-test-svc-badsec.conf'
    FNAME_BADOPT = '/tmp/stas-test-svc-badopt.conf'
    FNAME_VALID = '/tmp/stas-test-svc-valid.conf'

    @classmethod
    def setUpClass(cls):
        with open(cls.FNAME_OOR, 'w') as f:
            f.write('[Global]\nqueue-size=5\n')  # 5 is below the valid range [16, 1024]
        with open(cls.FNAME_BADSEC, 'w') as f:
            f.write('[BadSection]\nfoo=bar\n')
        with open(cls.FNAME_BADOPT, 'w') as f:
            f.write('[Global]\nbad-option=something\n')
        with open(cls.FNAME_VALID, 'w') as f:
            f.write('[Global]\nip-family=ipv4+ipv6\n')

    @classmethod
    def tearDownClass(cls):
        for fname in (cls.FNAME_OOR, cls.FNAME_BADSEC, cls.FNAME_BADOPT, cls.FNAME_VALID):
            if os.path.exists(fname):
                os.remove(fname)

    def setUp(self):
        conf.SvcConf().set_conf_file(self.FNAME_VALID)

    def test_queue_size_out_of_range_falls_back_to_none(self):
        conf.SvcConf().set_conf_file(self.FNAME_OOR)
        self.assertIsNone(conf.SvcConf().queue_size)

    def test_invalid_section_logs_error(self):
        with self.assertLogs(level='ERROR'):
            conf.SvcConf().set_conf_file(self.FNAME_BADSEC)

    def test_invalid_option_in_valid_section_logs_error(self):
        with self.assertLogs(level='ERROR'):
            conf.SvcConf().set_conf_file(self.FNAME_BADOPT)


class TestSysConfNqnTooLong(unittest.TestCase):
    '''Tests for SysConf NQN length validation (> 223 chars → sys.exit).'''

    FNAME = '/tmp/stas-test-long-nqn.conf'

    @classmethod
    def setUpClass(cls):
        long_nqn = 'nqn.' + 'a' * 220  # 224 chars — exceeds 223-char NVMe spec limit
        with open(cls.FNAME, 'w') as f:
            f.write(f'[Host]\nnqn={long_nqn}\n')

    @classmethod
    def tearDownClass(cls):
        # IMPORTANT: reset the SysConf singleton to an empty config BEFORE
        # deleting the temp file.  SysConf caches _config in memory; simply
        # deleting the file leaves the 224-char NQN in the cache.  When pytest
        # runs all test files in one process, trid.TID.__init__ unconditionally
        # evaluates sysconf.hostnqn (as the default arg to dict.get), so every
        # TID construction in later test files would hit sys.exit.
        conf.SysConf().set_conf_file('/dev/null')
        if os.path.exists(cls.FNAME):
            os.remove(cls.FNAME)

    def test_hostnqn_too_long_causes_exit(self):
        system_conf = conf.SysConf()
        system_conf.set_conf_file(self.FNAME)
        self.assertRaises(SystemExit, lambda: system_conf.hostnqn)


if __name__ == '__main__':
    unittest.main()
