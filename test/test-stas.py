#!/usr/bin/python3
import os
import shutil
import atexit
import tempfile
import unittest
from unittest.mock import patch
from staslib import conf, stas, trid
from pyfakefs.fake_filesystem_unittest import TestCase as FakeTestCase

HOSTNQN = 'nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab'
SUBSYSNQN = 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8'


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


# get_excluded() also reads libnvme's host-wide exclusion list. Keep these
# tests independent of what /etc/nvme/exclusions.conf holds on this machine.
libnvme_sandbox()


# ==============================================================================
class TestExcluded(unittest.TestCase):
    '''Unit tests for stas._excluded() — a pure function with no dependencies.'''

    def test_empty_exclusion_list(self):
        self.assertFalse(stas._excluded([], {'transport': 'tcp', 'traddr': '1.2.3.4'}))

    def test_exact_match_is_excluded(self):
        excluded = [{'transport': 'tcp', 'traddr': '1.2.3.4'}]
        self.assertTrue(stas._excluded(excluded, {'transport': 'tcp', 'traddr': '1.2.3.4'}))

    def test_partial_exclusion_matches_any_controller_with_that_field(self):
        # Exclusion specifies only transport — should match any TCP controller
        excluded = [{'transport': 'tcp'}]
        self.assertTrue(stas._excluded(excluded, {'transport': 'tcp', 'traddr': '99.99.99.99'}))

    def test_one_field_mismatch_not_excluded(self):
        excluded = [{'transport': 'tcp', 'traddr': '1.2.3.4'}]
        self.assertFalse(stas._excluded(excluded, {'transport': 'tcp', 'traddr': '5.5.5.5'}))

    def test_missing_key_in_controller_not_excluded(self):
        # Exclusion requires traddr but controller dict has none — should not match
        excluded = [{'transport': 'tcp', 'traddr': '1.2.3.4'}]
        self.assertFalse(stas._excluded(excluded, {'transport': 'tcp'}))

    def test_multiple_entries_first_matches(self):
        excluded = [
            {'transport': 'tcp', 'traddr': '1.2.3.4'},
            {'transport': 'rdma', 'traddr': '5.5.5.5'},
        ]
        self.assertTrue(stas._excluded(excluded, {'transport': 'tcp', 'traddr': '1.2.3.4'}))

    def test_multiple_entries_second_matches(self):
        excluded = [
            {'transport': 'tcp', 'traddr': '99.99.99.99'},
            {'transport': 'rdma', 'traddr': '5.5.5.5'},
        ]
        self.assertTrue(stas._excluded(excluded, {'transport': 'rdma', 'traddr': '5.5.5.5'}))

    def test_multiple_entries_none_match(self):
        excluded = [
            {'transport': 'tcp', 'traddr': '1.2.3.4'},
            {'transport': 'rdma', 'traddr': '5.5.5.5'},
        ]
        self.assertFalse(stas._excluded(excluded, {'transport': 'fc', 'traddr': '5.5.5.5'}))


