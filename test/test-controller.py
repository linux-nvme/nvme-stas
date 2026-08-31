#!/usr/bin/python3
import logging
import unittest
from libnvme3 import nvme
from staslib import conf, ctrl, timeparse, trid
from pyfakefs.fake_filesystem_unittest import TestCase


class MockOp:
    def kill(self):
        pass

    def retry(self, delay):
        pass


class TestController(ctrl.Controller):
    def _find_existing_connection(self):
        pass

    def _on_aen(self, aen: int):
        pass

    def _on_nvme_event(self, nvme_event):
        pass

    def reload_hdlr(self):
        pass


class TestDc(ctrl.Dc):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connected = True

        class Ctrl:
            def __init__(this):
                this.name = 'nvme666'
                this.dctype = 'none'

            @property
            def connected(this):
                return self._connected

            def disconnect(this):
                pass

            def discover(this, lsp=0):
                return []

        self._ctrl = Ctrl()

    def _find_existing_connection(self):
        pass

    def _on_aen(self, aen: int):
        pass

    def _on_nvme_event(self, nvme_event):
        pass

    def reload_hdlr(self):
        pass

    def _post_registration_actions(self):
        pass  # no-op: avoids starting async ops inside registration callback tests

    def set_connected(self, value):
        self._connected = value

    def connected(self):
        return self._connected


class TestStaf:
    def is_avahi_reported(self, tid):
        return False

    def controller_unresponsive(self, tid):
        pass

    def log_pages_changed(self, controller, device):
        pass

    def referrals_changed(self):
        pass

    @property
    def tron(self):
        return True


class TestStac:
    @property
    def tron(self):
        return True


class TestIoc(ctrl.Ioc):
    def _find_existing_connection(self):
        return None


stafd_conf_1 = '''
[Global]
tron=false
ignore-iface=false
ip-family=ipv4+ipv6
pleo=enabled

[Service Discovery]
zeroconf=enabled

[Discovery controller connection management]
persistent-connections=true
zeroconf-connections-persistence=10 seconds
'''

stafd_conf_2 = '''
[Discovery controller connection management]
zeroconf-connections-persistence=-1
'''

stafd_conf_3 = '''
[Controllers]
exclude=transport=tcp;traddr=10.10.10.10
'''


