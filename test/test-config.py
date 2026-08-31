#!/usr/bin/python3
import os
import atexit
import shutil
import tempfile
import unittest
from staslib import conf


def libnvme_sandbox():
    '''Return a directory where libnvme reads its host-wide config files.

    libnvme's test base dir is process-global and only the first call takes
    effect, so every test file that needs one must agree on the same path:
    "meson test" runs each file in its own process, but pytest runs them all
    in one. The path must be under /tmp.
    '''
    path = os.path.join(tempfile.gettempdir(), 'nvme-stas-test-%d' % os.getpid())
    if not os.path.exists(path):
        os.makedirs(path)
        atexit.register(shutil.rmtree, path, ignore_errors=True)
    conf.libnvme_ctx().set_test_base_dir(path)
    return path


class StasProcessConfUnitTest(unittest.TestCase):
    '''Process config unit tests'''

    FNAME = '/tmp/stas-process-config-test'

    @classmethod
    def setUpClass(cls):
        '''Create a temporary configuration file'''
        # get_excluded() also reads libnvme's host-wide exclusion list. Point
        # libnvme at a sandbox so this test doesn't depend on what
        # /etc/nvme/exclusions.conf happens to hold on the build machine.
        cls.SANDBOX = libnvme_sandbox()
        for fname in (os.path.join(cls.SANDBOX, 'exclusions.conf'), os.path.join(cls.SANDBOX, 'exclusions.conf.d')):
            if os.path.exists(fname):
                shutil.rmtree(fname, ignore_errors=True) if os.path.isdir(fname) else os.remove(fname)

        data = [
            '[Global]\n',
            'tron=true\n',
            'ip-family=ipv6\n',
            '\n',
            '[I/O controller connection management]\n',
            'honor-fabric-zoning = joe\n',
            'connect-attempts-on-ncc = 1\n',
            '\n',
            '[Controllers]\n',
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
            ('Global', 'ignore-iface'): False,
            ('Global', 'ip-family'): (4, 6),
            ('Global', 'pleo'): True,
            ('Service Discovery', 'zeroconf'): True,
            ('Controllers', 'controller'): list(),
            ('Controllers', 'exclude'): list(),
            ('I/O controller connection management', 'honor-fabric-zoning'): True,
            ('I/O controller connection management', 'connect-attempts-on-ncc'): 0,
        }

        conf.SvcConf.destroy()  # Make sure singleton does not exist
        self.addCleanup(conf.SvcConf.destroy)
        service_conf = conf.SvcConf(default_conf=default_conf)
        service_conf.set_conf_file(StasProcessConfUnitTest.FNAME)
        self.assertEqual(service_conf.conf_file, StasProcessConfUnitTest.FNAME)
        self.assertTrue(service_conf.tron)
        self.assertTrue(getattr(service_conf, 'tron'))
        self.assertTrue(service_conf.pleo_enabled)
        self.assertEqual(service_conf.honor_fabric_zoning, True)
        self.assertFalse(service_conf.ignore_iface)
        self.assertIn(6, service_conf.ip_family)
        self.assertNotIn(4, service_conf.ip_family)
        self.assertEqual(service_conf.get_excluded(), [{'transport': 'tcp', 'traddr': '10.10.10.10'}])


