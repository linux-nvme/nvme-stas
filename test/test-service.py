#!/usr/bin/python3
import os
import unittest
from staslib import service
from pyfakefs.fake_filesystem_unittest import TestCase


class Args:
    def __init__(self):
        self.tron = True
        self.syslog = True
        self.conf_file = '/dev/null'


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

        os.environ['RUNTIME_DIRECTORY'] = "/run"
        self.fs.create_file(
            '/etc/nvme/hostnqn', contents='nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab\n'
        )
        self.fs.create_file('/etc/nvme/hostid', contents='01234567-89ab-cdef-0123-456789abcdef\n')
        self.fs.create_file(
            '/dev/nvme-fabrics',
            contents='instance=-1,cntlid=-1,transport=%s,traddr=%s,trsvcid=%s,nqn=%s,queue_size=%d,nr_io_queues=%d,reconnect_delay=%d,ctrl_loss_tmo=%d,keep_alive_tmo=%d,hostnqn=%s,host_traddr=%s,host_iface=%s,hostid=%s,duplicate_connect,disable_sqflow,hdr_digest,data_digest,nr_write_queues=%d,nr_poll_queues=%d,tos=%d,fast_io_fail_tmo=%d,discovery,dhchap_secret=%s,dhchap_ctrl_secret=%s\n',
        )

    def test_cannot_instantiate_concrete_classes_if_abstract_method_are_not_implemented(self):
        # Make sure we can't instantiate the ABC directly (Abstract Base Class).
        class Service(service.Service):
            pass

        self.assertRaises(TypeError, lambda: Service(Args(), reload_hdlr=lambda x: x))

    def test_get_controller(self):
        srv = TestService(Args(), reload_hdlr=lambda x: x)

        self.assertEqual(list(srv.get_controllers()), list())
        self.assertEqual(
            srv.get_controller(
                transport='tcp',
                traddr='10.10.10.10',
                trsvcid='8009',
                host_traddr='1.2.3.4',
                host_iface='wlp0s20f3',
                subsysnqn='nqn.1988-11.com.dell:SFSS:2:20220208134025e8',
            ),
            None,
        )
        self.assertEqual(srv.remove_controller(controller=None, success=True), None)


if __name__ == '__main__':
    unittest.main()
