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
    referral_eflags_value = None

    def referral_eflags(self, tid):
        return TestStaf.referral_eflags_value

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
dc-giveup-timeout=10 seconds
'''

stafd_conf_2 = '''
[Discovery controller connection management]
dc-giveup-timeout=infinity
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
            ('Discovery controller connection management', 'epcsd-poll-interval-minutes'): 15,
            ('Discovery controller connection management', 'dc-giveup-timeout'): timeparse.timeparse('72hours'),
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


class TestPersistence(TestCase):
    '''Unit tests for the EPCSD persistence policy of a discovery controller'''

    EPCSD = 2  # NVMF_DISC_EFLAGS_EPCSD (bit 1; bit 2 is NCC)

    def setUp(self):
        self.setUpPyfakefs()
        self.fs.create_file(
            '/etc/nvme/hostnqn', contents='nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab\n'
        )
        self.fs.create_file('/etc/nvme/hostid', contents='01234567-89ab-cdef-0123-456789abcdef\n')
        self.fs.create_file('/dev/nvme-fabrics', contents='instance=-1,cntlid=-1\n')
        TestStaf.referral_eflags_value = None
        self.addCleanup(setattr, TestStaf, 'referral_eflags_value', None)
        conf.ConnConf.destroy()
        self.addCleanup(conf.ConnConf.destroy)

    def _dc(self, cfg=None, log_pages=None):
        cid = {'transport': 'tcp', 'traddr': '1.1.1.1', 'trsvcid': '8009', 'subsysnqn': 'nqn.unrelated'}
        if cfg:
            cid.update(cfg)
        return TestDc(TestStaf(), tid=trid.TID(cid), log_pages=log_pages)

    def test_mode_defaults_to_auto(self):
        '''libnvme treats an unset value as "no"; a discovery daemon cannot.'''
        self.assertEqual(self._dc().persistence_mode(), 'auto')

    def test_mode_comes_from_the_controller(self):
        self.assertEqual(self._dc(cfg={'persistent': 'force'}).persistence_mode(), 'force')
        self.assertEqual(self._dc(cfg={'persistent': 'no'}).persistence_mode(), 'no')

    def test_an_unknown_mode_falls_back_to_auto(self):
        self.assertEqual(self._dc(cfg={'persistent': 'sometimes'}).persistence_mode(), 'auto')

    def test_epcsd_comes_from_the_self_entry(self):
        dc = self._dc(log_pages=[{'subtype': ctrl.SUBTYPE_SELF, 'eflags': str(TestPersistence.EPCSD)}])
        self.assertTrue(dc.epcsd())

        dc = self._dc(log_pages=[{'subtype': ctrl.SUBTYPE_SELF, 'eflags': '0'}])
        self.assertFalse(dc.epcsd())

    def test_the_self_entry_wins_over_the_parent(self):
        TestStaf.referral_eflags_value = 0
        dc = self._dc(log_pages=[{'subtype': ctrl.SUBTYPE_SELF, 'eflags': str(TestPersistence.EPCSD)}])
        self.assertTrue(dc.epcsd())

    def test_the_parent_answers_when_there_is_no_self_entry(self):
        TestStaf.referral_eflags_value = TestPersistence.EPCSD
        dc = self._dc(log_pages=[{'subtype': ctrl.SUBTYPE_IOC, 'eflags': '0'}])
        self.assertTrue(dc.epcsd())

    def test_a_ddc_is_recognised_by_naming_both_spellings(self):
        """DCTYPE was carved out of a field that defaults to 0, so a legacy DDC
        reports "none" rather than "ddc". Both mean DDC; only a CDC is not one,
        and an unknown future type must not be mistaken for one."""
        dc = self._dc()
        for dctype, expected in (('ddc', True), ('none', True), ('cdc', False), ('something-new', False)):
            dc._ctrl.dctype = dctype
            with self.subTest(dctype=dctype):
                self.assertEqual(dc._is_ddc(), expected)

    def test_only_a_discovery_controller_can_be_parked(self):
        """parked() is asked of every controller when one is removed, so it has
        to answer for I/O controllers too."""
        ioc = TestIoc(TestStaf(), tid=trid.TID({'transport': 'tcp', 'traddr': '1.1.1.1', 'subsysnqn': 'nqn.x'}))
        self.assertFalse(ioc.parked())

    def test_no_self_entry_and_no_parent_means_no(self):
        '''What libnvme's dc_decide() and nvme-discoverd both assume.'''
        self.assertFalse(self._dc().epcsd())


