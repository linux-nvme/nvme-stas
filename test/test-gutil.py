#!/usr/bin/python3
import os
import logging
import unittest
import unittest.mock
from gi.repository import Gio, GLib
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

        # Killing a task with a retry pending kills the retry timer too
        retry_tmr = op._retry_tmr
        op.kill()
        self.assertIsNone(op._retry_tmr)
        self.assertEqual(retry_tmr.time_remaining(), 0)


    def test_run_async_is_a_no_op_while_running(self):
        op = gutil.AsyncTask(self._on_success, self._on_fail, self._operation, 'hello')
        self.addCleanup(op.kill)
        running_task = unittest.mock.Mock()
        running_task.get_completed.return_value = False
        op._task = running_task
        with unittest.mock.patch.object(gutil, '_TaskRunner') as task_runner:
            op.run_async()
        task_runner.assert_not_called()
        self.assertIs(op._task, running_task)

    def test_a_result_arriving_after_kill_is_dropped(self):
        """The operation ran to the end in its thread after we stopped caring"""
        success_cb = unittest.mock.Mock()
        fail_cb = unittest.mock.Mock()
        op = gutil.AsyncTask(success_cb, fail_cb, self._operation, 'hello')
        op.kill()
        runner = unittest.mock.Mock()
        op._on_operation_complete(runner, None)
        runner.communicate_finish.assert_not_called()
        success_cb.assert_not_called()
        fail_cb.assert_not_called()

    def test_retry_timeout_reruns_only_a_live_task(self):
        op = gutil.AsyncTask(self._on_success, self._on_fail, self._operation, 'hello')
        with unittest.mock.patch.object(op, 'run_async') as run_async:
            self.assertEqual(op._on_retry_timeout('arg'), GLib.SOURCE_REMOVE)
            run_async.assert_called_once_with('arg')

            op.cancel()
            run_async.reset_mock()
            self.assertEqual(op._on_retry_timeout('arg'), GLib.SOURCE_REMOVE)
            run_async.assert_not_called()
        op.kill()

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
        return trid.TID({'transport': transport, 'traddr': traddr, 'subsysnqn': SUBSYSNQN, 'hostnqn': HOSTNQN})

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

    def test_an_empty_traddr_is_dropped(self):
        resolver = gutil.NameResolver()
        result = []
        with self.assertLogs(level='ERROR') as captured:
            resolver.resolve_ctrl_async(None, [self._make_tid('tcp', '')], lambda ctrls: result.append(ctrls))
        self.assertIn('Invalid traddr', captured.output[0])
        self.assertEqual(result, [[]])

    def test_a_cancelled_resolution_drops_the_controller_quietly(self):
        '''Cancelling is how a stopping daemon abandons a lookup: not an error'''
        cancellable = Gio.Cancellable()
        cancellable.cancel()
        loop = GLib.MainLoop()
        result = []

        def done(ctrls):
            result.append(ctrls)
            loop.quit()

        GLib.timeout_add_seconds(5, loop.quit)  # never hang the test
        with self.assertLogs(level='DEBUG') as captured:
            gutil.NameResolver().resolve_ctrl_async(cancellable, [self._make_tid('tcp', 'localhost')], done)
            loop.run()
        self.assertEqual(result, [[]])
        self.assertFalse([r for r in captured.records if r.levelno >= logging.ERROR])

    def test_ipv4_excluded_when_only_ipv6_allowed(self):
        conf.SvcConf().set_conf_file(self.FNAME_IPV6)
        resolver = gutil.NameResolver()
        t = self._make_tid('tcp', '10.10.10.10')
        result = []
        resolver.resolve_ctrl_async(None, [t], lambda ctrls: result.extend(ctrls))
        self.assertEqual(result, [])


# ==============================================================================
class TestTcpChecker(unittest.TestCase):
    '''Socket errors that only a broken system produces'''

    def test_a_socket_gio_cannot_wrap(self):
        checker = gutil.TcpChecker('127.0.0.1', '8009', '', False, lambda connected: None)
        for failure in ({'side_effect': GLib.Error('injected')}, {'return_value': None}):
            with unittest.mock.patch.object(gutil.Gio.Socket, 'new_from_fd', **failure):
                self.assertRaises(RuntimeError, checker.connect)
            self.assertTrue(checker._native_sock._closed)
        checker.close()

    def test_a_socket_that_fails_to_close(self):
        checker = gutil.TcpChecker('127.0.0.1', '8009', '', False, lambda connected: None)
        gio_sock = unittest.mock.Mock()
        gio_sock.close.side_effect = GLib.Error('injected')
        checker._gio_sock = gio_sock
        with self.assertLogs(level='DEBUG') as captured:
            checker.close()
        self.assertIn('gio_sock.close', captured.output[-1])
        self.assertIsNone(checker._gio_sock)


if __name__ == '__main__':
    unittest.main()
