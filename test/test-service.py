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


class Test(TestCase):
    '''Unit tests for class Service'''

    def setUp(self):
        self.setUpPyfakefs()

        os.environ['RUNTIME_DIRECTORY'] = "/run"
        self.fs.create_file('/etc/nvme/hostnqn', contents='nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab\n')
        self.fs.create_file('/etc/nvme/hostid',  contents='01234567-89ab-cdef-0123-456789abcdef\n')
        self.fs.create_file('/dev/nvme-fabrics', contents='instance=-1,cntlid=-1,transport=%s,traddr=%s,trsvcid=%s,nqn=%s,queue_size=%d,nr_io_queues=%d,reconnect_delay=%d,ctrl_loss_tmo=%d,keep_alive_tmo=%d,hostnqn=%s,host_traddr=%s,host_iface=%s,hostid=%s,duplicate_connect,disable_sqflow,hdr_digest,data_digest,nr_write_queues=%d,nr_poll_queues=%d,tos=%d,fast_io_fail_tmo=%d,discovery,dhchap_secret=%s,dhchap_ctrl_secret=%s\n')

    def test_get_controller(self):
        # FIXME: this is hack, fix it later
        service.Service._load_last_known_config = lambda x : dict()
        # start the test

        srv = service.Service(Args(), reload_hdlr=lambda x : x)
        self.assertRaises(NotImplementedError, srv._keep_connections_on_exit)
        self.assertRaises(NotImplementedError, srv._dump_last_known_config, [])
        self.assertRaises(NotImplementedError, srv._on_config_ctrls)
        #self.assertEqual(srv.get_controllers(), dict())
        self.assertEqual(srv.get_controller(transport='tcp', traddr='10.10.10.10', trsvcid='8009', host_traddr='1.2.3.4', host_iface='wlp0s20f3', subsysnqn='nqn.1988-11.com.dell:SFSS:2:20220208134025e8'), None)
        self.assertEqual(srv.remove_controller(controller=None), None)

if __name__ == '__main__':
    unittest.main()