# ==============================================================================
class TestTidFromDlpe(unittest.TestCase):
    '''Unit tests for stas.tid_from_dlpe().'''

    DLPE = {
        'trtype': 'tcp',
        'traddr': '10.10.10.10',
        'trsvcid': '8009',
        'subnqn': SUBSYSNQN,
    }

    def test_returns_tid_instance(self):
        result = stas.tid_from_dlpe(self.DLPE, host_traddr='1.2.3.4', host_iface='eth0', hostnqn=HOSTNQN)
        self.assertIsInstance(result, trid.TID)

    def test_transport_field(self):
        result = stas.tid_from_dlpe(self.DLPE, host_traddr='', host_iface='', hostnqn=HOSTNQN)
        self.assertEqual(result.transport, 'tcp')

    def test_traddr_field(self):
        result = stas.tid_from_dlpe(self.DLPE, host_traddr='', host_iface='', hostnqn=HOSTNQN)
        self.assertEqual(result.traddr, '10.10.10.10')

    def test_trsvcid_field(self):
        result = stas.tid_from_dlpe(self.DLPE, host_traddr='', host_iface='', hostnqn=HOSTNQN)
        self.assertEqual(result.trsvcid, '8009')

    def test_subsysnqn_field(self):
        result = stas.tid_from_dlpe(self.DLPE, host_traddr='', host_iface='', hostnqn=HOSTNQN)
        self.assertEqual(result.subsysnqn, SUBSYSNQN)

    def test_host_traddr_field(self):
        result = stas.tid_from_dlpe(self.DLPE, host_traddr='1.2.3.4', host_iface='', hostnqn=HOSTNQN)
        self.assertEqual(result.host_traddr, '1.2.3.4')

    def test_none_hostnqn_falls_back_to_sysconf(self):
        # When hostnqn is None, TID falls back to SysConf.hostnqn (which may
        # itself be None if /etc/nvme/hostnqn is absent — that is acceptable here)
        result = stas.tid_from_dlpe(self.DLPE, host_traddr='', host_iface='', hostnqn=None)
        self.assertIsInstance(result, trid.TID)

    def test_usable_as_dict_key(self):
        result = stas.tid_from_dlpe(self.DLPE, host_traddr='', host_iface='', hostnqn=HOSTNQN)
        d = {result: 'value'}
        self.assertEqual(d[result], 'value')

    def test_identical_dlpes_produce_equal_tids(self):
        t1 = stas.tid_from_dlpe(self.DLPE, '1.2.3.4', 'eth0', HOSTNQN)
        t2 = stas.tid_from_dlpe(self.DLPE, '1.2.3.4', 'eth0', HOSTNQN)
        self.assertEqual(t1, t2)

    def test_different_traddr_produces_unequal_tids(self):
        dlpe2 = dict(self.DLPE)
        dlpe2['traddr'] = '20.20.20.20'
        t1 = stas.tid_from_dlpe(self.DLPE, '1.2.3.4', 'eth0', HOSTNQN)
        t2 = stas.tid_from_dlpe(dlpe2, '1.2.3.4', 'eth0', HOSTNQN)
        self.assertNotEqual(t1, t2)

    def test_different_host_traddr_produces_unequal_tids(self):
        t1 = stas.tid_from_dlpe(self.DLPE, '1.2.3.4', 'eth0', HOSTNQN)
        t2 = stas.tid_from_dlpe(self.DLPE, '9.9.9.9', 'eth0', HOSTNQN)
        self.assertNotEqual(t1, t2)


# ==============================================================================
class TestRemoveExcluded(unittest.TestCase):
    '''Unit tests for stas.remove_excluded().'''

    FNAME = '/tmp/stas-test-remove-excluded.conf'

    @classmethod
    def setUpClass(cls):
        with open(cls.FNAME, 'w') as f:
            f.writelines(
                [
                    '[Controllers]\n',
                    'exclude=transport=tcp;traddr=10.10.10.10\n',
                    'exclude=transport=rdma;traddr=192.168.1.1\n',
                ]
            )
        conf.SvcConf().set_conf_file(cls.FNAME)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.FNAME):
            os.remove(cls.FNAME)

    def _make_tid(self, transport, traddr):
        return trid.TID({'transport': transport, 'traddr': traddr, 'subsysnqn': SUBSYSNQN, 'hostnqn': HOSTNQN})

    def test_empty_list_unchanged(self):
        self.assertEqual(stas.remove_excluded([]), [])

    def test_excluded_controller_is_removed(self):
        controllers = [self._make_tid('tcp', '10.10.10.10')]
        self.assertEqual(stas.remove_excluded(controllers), [])

    def test_second_exclusion_rule_applied(self):
        controllers = [self._make_tid('rdma', '192.168.1.1')]
        self.assertEqual(stas.remove_excluded(controllers), [])

    def test_non_excluded_controller_is_kept(self):
        t = self._make_tid('tcp', '1.1.1.1')
        self.assertEqual(stas.remove_excluded([t]), [t])

    def test_mixed_list_only_excluded_removed(self):
        excluded = self._make_tid('tcp', '10.10.10.10')
        kept = self._make_tid('tcp', '1.1.1.1')
        result = stas.remove_excluded([excluded, kept])
        self.assertNotIn(excluded, result)
        self.assertIn(kept, result)

    def test_multiple_non_excluded_all_kept(self):
        t1 = self._make_tid('tcp', '1.1.1.1')
        t2 = self._make_tid('tcp', '2.2.2.2')
        result = stas.remove_excluded([t1, t2])
        self.assertEqual(len(result), 2)


