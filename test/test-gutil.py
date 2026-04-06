#!/usr/bin/python3
import os
import unittest
from staslib import conf, gutil, trid

SUBSYSNQN = 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8'
HOSTNQN = 'nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab'


class GutilUnitTest(unittest.TestCase):
    '''Run unit test for gutil.py'''

    def _on_success(self, op_obj: gutil.AsyncTask, data):
        op_obj.kill()

    def _on_fail(self, op_obj: gutil.AsyncTask, err, fail_cnt):
        op_obj.kill()

    def _operation(self, data):
        return data

    def test_AsyncTask(self):
        op = gutil.AsyncTask(self._on_success, self._on_fail, self._operation, 'hello')

        self.assertIsInstance(str(op), str)
        self.assertEqual(op.as_dict(), {'fail count': 0, 'completed': None, 'alive': True})

        op.retry(10)
        self.assertIsNotNone(op.as_dict().get('retry timer'))

        errmsg = 'something scarry happened'
        op._errmsg = errmsg
        self.assertEqual(op.as_dict().get('error'), errmsg)


    def test_Deferred(self):
        called = []
        d = gutil.Deferred(lambda: called.append(1))
        self.assertFalse(d.is_scheduled())
        d.schedule()
        self.assertTrue(d.is_scheduled())
        # Scheduling again is a no-op (idempotent)
        d.schedule()
        self.assertTrue(d.is_scheduled())
        d.cancel()
        self.assertFalse(d.is_scheduled())
        # Cancel when already cancelled is safe
        d.cancel()
        self.assertFalse(d.is_scheduled())


# ==============================================================================
class TestNameResolver(unittest.TestCase):
    '''Unit tests for NameResolver.resolve_ctrl_async() — synchronous paths only.

    When traddr is already a valid IP address the resolver skips the async DNS
    lookup and calls the callback immediately from within resolve_ctrl_async().
    Non-TCP/RDMA transports also bypass DNS.  Only those two paths are exercised
    here; async DNS resolution requires a live network and is not unit-testable.
    '''

    FNAME_BOTH = '/tmp/stas-test-nr-both.conf'
    FNAME_IPV6 = '/tmp/stas-test-nr-ipv6.conf'

    @classmethod
    def setUpClass(cls):
        with open(cls.FNAME_BOTH, 'w') as f:
            f.write('[Global]\nip-family=ipv4+ipv6\n')
        with open(cls.FNAME_IPV6, 'w') as f:
            f.write('[Global]\nip-family=ipv6\n')
        conf.SvcConf().set_conf_file(cls.FNAME_BOTH)

    @classmethod
    def tearDownClass(cls):
        for fname in (cls.FNAME_BOTH, cls.FNAME_IPV6):
            if os.path.exists(fname):
                os.remove(fname)

    def setUp(self):
        # Reset to the "both families" config before every test so that a test
        # that switches to FNAME_IPV6 does not leak into the next one.
        conf.SvcConf().set_conf_file(self.FNAME_BOTH)

    def _make_tid(self, transport, traddr):
        return trid.TID({'transport': transport, 'traddr': traddr, 'subsysnqn': SUBSYSNQN, 'host-nqn': HOSTNQN})

    def test_empty_list_calls_callback_immediately(self):
        resolver = gutil.NameResolver()
        result = []
        resolver.resolve_ctrl_async(None, [], lambda ctrls: result.extend(ctrls))
        self.assertEqual(result, [])

    def test_ipv4_address_resolves_synchronously(self):
        resolver = gutil.NameResolver()
        t = self._make_tid('tcp', '10.10.10.10')
        result = []
        resolver.resolve_ctrl_async(None, [t], lambda ctrls: result.extend(ctrls))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].traddr, '10.10.10.10')

    def test_ipv6_address_resolves_synchronously(self):
        resolver = gutil.NameResolver()
        t = self._make_tid('tcp', '::1')
        result = []
        resolver.resolve_ctrl_async(None, [t], lambda ctrls: result.extend(ctrls))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].traddr, '::1')

    def test_fc_transport_passes_through_without_dns(self):
        resolver = gutil.NameResolver()
        t = self._make_tid('fc', 'nn-0x1000000044001123:pn-0x2000000055001123')
        result = []
        resolver.resolve_ctrl_async(None, [t], lambda ctrls: result.extend(ctrls))
        self.assertEqual(len(result), 1)

    def test_ipv4_excluded_when_only_ipv6_allowed(self):
        conf.SvcConf().set_conf_file(self.FNAME_IPV6)
        resolver = gutil.NameResolver()
        t = self._make_tid('tcp', '10.10.10.10')
        result = []
        resolver.resolve_ctrl_async(None, [t], lambda ctrls: result.extend(ctrls))
        self.assertEqual(result, [])


if __name__ == '__main__':
    unittest.main()