class StasSysConfUnitTest(unittest.TestCase):
    '''Unit tests for SysConf, which reads the host identity from the files
    the nvme-cli family keeps it in.'''

    NQN = 'nqn.2014-08.org.nvmexpress:uuid:9aae2691-b275-4b64-8bfe-5da429a2bab9'
    ID = '56529e15-0f3e-4ede-87e2-63932a4adb99'

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._dir, True)
        # Leave no instance behind: the next caller must be free to build one
        # pointing at the real files. Matters when pytest runs every test file
        # in one process.
        conf.SysConf.destroy()
        self.addCleanup(conf.SysConf.destroy)

    def _sysconf(self, nqn=NQN, hostid=ID):
        '''Build a SysConf over temporary files. A None value means the file
        is not created at all.'''
        paths = list()
        for name, content in (('hostnqn', nqn), ('hostid', hostid)):
            path = os.path.join(self._dir, name)
            if content is not None:
                with open(path, 'w') as f:
                    f.write(content + '\n')
            paths.append(path)

        return conf.SysConf(hostnqn_file=paths[0], hostid_file=paths[1])

    def test_reads_the_host_identity(self):
        system_conf = self._sysconf()
        self.assertEqual(system_conf.hostnqn, StasSysConfUnitTest.NQN)
        self.assertEqual(system_conf.hostid, StasSysConfUnitTest.ID)
        self.assertEqual(
            system_conf.as_dict(),
            {'hostnqn': StasSysConfUnitTest.NQN, 'hostid': StasSysConfUnitTest.ID},
        )

    def test_a_missing_file_is_fatal(self):
        '''Both are mandatory, so neither can be absent.'''
        system_conf = self._sysconf(nqn=None, hostid=None)
        self.assertRaises(SystemExit, lambda: system_conf.hostnqn)
        self.assertRaises(SystemExit, lambda: system_conf.hostid)

    def test_an_empty_file_is_fatal(self):
        system_conf = self._sysconf(nqn='', hostid='')
        self.assertRaises(SystemExit, lambda: system_conf.hostnqn)
        self.assertRaises(SystemExit, lambda: system_conf.hostid)

    def test_the_nqn_must_look_like_one(self):
        system_conf = self._sysconf(nqn='qnq.2014-08.org.nvmexpress:uuid:9aae2691')
        self.assertRaises(SystemExit, lambda: system_conf.hostnqn)
        self.assertEqual(system_conf.hostid, StasSysConfUnitTest.ID)

    def test_the_nqn_cannot_exceed_223_characters(self):
        system_conf = self._sysconf(nqn='nqn.' + 'a' * 220)  # 224 chars
        self.assertRaises(SystemExit, lambda: system_conf.hostnqn)

    def test_trailing_content_is_ignored(self):
        '''Only the first word of the first line is the value.'''
        system_conf = self._sysconf(nqn=StasSysConfUnitTest.NQN + ' and then some\nsecond line')
        self.assertEqual(system_conf.hostnqn, StasSysConfUnitTest.NQN)


class TestDcGiveupTimeout(unittest.TestCase):
    '''Unit tests for the dc-giveup-timeout encoding: "infinity" never gives
    up, 0 gives up immediately, anything else is a time span.'''

    SECTION = 'Discovery controller connection management'

    def setUp(self):
        fd, self.fname = tempfile.mkstemp(prefix='stas-giveup-', suffix='.conf')
        os.close(fd)
        self.addCleanup(os.remove, self.fname)
        conf.SvcConf.destroy()
        self.addCleanup(conf.SvcConf.destroy)

    def _load(self, value):
        with open(self.fname, 'w') as f:
            f.write('[%s]\ndc-giveup-timeout=%s\n' % (TestDcGiveupTimeout.SECTION, value))
        cnf = conf.SvcConf()
        cnf.set_conf_file(self.fname)
        return cnf

    def test_infinity_never_gives_up(self):
        # Carried as -1: that is what the code that arms the timer tests for.
        self.assertEqual(self._load('infinity').dc_giveup_timeout_sec, -1)
        self.assertEqual(self._load('INFINITY').dc_giveup_timeout_sec, -1)

    def test_zero_gives_up_immediately(self):
        self.assertEqual(self._load('0').dc_giveup_timeout_sec, 0)

    def test_a_time_span_is_seconds(self):
        self.assertEqual(self._load('72hours').dc_giveup_timeout_sec, 72 * 60 * 60)
        self.assertEqual(self._load('3 days 5 hours').dc_giveup_timeout_sec, (3 * 24 + 5) * 60 * 60)

    def test_a_unit_less_value_is_seconds_not_hours(self):
        self.assertEqual(self._load('72').dc_giveup_timeout_sec, 72)

    def test_a_negative_value_is_rejected(self):
        '''"infinity" is how forever is spelled; -1 no longer means anything.'''
        cnf = self._load('-1')
        # The conversion is lazy: it happens when the property is read, not
        # when the file is loaded, so the warning lands here.
        with self.assertLogs(level='WARNING'):
            self.assertEqual(cnf.dc_giveup_timeout_sec, 72 * 60 * 60)  # the default

    def test_garbage_falls_back_to_the_default(self):
        cnf = self._load('not-a-timespan')
        with self.assertLogs(level='WARNING'):
            self.assertEqual(cnf.dc_giveup_timeout_sec, 72 * 60 * 60)


