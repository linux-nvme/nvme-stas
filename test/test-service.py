#!/usr/bin/python3
import os
import logging
import unittest
import unittest.mock
from staslib import conf, ctrl, log, service, trid
from pyfakefs.fake_filesystem_unittest import TestCase


class Args:
    def __init__(self):
        self.tron = True
        self.syslog = True
        self.conf_file = '/dev/null'
        self.conn_conf_file = '/dev/null'


class TestService(service.Service):
    def _config_ctrls_finish(self, configured_ctrl_list):
        pass

    def _dump_last_known_config(self, controllers):
        pass

    def _keep_connections_on_exit(self):
        pass

    def _load_last_known_config(self):
        return dict()


class Test(TestCase):
    '''Unit tests for class Service'''

    def setUp(self):
        self.setUpPyfakefs()

        # Service() builds the SvcConf singleton from its default_conf, which
        # only works when we are the ones creating it.
        conf.SvcConf.destroy()  # Make sure singleton does not exist
        self.addCleanup(conf.SvcConf.destroy)

        os.environ['RUNTIME_DIRECTORY'] = "/run"
        self.fs.create_file(
            '/etc/nvme/hostnqn', contents='nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab\n'
        )
        self.fs.create_file('/etc/nvme/hostid', contents='01234567-89ab-cdef-0123-456789abcdef\n')
        self.fs.create_file(
            '/dev/nvme-fabrics',
            contents='instance=-1,cntlid=-1,transport=%s,traddr=%s,trsvcid=%s,nqn=%s,queue_size=%d,nr_io_queues=%d,reconnect_delay=%d,ctrl_loss_tmo=%d,keep_alive_tmo=%d,hostnqn=%s,host_traddr=%s,host_iface=%s,hostid=%s,disable_sqflow,hdr_digest,data_digest,nr_write_queues=%d,nr_poll_queues=%d,tos=%d,fast_io_fail_tmo=%d,discovery,dhchap_secret=%s,dhchap_ctrl_secret=%s\n',
        )

    def test_cannot_instantiate_concrete_classes_if_abstract_method_are_not_implemented(self):
        # Make sure we can't instantiate the ABC directly (Abstract Base Class).
        class Service(service.Service):
            pass

        self.assertRaises(TypeError, lambda: Service(Args(), reload_hdlr=lambda x: x))

    def test_get_controller(self):
        srv = TestService(Args(), default_conf={}, reload_hdlr=lambda x: x)

        self.assertEqual(list(srv.get_controllers()), list())
        self.assertEqual(
            srv.get_controller(
                transport='tcp',
                traddr='10.10.10.10',
                trsvcid='8009',
                subsysnqn='nqn.1988-11.com.dell:SFSS:2:20220208134025e8',
                host_traddr='1.2.3.4',
                host_iface='wlp0s20f3',
                hostnqn='nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab',
            ),
            None,
        )
        self.assertEqual(srv.remove_controller(controller=None, success=True), None)


class FakeController:
    tid = 'fake-tid'
    device = 'nvme?'

    def all_ops_completed(self):
        return False

    def disconnect(self, cb, keep):
        cb(self, True)

    def info(self):
        return {}


class TestCtrlTerminator(unittest.TestCase):
    '''Unit tests for service.CtrlTerminator'''

    def setUp(self):
        log.init(syslog=False)

    def test_ctrl_terminator_pending(self):
        term = service.CtrlTerminator()
        fc = FakeController()
        removed = []
        cb = lambda ctrl, ok: removed.append(ok)

        # Nothing queued yet
        self.assertNotIn('terminator.controller.fake-tid', term.info())

        term.dispose(fc, cb, keep_connection=False)

        # fc has pending operations, so it lands in the garbage disposal
        info = term.info()
        self.assertIn('terminator.audit timer', info)
        self.assertIn('terminator.controller.fake-tid', info)

        # _on_disposal_check() — covers lines 120-121
        # fc.all_ops_completed() returns False → controller stays pending
        result = term._on_disposal_check()
        from gi.repository import GLib
        self.assertEqual(result, GLib.SOURCE_CONTINUE)
        self.assertIn('terminator.controller.fake-tid', term.info())

        # kill() with non-empty _controllers — covers line 111
        term.kill()
        self.assertEqual(removed, [True])


