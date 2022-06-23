#!/usr/bin/python3
import logging
import unittest
from staslib import ctrl, stas, trid
from pyfakefs.fake_filesystem_unittest import TestCase

class Test(TestCase):
    '''Unit tests for class Controller'''

    def setUp(self):
        self.setUpPyfakefs()

        self.fs.create_file('/etc/nvme/hostnqn', contents='nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab\n')
        self.fs.create_file('/etc/nvme/hostid',  contents='01234567-89ab-cdef-0123-456789abcdef\n')
        self.fs.create_file('/dev/nvme-fabrics', contents='instance=-1,cntlid=-1,transport=%s,traddr=%s,trsvcid=%s,nqn=%s,queue_size=%d,nr_io_queues=%d,reconnect_delay=%d,ctrl_loss_tmo=%d,keep_alive_tmo=%d,hostnqn=%s,host_traddr=%s,host_iface=%s,hostid=%s,duplicate_connect,disable_sqflow,hdr_digest,data_digest,nr_write_queues=%d,nr_poll_queues=%d,tos=%d,fast_io_fail_tmo=%d,discovery,dhchap_secret=%s,dhchap_ctrl_secret=%s\n')

        self.NVME_TID = trid.TID({
            'transport':   'tcp',
            'traddr':      '10.10.10.10',
            'subsysnqn':   'nqn.1988-11.com.dell:SFSS:2:20220208134025e8',
            'trsvcid':     '8009',
            'host-traddr': '1.2.3.4',
            'host-iface':  'wlp0s20f3',
        })

    def test_get_device(self):
        controller = ctrl.Controller(root=stas.Nvme().root, host=stas.Nvme().host, tid=self.NVME_TID)
        self.assertEqual(controller._connect_attempts, 0)
        self.assertRaises(NotImplementedError, controller._try_to_connect)
        self.assertEqual(controller._connect_attempts, 1)
        self.assertRaises(NotImplementedError, controller._find_existing_connection)
        self.assertEqual(controller.id, "(tcp, 10.10.10.10, 8009, nqn.1988-11.com.dell:SFSS:2:20220208134025e8, wlp0s20f3, 1.2.3.4)")
        # raise Exception(controller._connect_op)
        self.assertEqual(str(controller.tid), "(tcp, 10.10.10.10, 8009, nqn.1988-11.com.dell:SFSS:2:20220208134025e8, wlp0s20f3, 1.2.3.4)")
        self.assertEqual(controller.device, '')
        self.assertEqual(str(controller.controller_id_dict()), "{'transport': 'tcp', 'traddr': '10.10.10.10', 'trsvcid': '8009', 'host-traddr': '1.2.3.4', 'host-iface': 'wlp0s20f3', 'subsysnqn': 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8', 'device': ''}")
        # self.assertEqual(controller.details(), "{'transport': 'tcp', 'traddr': '10.10.10.[265 chars]ff]'}")
        self.assertEqual(controller.info(), {'transport': 'tcp', 'traddr': '10.10.10.10', 'trsvcid': '8009', 'host-traddr': '1.2.3.4', 'host-iface': 'wlp0s20f3', 'subsysnqn': 'nqn.1988-11.com.dell:SFSS:2:20220208134025e8', 'device': '', 'hostid': '', 'hostnqn': '', 'model': '', 'serial': '', 'connect attempts': '1', 'retry connect timer': '60.0s [off]'})
        # print(controller._connect_op)
        self.assertEqual(controller.cancel(), None)
        self.assertEqual(controller.kill(), None)
        # self.assertEqual(controller.disconnect(), 0)

    def test_connect(self):
        controller = ctrl.Controller(root=stas.Nvme().root, host=stas.Nvme().host, tid=self.NVME_TID)
        self.assertEqual(controller._connect_attempts, 0)
        controller._find_existing_connection = lambda : None
        with self.assertLogs(logger=logging.getLogger(), level='DEBUG') as captured:
            controller._try_to_connect()
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].getMessage(), "Controller._try_to_connect()       - (tcp, 10.10.10.10, 8009, nqn.1988-11.com.dell:SFSS:2:20220208134025e8, wlp0s20f3, 1.2.3.4) Connecting to nvme control with cfg={'hdr_digest': False, 'data_digest': False}")
        self.assertEqual(controller._connect_attempts, 1)


if __name__ == '__main__':
    unittest.main()