# ==============================================================================
class TestExcludedController(unittest.TestCase):
    '''Unit tests for stas.excluded().'''

    FNAME = '/tmp/stas-test-excluded.conf'
    EXCLUSIONS = [
        '[Controllers]\n',
        'exclude=transport=tcp;traddr=10.10.10.10\n',
        'exclude=host-iface=enp0s8\n',
    ]

    @classmethod
    def _write_conf(cls, lines):
        with open(cls.FNAME, 'w') as f:
            f.writelines(lines)

    @classmethod
    def setUpClass(cls):
        cls._write_conf(cls.EXCLUSIONS)
        conf.SvcConf().set_conf_file(cls.FNAME)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.FNAME):
            os.remove(cls.FNAME)

    def _make_tid(self, transport, traddr, host_iface=None):
        cid = {'transport': transport, 'traddr': traddr, 'subsysnqn': SUBSYSNQN, 'hostnqn': HOSTNQN}
        if host_iface:
            cid['host-iface'] = host_iface
        return trid.TID(cid)

    def test_excluded_controller(self):
        self.assertTrue(stas.excluded(self._make_tid('tcp', '10.10.10.10')))

    def test_non_excluded_controller(self):
        self.assertFalse(stas.excluded(self._make_tid('tcp', '1.1.1.1')))

    def test_partial_match_is_excluded(self):
        # An "exclude=" entry that only sets host-iface excludes
        # every controller on that interface.
        self.assertFalse(stas.excluded(self._make_tid('rdma', '1.1.1.1', 'enp0s3')))
        self.assertTrue(stas.excluded(self._make_tid('rdma', '1.1.1.1', 'enp0s8')))

    def test_exclusion_list_read_at_every_call(self):
        # The exclusion list is consulted on each call, so a controller that
        # was not excluded before a config reload is excluded after it.
        self.addCleanup(self._restore_conf)
        tid = self._make_tid('tcp', '5.5.5.5')
        self.assertFalse(stas.excluded(tid))
        self._write_conf(['[Controllers]\n', 'exclude=transport=tcp;traddr=5.5.5.5\n'])
        conf.SvcConf().reload()
        self.assertTrue(stas.excluded(tid))

    def _restore_conf(self):
        self._write_conf(self.EXCLUSIONS)
        conf.SvcConf().reload()