class FakeDc:
    '''Just enough of a discovery controller for referral_eflags().'''

    def __init__(self, tid, referrals):
        self.tid = tid
        self._referrals = referrals

    def referrals(self):
        return self._referrals


class FakeStaf:
    '''Stands in for the service. referral_eflags() reaches for nothing else,
    so the real method can be called against this.'''

    def __init__(self, controllers):
        self._controllers = controllers

    def get_controllers(self):
        return self._controllers


class TestReferralEflags(unittest.TestCase):
    '''Unit tests for Staf.referral_eflags(): what a discovery controller
    published about another one it referred us to.'''

    EPCSD = 2

    HOST_TRADDR = '1.2.3.4'
    HOST_IFACE = 'eth0'
    HOSTNQN = 'nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab'

    @staticmethod
    def _parent(referrals):
        parent_tid = trid.TID(
            {
                'transport': 'tcp',
                'traddr': '1.1.1.1',
                'trsvcid': '8009',
                'subsysnqn': 'nqn.2014-08.org.nvmexpress.discovery',
                'host-traddr': TestReferralEflags.HOST_TRADDR,
                'host-iface': TestReferralEflags.HOST_IFACE,
                'hostnqn': TestReferralEflags.HOSTNQN,
            }
        )
        return FakeDc(parent_tid, referrals)

    @staticmethod
    def _referral_dlpe(traddr, eflags):
        return {
            'subtype': ctrl.SUBTYPE_REFERRAL,
            'trtype': 'tcp',
            'traddr': traddr,
            'trsvcid': '8009',
            'subnqn': 'nqn.2014-08.org.nvmexpress.discovery',
            'eflags': str(eflags),
        }

    @staticmethod
    def _referred_tid(traddr):
        '''The TID the parent's referral entry designates. Spelled out rather
        than built with tid_from_dlpe(), so this does not merely agree with
        itself.'''
        return trid.TID(
            {
                'transport': 'tcp',
                'traddr': traddr,
                'trsvcid': '8009',
                'subsysnqn': 'nqn.2014-08.org.nvmexpress.discovery',
                'host-traddr': TestReferralEflags.HOST_TRADDR,
                'host-iface': TestReferralEflags.HOST_IFACE,
                'hostnqn': TestReferralEflags.HOSTNQN,
            }
        )

    def _lookup(self, controllers, tid):
        return service.Staf.referral_eflags(FakeStaf(controllers), tid)

    def test_finds_what_the_parent_published(self):
        parent = self._parent([self._referral_dlpe('2.2.2.2', TestReferralEflags.EPCSD)])
        self.assertEqual(self._lookup([parent], self._referred_tid('2.2.2.2')), TestReferralEflags.EPCSD)

    def test_zero_is_an_answer_not_an_absence(self):
        '''A parent saying "no EPCSD" must be distinguishable from no parent
        at all: the caller falls back only on None.'''
        parent = self._parent([self._referral_dlpe('2.2.2.2', 0)])
        self.assertEqual(self._lookup([parent], self._referred_tid('2.2.2.2')), 0)

    def test_none_when_nobody_refers_to_it(self):
        parent = self._parent([self._referral_dlpe('2.2.2.2', TestReferralEflags.EPCSD)])
        self.assertIsNone(self._lookup([parent], self._referred_tid('9.9.9.9')))

    def test_none_when_there_are_no_controllers(self):
        self.assertIsNone(self._lookup([], self._referred_tid('2.2.2.2')))

    def test_searches_every_controller(self):
        quiet = self._parent([])
        talkative = self._parent([self._referral_dlpe('3.3.3.3', TestReferralEflags.EPCSD)])
        self.assertEqual(
            self._lookup([quiet, talkative], self._referred_tid('3.3.3.3')), TestReferralEflags.EPCSD
        )


