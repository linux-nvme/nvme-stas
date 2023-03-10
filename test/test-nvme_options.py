#!/usr/bin/python3
import os
import logging
import unittest
from staslib import conf, log
from pyfakefs.fake_filesystem_unittest import TestCase


class Test(TestCase):
    """Unit tests for class NvmeOptions"""

    def setUp(self):
        self.setUpPyfakefs()
        log.init(syslog=False)
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.INFO)

    def tearDown(self):
        # No longer need self.tearDownPyfakefs()
        pass

    def test_fabrics_empty_file(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        # TODO: this is a bug
        self.fs.create_file("/dev/nvme-fabrics")
        self.assertTrue(os.path.exists('/dev/nvme-fabrics'))
        nvme_options = conf.NvmeOptions()
        self.assertIsInstance(nvme_options.discovery_supp, bool)
        self.assertIsInstance(nvme_options.host_iface_supp, bool)
        del nvme_options

    def test_fabrics_wrong_file(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        self.fs.create_file("/dev/nvme-fabrics", contents="blah")
        self.assertTrue(os.path.exists('/dev/nvme-fabrics'))
        nvme_options = conf.NvmeOptions()
        self.assertIsInstance(nvme_options.discovery_supp, bool)
        self.assertIsInstance(nvme_options.host_iface_supp, bool)
        del nvme_options

    def test_fabrics_correct_file(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        self.fs.create_file('/dev/nvme-fabrics', contents='host_iface=%s,discovery,dhchap_secret=%s\n')
        self.assertTrue(os.path.exists('/dev/nvme-fabrics'))
        nvme_options = conf.NvmeOptions()
        self.assertTrue(nvme_options.discovery_supp)
        self.assertTrue(nvme_options.host_iface_supp)
        self.assertTrue(nvme_options.dhchap_secret_supp)
        self.assertEqual(nvme_options.get(), {'discovery': True, 'host_iface': True, 'dhchap_secret': True})
        self.assertEqual(
            str(nvme_options), "supported options: {'discovery': True, 'host_iface': True, 'dhchap_secret': True}"
        )
        del nvme_options


if __name__ == "__main__":
    unittest.main()
