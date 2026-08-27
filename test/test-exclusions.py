#!/usr/bin/python3
import os
import shutil
import tempfile
import unittest
from staslib import conf, stas, trid

HOSTNQN = 'nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab'
SUBSYSNQN = 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8'


# ==============================================================================
class TestLibnvmeExclusions(unittest.TestCase):
    '''Unit tests for libnvme's host-wide exclusion list, which stas reads in
    addition to the "exclude=" keyword of stafd.conf/stacd.conf.

    libnvme reads its files from C, which is why these tests use a real
    directory under /tmp (redirected with ctx.set_test_base_dir()) instead of
    pyfakefs.
    '''

    @classmethod
    def setUpClass(cls):
        # The test base dir must be under /tmp. Layout is flat:
        # <base>/exclusions.conf and <base>/exclusions.conf.d/<name>.conf
        cls.SANDBOX = tempfile.mkdtemp(dir='/tmp')
        cls.DROPIN_DIR = os.path.join(cls.SANDBOX, 'exclusions.conf.d')
        cls.CONF_FILE = os.path.join(cls.SANDBOX, 'stafd.conf')
        os.mkdir(cls.DROPIN_DIR)
        conf.libnvme_ctx().set_test_base_dir(cls.SANDBOX)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.SANDBOX, ignore_errors=True)

    def setUp(self):
        self._write_exclusions(None)
        self._write_conf()

    def _write_exclusions(self, entries, name=None):
        '''Write libnvme's main exclusion list, or a named drop-in list.'''
        fname = os.path.join(self.DROPIN_DIR, name + '.conf') if name else os.path.join(self.SANDBOX, 'exclusions.conf')
        if entries is None:
            if os.path.exists(fname):
                os.remove(fname)
            return

        with open(fname, 'w') as f:
            f.write('[exclusions]\n')
            f.writelines(['exclusion = ' + entry + '\n' for entry in entries])

    def _write_conf(self, excluded=()):
        '''Write stafd.conf with the given "exclude=" entries.'''
        with open(self.CONF_FILE, 'w') as f:
            f.write('[Controllers]\n')
            f.writelines(['exclude=' + entry + '\n' for entry in excluded])
        conf.SvcConf().set_conf_file(self.CONF_FILE)

    def _make_tid(self, **kwargs):
        cid = {'transport': 'tcp', 'traddr': '1.1.1.1', 'subsysnqn': SUBSYSNQN, 'hostnqn': HOSTNQN}
        cid.update(kwargs)
        return trid.TID(cid)

    def test_no_exclusion_files(self):
        self.assertEqual(conf.SvcConf().get_excluded(), [])
        self.assertFalse(stas.excluded(self._make_tid()))

    def test_main_list(self):
        self._write_exclusions(['transport=tcp;traddr=10.10.10.10'])
        self.assertTrue(stas.excluded(self._make_tid(traddr='10.10.10.10')))
        self.assertFalse(stas.excluded(self._make_tid()))

    def test_dropin_list(self):
        self._write_exclusions(['host-iface=enp0s8'], name='maintenance')
        self.addCleanup(self._write_exclusions, None, 'maintenance')
        self.assertTrue(stas.excluded(self._make_tid(**{'host-iface': 'enp0s8'})))
        self.assertFalse(stas.excluded(self._make_tid(**{'host-iface': 'enp0s3'})))

    def test_main_and_dropin_lists_are_merged(self):
        self._write_exclusions(['traddr=10.10.10.10'])
        self._write_exclusions(['traddr=20.20.20.20'], name='maintenance')
        self.addCleanup(self._write_exclusions, None, 'maintenance')
        self.assertEqual(len(conf.SvcConf().get_excluded()), 2)
        self.assertTrue(stas.excluded(self._make_tid(traddr='10.10.10.10')))
        self.assertTrue(stas.excluded(self._make_tid(traddr='20.20.20.20')))

    def test_nqn_is_renamed_to_subsysnqn(self):
        # libnvme spells the subsystem NQN "nqn"
        self._write_exclusions(['nqn=' + SUBSYSNQN])
        self.assertEqual(conf.SvcConf().get_excluded(), [{'subsysnqn': SUBSYSNQN}])
        self.assertTrue(stas.excluded(self._make_tid()))

    def test_minimal_match(self):
        # Only the fields the entry sets are compared
        self._write_exclusions(['transport=tcp;traddr=10.10.10.10;trsvcid=4420'])
        self.assertTrue(stas.excluded(self._make_tid(traddr='10.10.10.10', trsvcid='4420')))
        self.assertFalse(stas.excluded(self._make_tid(traddr='10.10.10.10', trsvcid='8009')))

    def test_field_absent_from_controller(self):
        self._write_exclusions(['host-traddr=1.2.3.4'])
        self.assertFalse(stas.excluded(self._make_tid()))
        self.assertTrue(stas.excluded(self._make_tid(**{'host-traddr': '1.2.3.4'})))

    def test_hostnqn_entry(self):
        self._write_exclusions(['hostnqn=' + HOSTNQN])
        self.assertTrue(stas.excluded(self._make_tid()))
        self.assertFalse(stas.excluded(self._make_tid(hostnqn='nqn.2014-08.org.nvmexpress:uuid:other')))

    def test_hostid_of_this_host_excludes_everything(self):
        # Our TIDs carry no hostid, so it is resolved when the list is built:
        # an entry naming this host's hostid matches every controller, the way
        # libnvme's exclusion_match() does.
        self._write_exclusions(['hostid=' + conf.SysConf().hostid])
        self.assertEqual(conf.SvcConf().get_excluded(), [{}])
        self.assertTrue(stas.excluded(self._make_tid()))

    def test_hostid_of_another_host_excludes_nothing(self):
        self._write_exclusions(['hostid=deadbeef-0000-0000-0000-000000000000;traddr=1.1.1.1'])
        self.assertEqual(conf.SvcConf().get_excluded(), [])
        self.assertFalse(stas.excluded(self._make_tid()))

    def test_malformed_entries_exclude_nothing(self):
        # An unknown key, a bare token, or an entry with an empty value must
        # not take the daemon down and must not match anything.
        self._write_exclusions(['bogus=x', 'baretoken', 'nqn=', 'subsysnqn=' + SUBSYSNQN])
        self.assertFalse(stas.excluded(self._make_tid()))

    def test_ipv6_spelling(self):
        # Addresses are compared in normalized form, like libnvme does
        self._write_exclusions(['traddr=fe80::2c6e:dee7:857:26bb'])
        self.assertTrue(stas.excluded(self._make_tid(traddr='fe80:0000:0000:0000:2c6e:dee7:0857:26bb')))

    def test_fc_wwn_comma_spelling(self):
        # Some Discovery Controllers report the WWN pair comma-separated
        wwn = 'nn-0x204600a098cbcac6:pn-0x204700a098cbcac6'
        self._write_exclusions(['transport=fc;traddr=' + wwn])
        self.assertTrue(stas.excluded(self._make_tid(transport='fc', traddr=wwn.replace(':', ',', 1))))

    def test_hostname_traddr_is_not_excluded(self):
        # Before name resolution, traddr may be a hostname. libnvme's list
        # holds numeric addresses only, so it cannot match one -- and must not
        # raise trying.
        self._write_exclusions(['traddr=10.10.10.10'])
        self.assertFalse(stas.excluded(self._make_tid(traddr='dc.example.com')))

    def test_added_entry_is_seen_without_a_reload(self):
        # libnvme's list is read live: it is host-wide and other tools write
        # it behind our back.
        tid = self._make_tid(traddr='10.10.10.10')
        self.assertFalse(stas.excluded(tid))
        self._write_exclusions(['traddr=10.10.10.10'])
        self.assertTrue(stas.excluded(tid))

    def test_both_sources_are_honored(self):
        self._write_conf(['transport=tcp;traddr=10.10.10.10'])
        self._write_exclusions(['traddr=20.20.20.20'])
        self.assertTrue(stas.excluded(self._make_tid(traddr='10.10.10.10')))
        self.assertTrue(stas.excluded(self._make_tid(traddr='20.20.20.20')))
        self.assertFalse(stas.excluded(self._make_tid(traddr='30.30.30.30')))

    def test_empty_exclude_keyword_excludes_nothing(self):
        # An "exclude=" with no key=value pair sets no field. It must not be
        # read as "exclude everything".
        self._write_conf([''])
        self.assertEqual(conf.SvcConf().get_excluded(), [])
        self.assertFalse(stas.excluded(self._make_tid()))

    def test_remove_excluded_uses_both_sources(self):
        self._write_conf(['traddr=10.10.10.10'])
        self._write_exclusions(['traddr=20.20.20.20'])
        kept = self._make_tid(traddr='30.30.30.30')
        controllers = [self._make_tid(traddr='10.10.10.10'), self._make_tid(traddr='20.20.20.20'), kept]
        self.assertEqual(stas.remove_excluded(controllers), [kept])


if __name__ == '__main__':
    unittest.main()