# ==============================================================================
class TestRemoveInvalidAddresses(unittest.TestCase):
    '''Unit tests for stas.remove_invalid_addresses().'''

    FNAME_BOTH = '/tmp/stas-test-addr-both.conf'
    FNAME_IPV4 = '/tmp/stas-test-addr-ipv4.conf'
    FNAME_IPV6 = '/tmp/stas-test-addr-ipv6.conf'

    @classmethod
    def setUpClass(cls):
        for fname, family in (
            (cls.FNAME_BOTH, 'ipv4+ipv6'),
            (cls.FNAME_IPV4, 'ipv4'),
            (cls.FNAME_IPV6, 'ipv6'),
        ):
            with open(fname, 'w') as f:
                f.write(f'[Global]\nip-family={family}\n')

    @classmethod
    def tearDownClass(cls):
        for fname in (cls.FNAME_BOTH, cls.FNAME_IPV4, cls.FNAME_IPV6):
            if os.path.exists(fname):
                os.remove(fname)

    def _make_tid(self, transport, traddr):
        return trid.TID({'transport': transport, 'traddr': traddr, 'subsysnqn': SUBSYSNQN, 'hostnqn': HOSTNQN})

    def test_empty_list_unchanged(self):
        conf.SvcConf().set_conf_file(self.FNAME_BOTH)
        self.assertEqual(stas.remove_invalid_addresses([]), [])

    def test_valid_ipv4_kept_when_both_families_allowed(self):
        conf.SvcConf().set_conf_file(self.FNAME_BOTH)
        t = self._make_tid('tcp', '10.10.10.10')
        self.assertEqual(stas.remove_invalid_addresses([t]), [t])

    def test_valid_ipv6_kept_when_both_families_allowed(self):
        conf.SvcConf().set_conf_file(self.FNAME_BOTH)
        t = self._make_tid('tcp', '::1')
        self.assertEqual(stas.remove_invalid_addresses([t]), [t])

    def test_invalid_address_always_removed(self):
        conf.SvcConf().set_conf_file(self.FNAME_BOTH)
        t = self._make_tid('tcp', 'not-an-ip-address')
        self.assertEqual(stas.remove_invalid_addresses([t]), [])

    def test_ipv4_removed_when_only_ipv6_enabled(self):
        conf.SvcConf().set_conf_file(self.FNAME_IPV6)
        t = self._make_tid('tcp', '10.10.10.10')
        self.assertEqual(stas.remove_invalid_addresses([t]), [])

    def test_ipv6_removed_when_only_ipv4_enabled(self):
        conf.SvcConf().set_conf_file(self.FNAME_IPV4)
        t = self._make_tid('tcp', '::1')
        self.assertEqual(stas.remove_invalid_addresses([t]), [])

    def test_ipv4_kept_when_only_ipv4_enabled(self):
        conf.SvcConf().set_conf_file(self.FNAME_IPV4)
        t = self._make_tid('tcp', '10.10.10.10')
        self.assertEqual(stas.remove_invalid_addresses([t]), [t])

    def test_ipv6_kept_when_only_ipv6_enabled(self):
        conf.SvcConf().set_conf_file(self.FNAME_IPV6)
        t = self._make_tid('tcp', '::1')
        self.assertEqual(stas.remove_invalid_addresses([t]), [t])

    def test_rdma_with_valid_ipv4_kept(self):
        conf.SvcConf().set_conf_file(self.FNAME_BOTH)
        t = self._make_tid('rdma', '192.168.0.1')
        self.assertEqual(stas.remove_invalid_addresses([t]), [t])

    def test_fc_transport_always_kept_regardless_of_ip_family(self):
        conf.SvcConf().set_conf_file(self.FNAME_IPV4)
        t = self._make_tid('fc', 'nn-0x1000000044001123:pn-0x2000000055001123')
        self.assertEqual(stas.remove_invalid_addresses([t]), [t])

    def test_loop_transport_always_kept(self):
        conf.SvcConf().set_conf_file(self.FNAME_IPV4)
        t = self._make_tid('loop', '')
        self.assertEqual(stas.remove_invalid_addresses([t]), [t])

    def test_unknown_transport_always_removed(self):
        conf.SvcConf().set_conf_file(self.FNAME_BOTH)
        t = self._make_tid('unknown', '10.10.10.10')
        self.assertEqual(stas.remove_invalid_addresses([t]), [])


# ==============================================================================
class TestLoadIdl(unittest.TestCase):
    '''Unit tests for stas.load_idl().'''

    def test_stafd_idl_returns_content(self):
        content = stas.load_idl('stafd.idl')
        self.assertIsInstance(content, str)
        self.assertGreater(len(content), 0)

    def test_stacd_idl_returns_content(self):
        content = stas.load_idl('stacd.idl')
        self.assertIsInstance(content, str)
        self.assertGreater(len(content), 0)

    def test_nonexistent_idl_returns_empty_string(self):
        content = stas.load_idl('nonexistent.idl')
        self.assertEqual(content, '')


# ==============================================================================
class TestCheckIfAllowedToContinue(FakeTestCase):
    '''Unit tests for stas.check_if_allowed_to_continue() using a fake filesystem.'''

    def setUp(self):
        self.setUpPyfakefs()

    def test_exits_when_not_root(self):
        with patch('os.geteuid', return_value=1000):
            with self.assertRaises(SystemExit):
                stas.check_if_allowed_to_continue()

    def test_exits_when_nvme_fabrics_missing(self):
        # /dev/nvme-fabrics is absent in the fake filesystem by default
        with patch('os.geteuid', return_value=0):
            with self.assertRaises(SystemExit):
                stas.check_if_allowed_to_continue()

    def test_returns_normally_when_root_and_nvme_fabrics_present(self):
        self.fs.create_file('/dev/nvme-fabrics')
        with patch('os.geteuid', return_value=0):
            stas.check_if_allowed_to_continue()  # Must not raise


if __name__ == '__main__':
    unittest.main()