class TestDefaultConf(unittest.TestCase):
    '''SvcConf builds its valid-option set from the daemon's DEFAULT_CONF, not
    from OPTION_CHECKER, so an option missing there is rejected as invalid no
    matter how well OPTION_CHECKER knows it. These pin that both ways.'''

    DAEMONS = (('stafd', service.Staf), ('stacd', service.Stac))

    def test_every_default_is_a_known_option(self):
        '''A typo in DEFAULT_CONF would otherwise sit there unnoticed.'''
        for name, daemon in TestDefaultConf.DAEMONS:
            for section, option in daemon.DEFAULT_CONF:
                with self.subTest(daemon=name, section=section, option=option):
                    self.assertIn(section, conf.SvcConf.OPTION_CHECKER)
                    self.assertIn(option, conf.SvcConf.OPTION_CHECKER[section])

    def test_each_daemon_accepts_its_whole_section(self):
        '''The section that belongs to a daemon must be listed in full. This is
        what catches an option added to OPTION_CHECKER and to the shipped .conf
        file, but forgotten here - the daemon would reject it as invalid.'''
        owned = {
            'stafd': 'Discovery controller connection management',
            'stacd': 'I/O controller connection management',
        }
        for name, daemon in TestDefaultConf.DAEMONS:
            section = owned[name]
            declared = {opt for sect, opt in daemon.DEFAULT_CONF if sect == section}
            with self.subTest(daemon=name, section=section):
                self.assertEqual(declared, set(conf.SvcConf.OPTION_CHECKER[section]))

    def test_the_common_sections_are_covered(self):
        '''Both daemons read [Global] tron and [Controllers] exclude.'''
        for name, daemon in TestDefaultConf.DAEMONS:
            with self.subTest(daemon=name):
                self.assertIn(('Global', 'tron'), daemon.DEFAULT_CONF)
                self.assertIn(('Controllers', 'exclude'), daemon.DEFAULT_CONF)


class TestStacReconcileWithoutStafd(unittest.TestCase):
    '''stacd learns about I/O controllers from stafd and from nowhere else. When
    stafd cannot be reached, an I/O controller missing from the discovery log
    pages is missing because nobody told us about it, not because it went away.
    These pin that stacd tells the two apart.'''

    TID = trid.TID(
        {
            'transport': 'tcp',
            'traddr': '10.10.10.10',
            'trsvcid': '4420',
            'subsysnqn': 'nqn.1988-11.com.dell:PowerSANxxx:01:20210225100113-454f73093ceb4847a7bdfc6e34ae8e28',
        }
    )

    def setUp(self):
        conf.SvcConf.destroy()  # Make sure singleton does not exist
        self.addCleanup(conf.SvcConf.destroy)
        conf.SvcConf(default_conf=service.Stac.DEFAULT_CONF)

    def _make_stac(self, log_pages):
        '''Build the smallest object _config_ctrls_finish() will run against, holding
        one I/O controller and told to expect @log_pages back from stafd.'''
        stac = unittest.mock.Mock()  # No spec: _udev and friends are instance attributes
        stac._alive = lambda: True
        stac._get_log_pages_from_stafd = lambda: log_pages
        stac._udev.find_nvme_ioc_device = lambda tid: None
        stac._controllers = {TestStacReconcileWithoutStafd.TID: unittest.mock.Mock()}
        return stac

    def test_no_controller_is_removed_when_stafd_is_unreachable(self):
        '''None means "we were told nothing", so nothing may be disconnected.'''
        stac = self._make_stac(None)

        service.Stac._config_ctrls_finish(stac, list())

        stac._terminator.dispose.assert_not_called()
        self.assertIn(TestStacReconcileWithoutStafd.TID, stac._controllers)

    def test_a_controller_is_removed_when_stafd_reports_nothing(self):
        '''An empty list means "nothing is discovered", which we can act on.'''
        stac = self._make_stac(list())

        service.Stac._config_ctrls_finish(stac, list())

        stac._terminator.dispose.assert_called_once()
        self.assertNotIn(TestStacReconcileWithoutStafd.TID, stac._controllers)


if __name__ == '__main__':
    unittest.main()
