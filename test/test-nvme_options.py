#!/usr/bin/python3
import os
import unittest
from staslib import stas, defs
from pyfakefs.fake_filesystem_unittest import TestCase


class Test(TestCase):
    """Unit tests for class NvmeOptions"""

    def setUp(self):
        self.setUpPyfakefs()

    def tearDown(self):
        # No longer need self.tearDownPyfakefs()
        pass

    def test_fabrics_doesnt_exist(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        with self.assertLogs(logger=stas.LOG) as captured:
            nvme_options = stas.NvmeOptions()
            self.assertIsInstance(nvme_options.discovery_supp, bool)
            self.assertIsInstance(nvme_options.host_iface_supp, bool)
            nvme_options.destroy()
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].getMessage(), "Cannot determine which NVMe options the kernel supports")

    def test_fabrics_empty_file(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        # TODO: this is a bug
        self.fs.create_file("/dev/nvme-fabrics")
        self.assertTrue(os.path.exists('/dev/nvme-fabrics'))
        nvme_options = stas.NvmeOptions()
        self.assertIsInstance(nvme_options.discovery_supp, bool)
        self.assertIsInstance(nvme_options.host_iface_supp, bool)
        nvme_options.destroy()

    def test_fabrics_wrong_file(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        self.fs.create_file("/dev/nvme-fabrics", contents="blah")
        self.assertTrue(os.path.exists('/dev/nvme-fabrics'))
        nvme_options = stas.NvmeOptions()
        self.assertIsInstance(nvme_options.discovery_supp, bool)
        self.assertIsInstance(nvme_options.host_iface_supp, bool)
        nvme_options.destroy()

    def test_fabrics_correct_file(self):
        self.assertFalse(os.path.exists("/dev/nvme-fabrics"))
        self.fs.create_file('/dev/nvme-fabrics', contents='host_iface=%s,discovery\n')
        self.assertTrue(os.path.exists('/dev/nvme-fabrics'))
        nvme_options = stas.NvmeOptions()
        self.assertTrue(nvme_options.discovery_supp)
        self.assertTrue(nvme_options.host_iface_supp)
        self.assertEqual(nvme_options.get(), {'discovery': True, 'host_iface': True})
        nvme_options.destroy()


if __name__ == "__main__":
    unittest.main()
