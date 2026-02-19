#!/usr/bin/python3
import logging
import unittest
from staslib import conf, ctrl, timeparse, trid
from pyfakefs.fake_filesystem_unittest import TestCase


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

            def connected(this):
                return self._connected

            def disconnect(this):
                pass

        self._ctrl = Ctrl()

    def _find_existing_connection(self):
        pass

    def _on_aen(self, aen: int):
        pass

    def _on_nvme_event(self, nvme_event):
        pass

    def reload_hdlr(self):
        pass

    def set_connected(self, value):
        self._connected = value

    def connected(self):
        return self._connected


class TestStaf:
    def is_avahi_reported(self, tid):
        return False

    def controller_unresponsive(self, tid):
        pass

    @property
    def tron(self):
        return True


stafd_conf_1 = '''
[Global]
tron=false
hdr-digest=false
data-digest=false
kato=30
queue-size=128
reconnect-delay=10
ctrl-loss-tmo=600
disable-sqflow=false
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
                'host-nqn': 'nqn.1988-11.com.dell:poweredge:1234',
            }
        )

        default_conf = {
            ('Global', 'tron'): False,
            ('Global', 'hdr-digest'): False,
            ('Global', 'data-digest'): False,
            ('Global', 'kato'): None,  # None to let the driver decide the default
            ('Global', 'queue-size'): None,  # None to let the driver decide the default
            ('Global', 'reconnect-delay'): None,  # None to let the driver decide the default
            ('Global', 'ctrl-loss-tmo'): None,  # None to let the driver decide the default
            ('Global', 'disable-sqflow'): None,  # None to let the driver decide the default
            ('Discovery controller connection management', 'persistent-connections'): True,
            ('Discovery controller connection management', 'zeroconf-connections-persistence'): timeparse.timeparse(
                '72hours'
            ),
            ('Global', 'ignore-iface'): False,
            ('Global', 'ip-family'): (4, 6),
            ('Global', 'pleo'): True,
            ('Service Discovery', 'zeroconf'): True,
            ('Controllers', 'controller'): list(),
            ('Controllers', 'exclude'): list(),
        }

        self.stafd_conf_file1 = '/etc/stas/stafd1.conf'
        self.fs.create_file(self.stafd_conf_file1, contents=stafd_conf_1)

        self.stafd_conf_file2 = '/etc/stas/stafd2.conf'
        self.fs.create_file(self.stafd_conf_file2, contents=stafd_conf_2)

        self.svcconf = conf.SvcConf(default_conf=default_conf)
        self.svcconf.set_conf_file(self.stafd_conf_file1)

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
                'host-nqn': 'nqn.1988-11.com.dell:poweredge:1234',
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
                'host-nqn': 'nqn.1988-11.com.dell:poweredge:1234',
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
                'host-nqn': 'nqn.1988-11.com.dell:poweredge:1234',
                'subsysnqn': 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8',
                'device': 'nvme?',
                'connect attempts': '1',
                'retry connect timer': '60.0s [off]',
                'hostid': '',
                'hostnqn': '',
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
            captured.records[0]
            .getMessage()
            .startswith(
                "Controller._do_connect()           - (tcp, 10.10.10.10, 8009, nqn.1988-11.com.dell:SFSS:2:20220208134025e8, wlp0s20f3, 1.2.3.4) Connecting to nvme control with cfg={"
            )
        )
        self.assertEqual(controller._connect_attempts, 1)

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


if __name__ == '__main__':
    unittest.main()
