#!/usr/bin/python3
import os
import logging
import unittest
from staslib import defs, conf, log
from pyfakefs.fake_filesystem_unittest import TestCase


class TestStandardNvmeFabricsFile(unittest.TestCase):
    def test_regular_user(self):
        conf.NvmeOptions.destroy()  # Make sure singleton does not exist
        if os.path.exists('/dev/nvme-fabrics'):
            if os.geteuid() != 0 and defs.KERNEL_VERSION < defs.KERNEL_ALL_MIN_VERSION:
                with self.assertRaises(PermissionError):
                    nvme_options = conf.NvmeOptions()
            else:
                nvme_options = conf.NvmeOptions()
                self.assertIsInstance(nvme_options.discovery_supp, bool)
                self.assertIsInstance(nvme_options.host_iface_supp, bool)


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

    def test_file_missing(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        conf.NvmeOptions.destroy()  # Make sure singleton does not exist
        nvme_options = conf.NvmeOptions()
        self.assertIsInstance(nvme_options.discovery_supp, bool)
        self.assertIsInstance(nvme_options.host_iface_supp, bool)

    def test_fabrics_empty_file(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        self.fs.create_file("/dev/nvme-fabrics")
        self.assertTrue(os.path.exists('/dev/nvme-fabrics'))
        conf.NvmeOptions.destroy()  # Make sure singleton does not exist
        nvme_options = conf.NvmeOptions()
        self.assertIsInstance(nvme_options.discovery_supp, bool)
        self.assertIsInstance(nvme_options.host_iface_supp, bool)

    def test_fabrics_wrong_file(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        self.fs.create_file("/dev/nvme-fabrics", contents="blah")
        self.assertTrue(os.path.exists('/dev/nvme-fabrics'))
        conf.NvmeOptions.destroy()  # Make sure singleton does not exist
        nvme_options = conf.NvmeOptions()
        self.assertIsInstance(nvme_options.discovery_supp, bool)
        self.assertIsInstance(nvme_options.host_iface_supp, bool)

    def test_fabrics_correct_file(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        self.fs.create_file(
            '/dev/nvme-fabrics', contents='host_iface=%s,discovery,dhchap_secret=%s,dhchap_ctrl_secret=%s\n'
        )
        self.assertTrue(os.path.exists('/dev/nvme-fabrics'))
        conf.NvmeOptions.destroy()  # Make sure singleton does not exist
        nvme_options = conf.NvmeOptions()
        self.assertTrue(nvme_options.discovery_supp)
        self.assertTrue(nvme_options.host_iface_supp)
        self.assertTrue(nvme_options.dhchap_hostkey_supp)
        self.assertTrue(nvme_options.dhchap_ctrlkey_supp)
        self.assertEqual(
            nvme_options.get(),
            {'discovery': True, 'host_iface': True, 'dhchap_secret': True, 'dhchap_ctrl_secret': True},
        )
        self.assertTrue(str(nvme_options).startswith("supported options:"))


if __name__ == "__main__":
    unittest.main()