class ParkableDc(TestDc):
    '''A Dc whose disconnect is recorded rather than performed, so parking can
    be tested without a main loop.'''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.disconnects = []

    def disconnect(self, disconnected_cb, keep_connection):
        self.disconnects.append(keep_connection)
        self._connected = False


class RecordingOp:
    """An AsyncTask that records whether it was run instead of running."""

    def __init__(self):
        self.ran = False

    def run_async(self):
        self.ran = True


class TestParking(TestCase):
    '''Unit tests for parking: a discovery controller that does not support a
    persistent connection is disconnected but kept, and polled.'''

    EPCSD = 2

    def setUp(self):
        self.setUpPyfakefs()
        self.fs.create_file(
            '/etc/nvme/hostnqn', contents='nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab\n'
        )
        self.fs.create_file('/etc/nvme/hostid', contents='01234567-89ab-cdef-0123-456789abcdef\n')
        self.fs.create_file('/dev/nvme-fabrics', contents='instance=-1,cntlid=-1\n')
        TestStaf.referral_eflags_value = None
        self.addCleanup(setattr, TestStaf, 'referral_eflags_value', None)
        conf.ConnConf.destroy()
        self.addCleanup(conf.ConnConf.destroy)

    def _dc(self, persistent=None, eflags=0, origin='discovered'):
        cid = {'transport': 'tcp', 'traddr': '1.1.1.1', 'trsvcid': '8009', 'subsysnqn': 'nqn.unrelated'}
        if persistent:
            cid['persistent'] = persistent
        dc = ParkableDc(
            TestStaf(),
            tid=trid.TID(cid),
            log_pages=[{'subtype': ctrl.SUBTYPE_SELF, 'eflags': str(eflags)}],
            origin=origin,
        )
        return dc

    def test_auto_parks_a_dc_without_epcsd(self):
        dc = self._dc(eflags=0)
        dc._apply_persistence_policy()
        self.assertTrue(dc.parked())
        self.assertEqual(dc.disconnects, [False])  # do not keep the connection

    def test_auto_holds_a_dc_with_epcsd(self):
        dc = self._dc(eflags=TestParking.EPCSD)
        dc._apply_persistence_policy()
        self.assertFalse(dc.parked())
        self.assertEqual(dc.disconnects, [])

    def test_force_never_parks(self):
        '''For a DC whose own EPCSD cannot be trusted.'''
        dc = self._dc(persistent='force', eflags=0)
        dc._apply_persistence_policy()
        self.assertFalse(dc.parked())
        self.assertEqual(dc.disconnects, [])

    def test_no_parks_even_with_epcsd(self):
        dc = self._dc(persistent='no', eflags=TestParking.EPCSD)
        dc._apply_persistence_policy()
        self.assertTrue(dc.parked())

    def test_parking_is_not_repeated(self):
        dc = self._dc(eflags=0)
        dc._apply_persistence_policy()
        dc._apply_persistence_policy()
        self.assertEqual(dc.disconnects, [False])

    def test_a_dc_unparks_when_epcsd_appears(self):
        dc = self._dc(eflags=0)
        dc._apply_persistence_policy()
        self.assertTrue(dc.parked())

        dc._log_pages = [{'subtype': ctrl.SUBTYPE_SELF, 'eflags': str(TestParking.EPCSD)}]
        dc._apply_persistence_policy()
        self.assertFalse(dc.parked())

    def test_a_parked_dc_is_not_treated_as_lost(self):
        '''It is disconnected because we disconnected it, not because it went
        away, so the give-up timer must not start counting toward deletion.'''
        dc = self._dc(eflags=0)
        dc._apply_persistence_policy()
        self.assertTrue(dc.parked())

        dc._handle_lost_controller()
        self.assertEqual(dc._ctrl_unresponsive_time, None)

    def test_a_dc_that_really_is_lost_still_counts(self):
        '''The guard must not swallow the case it is guarding against.'''
        dc = self._dc(eflags=TestParking.EPCSD)
        dc._apply_persistence_policy()
        self.assertFalse(dc.parked())

        dc.set_connected(False)
        dc._handle_lost_controller()
        self.assertIsNotNone(dc._ctrl_unresponsive_time)

    def test_a_parked_dc_does_not_resync(self):
        """A parked DC is reached by _on_nvme_event(), when udev reports the
        connection we already tore down, and by reload_hdlr() right after it
        parks. Either way there is nothing connected to talk to, and asking
        only earns a NotConnectedError and a retry timer."""
        dc = self._dc(eflags=0)
        dc._apply_persistence_policy()
        self.assertTrue(dc.parked())

        dc._get_log_op = RecordingOp()
        dc._resync_with_controller()
        self.assertFalse(dc._get_log_op.ran)

    def test_a_connected_dc_still_resyncs(self):
        """The guard must not swallow the case it is guarding against."""
        dc = self._dc(eflags=TestParking.EPCSD)
        dc._apply_persistence_policy()
        self.assertFalse(dc.parked())

        dc._get_log_op = RecordingOp()
        dc._resync_with_controller()
        self.assertTrue(dc._get_log_op.ran)

    def test_a_reload_that_parks_does_not_then_resync(self):
        """reload_hdlr() re-decides persistence and then resyncs, in that
        order. A reload that parks the controller must not turn round and
        talk to it."""
        dc = self._dc(persistent='no', eflags=TestParking.EPCSD)
        dc._get_log_op = RecordingOp()

        dc._apply_persistence_policy()  # what reload_hdlr() does, in order
        dc._resync_with_controller()

        self.assertTrue(dc.parked())
        self.assertFalse(dc._get_log_op.ran)

    def test_get_supported_failure_fetches_the_log_pages_anyway(self):
        """A controller that answers "unrecognized" will not answer differently
        on a second try, and PLEOS is only consulted to decide whether to set
        PLEO. Retrying instead meant never retrieving the log pages at all."""
        dc = self._dc(eflags=0)

        class Op:
            killed = False

            def kill(self):
                Op.killed = True

            def retry(self, _interval):
                raise AssertionError('must not retry')

        with self.assertLogs(level='ERROR'):
            dc._on_get_supported_fail(Op(), 'NvmeError: unrecognized', 1)

        self.assertTrue(Op.killed)
        self.assertIsNone(dc._get_supported_op)
        self.assertIsNotNone(dc._get_log_op)  # went on to fetch the log pages

    def test_a_self_entry_survives_the_address_filter(self):
        """A CDC may report an unusable address; those entries are dropped.
        The controller's own entry is exempt: it is not something we dial, and
        its EFLAGS are where EPCSD comes from."""
        dc = self._dc(eflags=0)
        dc._on_get_log_success(
            None,
            [
                {'subtype': ctrl.SUBTYPE_SELF, 'traddr': '0.0.0.0', 'eflags': str(TestParking.EPCSD)},
                {'subtype': ctrl.SUBTYPE_IOC, 'traddr': '0.0.0.0', 'subnqn': 'nqn.dropped'},
                {'subtype': ctrl.SUBTYPE_IOC, 'traddr': '1.1.1.1', 'subnqn': 'nqn.kept'},
            ],
        )

        subnqns = [page.get('subnqn') for page in dc.log_pages()]
        self.assertIn('nqn.kept', subnqns)
        self.assertNotIn('nqn.dropped', subnqns)  # unusable address, still filtered

        self.assertIsNotNone(dc._self_entry())
        self.assertTrue(dc.epcsd())  # and it is what we read EPCSD from

    def test_the_poll_timer_brings_it_back(self):
        dc = self._dc(eflags=0)
        dc._apply_persistence_policy()
        self.assertTrue(dc.parked())

        dc._on_epcsd_poll_expired()
        self.assertFalse(dc.parked())


if __name__ == '__main__':
    unittest.main()