class Test(TestCase):
    '''Unit tests for class Controller'''

    def setUp(self):
        self.setUpPyfakefs()

        self.fs.create_file(
            '/etc/nvme/hostnqn', contents='nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab\n'
        )
        self.fs.create_file('/etc/nvme/hostid', contents='01234567-89ab-cdef-0123-456789abcdef\n')
        self.fs.create_file(
            '/dev/nvme-fabrics',
            contents='instance=-1,cntlid=-1,transport=%s,traddr=%s,trsvcid=%s,nqn=%s,queue_size=%d,nr_io_queues=%d,reconnect_delay=%d,ctrl_loss_tmo=%d,keep_alive_tmo=%d,hostnqn=%s,host_traddr=%s,host_iface=%s,hostid=%s,disable_sqflow,hdr_digest,data_digest,nr_write_queues=%d,nr_poll_queues=%d,tos=%d,fast_io_fail_tmo=%d,discovery,dhchap_secret=%s,dhchap_ctrl_secret=%s\n',
        )

        self.NVME_TID = trid.TID(
            {
                'transport': 'tcp',
                'traddr': '10.10.10.10',
                'subsysnqn': 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8',
                'trsvcid': '8009',
                'host-traddr': '1.2.3.4',
                'host-iface': 'wlp0s20f3',
                'hostnqn': 'nqn.1988-11.com.dell:poweredge:1234',
                'hostid': '12345678-9abc-def0-1234-56789abcdef0',
            }
        )

        default_conf = {
            ('Global', 'tron'): False,
            ('Discovery controller connection management', 'persistent-connections'): True,
            ('Discovery controller connection management', 'zeroconf-connections-persistence'): timeparse.timeparse(
                '72hours'
            ),
            ('Global', 'ignore-iface'): False,
            ('Global', 'ip-family'): (4, 6),
            ('Global', 'pleo'): True,
            ('Service Discovery', 'zeroconf'): True,
            ('Controllers', 'exclude'): list(),
        }

        self.stafd_conf_file1 = '/etc/nvme/stafd1.conf'
        self.fs.create_file(self.stafd_conf_file1, contents=stafd_conf_1)

        self.stafd_conf_file2 = '/etc/nvme/stafd2.conf'
        self.fs.create_file(self.stafd_conf_file2, contents=stafd_conf_2)

        self.stafd_conf_file3 = '/etc/nvme/stafd3.conf'
        self.fs.create_file(self.stafd_conf_file3, contents=stafd_conf_3)

        conf.SvcConf.destroy()  # Make sure singleton does not exist
        self.addCleanup(conf.SvcConf.destroy)
        self.svcconf = conf.SvcConf(default_conf=default_conf)
        self.svcconf.set_conf_file(self.stafd_conf_file1)

    def test_identity_defaults_to_the_system_one(self):
        sysconf = conf.SysConf()
        conn_conf = conf.ConnConf()
        tid = trid.TID({'transport': 'tcp', 'traddr': '1.1.1.1', 'subsysnqn': 'nqn.unrelated'})
        self.assertEqual(
            ctrl.host_identity(tid, sysconf, conn_conf),
            (sysconf.hostnqn, sysconf.hostid, conn_conf.hostsymname),
        )

    def test_a_named_identity_is_taken_whole(self):
        '''A connection that names its own host NQN is a persona. It must not
        borrow the system host ID: that would make the subsystem treat the two
        as the same host.'''
        sysconf = conf.SysConf()
        tid = trid.TID(
            {
                'transport': 'tcp',
                'traddr': '1.1.1.1',
                'subsysnqn': 'nqn.unrelated',
                'hostnqn': 'nqn.1988-11.com.dell:persona:1',
                'hostid': 'aaaaaaaa-0000-0000-0000-000000000001',
                'hostsymname': 'persona-1',
            }
        )
        self.assertEqual(
            ctrl.host_identity(tid, sysconf, conf.ConnConf()),
            ('nqn.1988-11.com.dell:persona:1', 'aaaaaaaa-0000-0000-0000-000000000001', 'persona-1'),
        )

    def test_a_named_identity_never_borrows_the_system_host_id(self):
        sysconf = conf.SysConf()
        tid = trid.TID(
            {
                'transport': 'tcp',
                'traddr': '1.1.1.1',
                'subsysnqn': 'nqn.unrelated',
                'hostnqn': 'nqn.1988-11.com.dell:persona:2',
            }
        )
        _, hostid, _ = ctrl.host_identity(tid, sysconf, conf.ConnConf())
        self.assertIsNone(hostid)
        self.assertNotEqual(hostid, sysconf.hostid)

    def test_the_symbolic_name_alone_does_not_make_a_persona(self):
        '''hostsymname does not discriminate identity, so naming one keeps the
        system host NQN and host ID.'''
        sysconf = conf.SysConf()
        tid = trid.TID(
            {
                'transport': 'tcp',
                'traddr': '1.1.1.1',
                'subsysnqn': 'nqn.unrelated',
                'hostsymname': 'just-a-name',
            }
        )
        self.assertEqual(
            ctrl.host_identity(tid, sysconf, conf.ConnConf()),
            (sysconf.hostnqn, sysconf.hostid, 'just-a-name'),
        )

    def tearDown(self):
        pass

    def test_cannot_instantiate_concrete_classes_if_abstract_method_are_not_implemented(self):
        # Make sure we can't instantiate the ABC directly (Abstract Base Class).
        class Controller(ctrl.Controller):
            pass

        self.assertRaises(TypeError, lambda: ctrl.Controller(tid=self.NVME_TID))

    def test_get_device(self):
        controller = TestController(tid=self.NVME_TID, service=TestStaf())
        self.assertEqual(controller._connect_attempts, 0)
        controller._try_to_connect()
        self.assertEqual(controller._connect_attempts, 1)
        self.assertEqual(
            controller.id, "(tcp, 10.10.10.10, 8009, nqn.1988-11.com.dell:SFSS:2:20220208134025e8, wlp0s20f3, 1.2.3.4)"
        )
        # raise Exception(controller._connect_op)
        self.assertEqual(
            str(controller.tid),
            "(tcp, 10.10.10.10, 8009, nqn.1988-11.com.dell:SFSS:2:20220208134025e8, wlp0s20f3, 1.2.3.4)",
        )
        self.assertEqual(controller.device, 'nvme?')
        self.assertEqual(
            controller.controller_id_dict(),
            {
                'transport': 'tcp',
                'traddr': '10.10.10.10',
                'trsvcid': '8009',
                'host-traddr': '1.2.3.4',
                'host-iface': 'wlp0s20f3',
                'subsysnqn': 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8',
                'device': 'nvme?',
                'hostnqn': 'nqn.1988-11.com.dell:poweredge:1234',
                'hostid': '12345678-9abc-def0-1234-56789abcdef0',
            },
        )

        self.assertEqual(
            controller.info(),
            {
                'transport': 'tcp',
                'traddr': '10.10.10.10',
                'subsysnqn': 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8',
                'trsvcid': '8009',
                'host-traddr': '1.2.3.4',
                'host-iface': 'wlp0s20f3',
                'hostnqn': 'nqn.1988-11.com.dell:poweredge:1234',
                'hostid': '12345678-9abc-def0-1234-56789abcdef0',
                'device': 'nvme?',
                'connect attempts': '1',
                'retry connect timer': '60.0s [off]',
                'connect operation': "{'fail count': 0, 'completed': False, 'alive': True}",
            },
        )
        self.assertEqual(
            controller.details(),
            {
                'dctype': '',
                'cntrltype': '',
                'connected': 'False',
                'transport': 'tcp',
                'traddr': '10.10.10.10',
                'trsvcid': '8009',
                'host-traddr': '1.2.3.4',
                'host-iface': 'wlp0s20f3',
                'hostnqn': 'nqn.1988-11.com.dell:poweredge:1234',
                'hostid': '12345678-9abc-def0-1234-56789abcdef0',
                'subsysnqn': 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8',
                'device': 'nvme?',
                'connect attempts': '1',
                'retry connect timer': '60.0s [off]',
                'hostid': '',
                'model': '',
                'serial': '',
                'connect operation': "{'fail count': 0, 'completed': False, 'alive': True}",
            },
        )

        # print(controller._connect_op)
        self.assertEqual(controller.cancel(), None)
        self.assertEqual(controller.kill(), None)
        self.assertIsNone(controller.disconnect(lambda *args: None, True))

    def test_connect(self):
        controller = TestController(tid=self.NVME_TID, service=TestStaf())
        self.assertEqual(controller._connect_attempts, 0)
        controller._find_existing_connection = lambda: None
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG') as captured:
            controller._try_to_connect()
        self.assertTrue(len(captured.records) > 0)
        self.assertTrue(
            any(
                record.getMessage().startswith(
                    "Controller._do_connect()           - (tcp, 10.10.10.10, 8009, nqn.1988-11.com.dell:SFSS:2:20220208134025e8, wlp0s20f3, 1.2.3.4) Connecting to nvme control with cfg={"
                )
                for record in captured.records
            )
        )
        self.assertEqual(controller._connect_attempts, 1)

    def test_excluded_controller_does_not_connect(self):
        '''A controller that gets excluded while the daemon is running must not
        be reconnected by the retry timer'''
        controller = TestController(tid=self.NVME_TID, service=TestStaf())
        controller._find_existing_connection = lambda: None
        controller._try_to_connect()
        self.assertEqual(controller._connect_attempts, 1)

        # Exclude the controller and make sure no new attempt is made
        self.svcconf.set_conf_file(self.stafd_conf_file3)
        with self.assertLogs(logger=logging.getLogger(), level='INFO') as captured:
            controller._try_to_connect()
        self.assertTrue(captured.records[0].getMessage().endswith('Controller is excluded. Do not connect.'))
        self.assertEqual(controller._connect_attempts, 1)

        controller.kill()

    def test_dlp_supp_opts_as_string(self):
        dlp_supp_opts = 0x7
        opts = ctrl.dlp_supp_opts_as_string(dlp_supp_opts)
        self.assertEqual(['EXTDLPES', 'PLEOS', 'ALLSUBES'], opts)

    def test_ncc(self):
        dlpe = {'eflags': '4'}
        ncc = ctrl.get_ncc(ctrl.get_eflags(dlpe))
        self.assertTrue(ncc)

        dlpe = {}
        ncc = ctrl.get_ncc(ctrl.get_eflags(dlpe))
        self.assertFalse(ncc)

    def test_dc(self):
        self.svcconf.set_conf_file(self.stafd_conf_file1)

        controller = TestDc(TestStaf(), tid=self.NVME_TID)
        controller.set_connected(True)
        controller.origin = 'discovered'

        with self.assertLogs(logger=logging.getLogger(), level='DEBUG') as captured:
            controller.origin = 'blah'
            self.assertEqual(len(captured.records), 1)
            self.assertNotEqual(-1, captured.records[0].getMessage().find("Trying to set invalid origin to blah"))

        controller.set_connected(False)
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG') as captured:
            controller.origin = 'discovered'
            self.assertEqual(len(captured.records), 1)
            self.assertNotEqual(
                -1, captured.records[0].getMessage().find("Controller is not responding. Will be removed by")
            )

        self.svcconf.set_conf_file(self.stafd_conf_file2)
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG') as captured:
            controller.origin = 'discovered'
            self.assertEqual(len(captured.records), 1)
            self.assertNotEqual(-1, captured.records[0].getMessage().find("Controller not responding. Retrying..."))

        controller.set_connected(True)
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG') as captured:
            controller.disconnect(lambda *args: None, keep_connection=False)
            self.assertEqual(len(captured.records), 2)
            self.assertNotEqual(-1, captured.records[0].getMessage().find("nvme666: keep_connection=False"))
            self.assertNotEqual(-1, captured.records[1].getMessage().find("nvme666 - Disconnect initiated"))

    def test_disconnect(self):
        '''Test the fast-path (no async operation) cases of disconnect()'''
        self.svcconf.set_conf_file(self.stafd_conf_file1)
        controller = TestDc(TestStaf(), tid=self.NVME_TID)

        # keep_connection=True → no async disconnect even when the ctrl IS connected
        controller.set_connected(True)
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG') as captured:
            controller.disconnect(lambda *args: None, keep_connection=True)
        self.assertEqual(len(captured.records), 1)
        self.assertIn('keep_connection=True', captured.records[0].getMessage())
        # "Disconnect initiated" must NOT appear when keep_connection=True
        self.assertNotIn('Disconnect initiated', captured.records[0].getMessage())

        # keep_connection=False but ctrl is NOT connected → no async disconnect either
        controller.set_connected(False)
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG') as captured:
            controller.disconnect(lambda *args: None, keep_connection=False)
        self.assertEqual(len(captured.records), 1)
        self.assertIn('keep_connection=False', captured.records[0].getMessage())
        self.assertNotIn('Disconnect initiated', captured.records[0].getMessage())


    def test_dc_registration_callbacks(self):
        op = MockOp()
        dc = TestDc(TestStaf(), tid=self.NVME_TID)

        # _on_registration_success: data=None → DC accepted, logs debug
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG'):
            dc._on_registration_success(op, None)

        # _on_registration_success: data='error' → DC returned an error, logs warning
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG'):
            dc._on_registration_success(op, 'some DC error')

        class FakeErr:
            domain = 'nvme'
            message = 'timeout'

            def __str__(self):
                return 'timeout'

        # _on_registration_fail: fail_cnt=1 → logs error + schedules retry
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG'):
            dc._on_registration_fail(op, FakeErr(), 1)

        # _on_registration_fail: fail_cnt=2 → throttled (no extra error log)
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG'):
            dc._on_registration_fail(op, FakeErr(), 2)

    def test_dc_log_page_callbacks(self):
        op = MockOp()
        dc = TestDc(TestStaf(), tid=self.NVME_TID)

        # _on_get_supported_success: creates AsyncTask with dc._ctrl.discover and runs it
        data = {nvme.NVME_LOG_LID_DISCOVERY: nvme.NVMF_LOG_DISC_LID_PLEOS << 16}
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG'):
            dc._on_get_supported_success(op, data)
        self.assertIsNotNone(dc._get_log_op)

        # _on_get_log_fail: fail_cnt=1 → logs error + schedules retry
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG'):
            dc._on_get_log_fail(op, Exception('timeout'), 1)

        # _on_get_log_fail: fail_cnt=2 → throttled
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG'):
            dc._on_get_log_fail(op, Exception('timeout'), 2)

    def test_disconn_callbacks(self):
        op = MockOp()
        dc = TestDc(TestStaf(), tid=self.NVME_TID)
        results = []
        cb = lambda controller, ok: results.append(ok)

        with self.assertLogs(logger=logging.getLogger(), level='DEBUG'):
            dc._on_disconn_success(op, None, cb)

        with self.assertLogs(logger=logging.getLogger(), level='DEBUG'):
            dc._on_disconn_fail(op, Exception('err'), 1, cb)

    def test_ioc_remaining(self):
        ioc = TestIoc(TestStac(), self.NVME_TID)

        # reload_hdlr: not connected + timer not running → schedules deferred connect
        ioc.reload_hdlr()

        # update_dlpe: NCC bit was clear, stays clear → no reconnect scheduled
        ioc._dlpe = {'eflags': '0'}
        ioc.update_dlpe({'eflags': '0'})
        self.assertFalse(ioc.ncc)

        # update_dlpe: NCC was set, now cleared → connect attempt reset and scheduled
        ioc._dlpe = {'eflags': '4'}
        self.assertTrue(ioc.ncc)
        ioc.update_dlpe({'eflags': '0'})
        self.assertFalse(ioc.ncc)
        self.assertEqual(ioc._connect_attempts, 0)

        # _should_try_to_reconnect: ncc=False → max_connect_attempts=0 → always True
        self.assertTrue(ioc._should_try_to_reconnect())


if __name__ == '__main__':
    unittest.main()