class TestEpcsdPollInterval(unittest.TestCase):
    '''Unit tests for epcsd-poll-interval-minutes'''

    SECTION = 'Discovery controller connection management'

    def setUp(self):
        fd, self.fname = tempfile.mkstemp(prefix='stas-poll-', suffix='.conf')
        os.close(fd)
        self.addCleanup(os.remove, self.fname)
        conf.SvcConf.destroy()
        self.addCleanup(conf.SvcConf.destroy)

    def _load(self, value):
        with open(self.fname, 'w') as f:
            f.write('[%s]\nepcsd-poll-interval-minutes=%s\n' % (TestEpcsdPollInterval.SECTION, value))
        cnf = conf.SvcConf()
        cnf.set_conf_file(self.fname)
        return cnf

    def test_minutes_are_returned_as_seconds(self):
        self.assertEqual(self._load('15').epcsd_poll_interval_sec, 900)
        self.assertEqual(self._load('1').epcsd_poll_interval_sec, 60)

    def test_zero_is_rejected(self):
        '''This poll is the only way a parked controller comes back, so
        "never" is not a valid answer.'''
        cnf = self._load('0')
        with self.assertLogs(level='WARNING'):
            self.assertEqual(cnf.epcsd_poll_interval_sec, 900)  # the default

    def test_a_negative_value_is_rejected(self):
        cnf = self._load('-5')
        with self.assertLogs(level='WARNING'):
            self.assertEqual(cnf.epcsd_poll_interval_sec, 900)

    def test_garbage_is_rejected(self):
        cnf = self._load('quarter-hourly')
        with self.assertLogs(level='WARNING'):
            self.assertEqual(cnf.epcsd_poll_interval_sec, 900)

    def test_the_default_is_fifteen_minutes(self):
        with open(self.fname, 'w') as f:
            f.write('[%s]\n' % TestEpcsdPollInterval.SECTION)
        cnf = conf.SvcConf()
        cnf.set_conf_file(self.fname)
        self.assertEqual(cnf.epcsd_poll_interval_sec, 900)


class TestParseController(unittest.TestCase):
    '''Unit tests for conf._parse_controller() — a pure function.'''

    def test_empty_string_returns_empty_dict(self):
        self.assertEqual(conf._parse_controller(''), {})

    def test_malformed_token_with_no_equals_is_silently_skipped(self):
        # Token without '=' causes ValueError in unpacking → silently ignored
        result = conf._parse_controller('noequalsign')
        self.assertEqual(result, {})

    def test_token_with_extra_equals_preserves_value(self):
        # split('=', maxsplit=1) keeps extra '=' in value (needed for base64-padded KXCHAP secrets)
        result = conf._parse_controller('key=val=extra')
        self.assertEqual(result, {'key': 'val=extra'})

    def test_mixed_valid_and_malformed_tokens(self):
        result = conf._parse_controller('transport=tcp;noequalsign;traddr=10.10.10.10')
        self.assertEqual(result, {'transport': 'tcp', 'traddr': '10.10.10.10'})


class TestSvcConfEdgeCases(unittest.TestCase):
    '''Edge-case tests for SvcConf validation: out-of-range values, invalid
    sections/options.

    SvcConf only validates sections and options when it was built with a
    default_conf, so these tests build the singleton themselves. Inheriting
    whichever instance happened to be created first is not good enough: any
    module that calls SvcConf() with no arguments gets a singleton that
    validates nothing, and every test here would then silently pass on a
    config file that was never checked.
    '''

    DEFAULT_CONF = {
        ('Global', 'ip-family'): (4, 6),
    }

    FNAME_BADSEC = '/tmp/stas-test-svc-badsec.conf'
    FNAME_BADOPT = '/tmp/stas-test-svc-badopt.conf'
    FNAME_VALID = '/tmp/stas-test-svc-valid.conf'

    @classmethod
    def setUpClass(cls):
        conf.SvcConf.destroy()  # Make sure singleton does not exist
        conf.SvcConf(default_conf=cls.DEFAULT_CONF)

        with open(cls.FNAME_BADSEC, 'w') as f:
            f.write('[BadSection]\nfoo=bar\n')
        with open(cls.FNAME_BADOPT, 'w') as f:
            f.write('[Global]\nbad-option=something\n')
        with open(cls.FNAME_VALID, 'w') as f:
            f.write('[Global]\nip-family=ipv4+ipv6\n')

    @classmethod
    def tearDownClass(cls):
        conf.SvcConf.destroy()  # Leave the next test file a clean slate

        for fname in (cls.FNAME_BADSEC, cls.FNAME_BADOPT, cls.FNAME_VALID):
            if os.path.exists(fname):
                os.remove(fname)

    def setUp(self):
        conf.SvcConf().set_conf_file(self.FNAME_VALID)

    def test_invalid_section_logs_error(self):
        with self.assertLogs(level='ERROR'):
            conf.SvcConf().set_conf_file(self.FNAME_BADSEC)

    def test_invalid_option_in_valid_section_logs_error(self):
        with self.assertLogs(level='ERROR'):
            conf.SvcConf().set_conf_file(self.FNAME_BADOPT)


if __name__ == '__main__':
    unittest.main()
