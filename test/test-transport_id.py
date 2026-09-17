#!/usr/bin/python3
import unittest
from staslib import trid


class Test(unittest.TestCase):
    '''Unit test for class TRID'''

    TRANSPORT = 'tcp'
    TRADDR = '10.10.10.10'
    OTHER_TRADDR = '1.1.1.1'
    SUBSYSNQN = 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8'
    TRSVCID = '8009'
    HOST_TRADDR = '1.2.3.4'
    HOST_IFACE = 'wlp0s20f3'
    HOST_NQN = 'nqn.1988-11.com.dell:12345'
    HOST_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
    HOST_SYMNAME = 'lab-host-01'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cid = {
            'transport': Test.TRANSPORT,
            'traddr': Test.TRADDR,
            'subsysnqn': Test.SUBSYSNQN,
            'trsvcid': Test.TRSVCID,
            'host-traddr': Test.HOST_TRADDR,
            'host-iface': Test.HOST_IFACE,
            'hostnqn': Test.HOST_NQN,
            'hostid': Test.HOST_ID,
            'hostsymname': Test.HOST_SYMNAME,
        }
        self.other_cid = {
            'transport': Test.TRANSPORT,
            'traddr': Test.OTHER_TRADDR,
            'subsysnqn': Test.SUBSYSNQN,
            'trsvcid': Test.TRSVCID,
            'host-traddr': Test.HOST_TRADDR,
            'host-iface': Test.HOST_IFACE,
            'hostnqn': Test.HOST_NQN,
            'hostid': Test.HOST_ID,
            'hostsymname': Test.HOST_SYMNAME,
        }

        self.tid = trid.TID(self.cid)
        self.other_tid = trid.TID(self.other_cid)

    def test_hash(self):
        '''Check that a hash exists'''
        self.assertIsInstance(self.tid._hash, int)

    def test_transport(self):
        '''Check that transport is set'''
        self.assertEqual(self.tid.transport, Test.TRANSPORT)

    def test_traddr(self):
        '''Check that traddr is set'''
        self.assertEqual(self.tid.traddr, Test.TRADDR)

    def test_trsvcid(self):
        '''Check that trsvcid is set'''
        self.assertEqual(self.tid.trsvcid, Test.TRSVCID)

    def test_host_traddr(self):
        '''Check that host_traddr is set'''
        self.assertEqual(self.tid.host_traddr, Test.HOST_TRADDR)

    def test_host_iface(self):
        '''Check that host_iface is set'''
        self.assertEqual(self.tid.host_iface, Test.HOST_IFACE)

    def test_subsysnqn(self):
        '''Check that subsysnqn is set'''
        self.assertEqual(self.tid.subsysnqn, Test.SUBSYSNQN)

    def test_hostnqn(self):
        '''Check that hostnqn is set'''
        self.assertEqual(self.tid.hostnqn, Test.HOST_NQN)

    def test_hostid(self):
        '''A persona's own hostid is taken as-is - no system/main-file fallback'''
        self.assertEqual(self.tid.hostid, Test.HOST_ID)

    def test_hostsymname(self):
        '''hostsymname is a display label, not identity - it lives in cfg,
        not as its own field, and plays no part in _key.'''
        self.assertEqual(self.tid.cfg.get('hostsymname'), Test.HOST_SYMNAME)

    def test_persona_without_hostid_never_borrows_one(self):
        '''A persona's hostnqn without its own hostid, and with no hostid
        recoverable from the hostnqn itself, must not be paired with one that
        came from anywhere else.'''
        cid = dict(self.cid)
        del cid['hostid']
        tid = trid.TID(cid)
        self.assertEqual(tid.hostid, '')

    def test_persona_hostid_recovered_from_uuid_hostnqn(self):
        '''Base Spec 4.7 + TP4126: a uuid:-form hostnqn already encodes a
        hostid. Recovering it is not borrowing an identity from elsewhere.'''
        cid = dict(self.cid)
        del cid['hostid']
        cid['hostnqn'] = 'nqn.2014-08.org.nvmexpress:uuid:aaaaaaaa-0000-0000-0000-000000000001'
        tid = trid.TID(cid)
        self.assertEqual(tid.hostid, 'aaaaaaaa-0000-0000-0000-000000000001')

    def test_persona_own_hostid_wins_over_uuid_hostnqn(self):
        '''An explicit hostid is taken as-is, even when the hostnqn is
        uuid:-form and would otherwise imply a different one.'''
        cid = dict(self.cid)
        cid['hostnqn'] = 'nqn.2014-08.org.nvmexpress:uuid:aaaaaaaa-0000-0000-0000-000000000001'
        tid = trid.TID(cid)
        self.assertEqual(tid.hostid, Test.HOST_ID)

    def test_hostid_is_part_of_identity(self):
        '''Two connections identical except for hostid are a different
        Host-Subsystem association, and must not compare equal.'''
        cid = dict(self.cid)
        cid['hostid'] = 'bbbbbbbb-0000-0000-0000-000000000002'
        self.assertNotEqual(self.tid, trid.TID(cid))

    def test_as_dict(self):
        '''Check that a TRID can be converted back to the original Dict it was created with'''
        self.assertDictEqual(self.tid.as_dict(), self.cid)

    def test_str(self):
        '''Check that a TRID can be represented as a string'''
        self.assertTrue(str(self.tid).startswith(f'({Test.TRANSPORT},'))

    def test_eq(self):
        '''Check that two TRID objects can be tested for equality'''
        self.assertEqual(self.tid, trid.TID(self.cid))
        self.assertFalse(self.tid == 'blah')

    def test_ne(self):
        '''Check that two TID objects can be tested for non-equality'''
        self.assertNotEqual(self.tid, self.other_tid)
        self.assertNotEqual(self.tid, 'hello')


if __name__ == '__main__':
    unittest.main()
