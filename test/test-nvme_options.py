#!/usr/bin/python3
import os
import unittest
from staslib import stas

if __name__ == '__main__':

    class Test(unittest.TestCase):
        '''Unit tests for class NvmeOptions'''

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.is_root = os.geteuid() == 0
            if self.is_root:  # Only root can access /dev/nvme-fabrics
                self.nvme_options = stas.NvmeOptions()
            else:
                self.nvme_options = None

        def test_discovery_supp(self):
            '''Test discovery_supp'''
            if self.nvme_options:
                self.assertEqual(type(self.nvme_options.discovery_supp), bool)

        def test_host_iface_supp(self):
            '''Test host_iface_supp'''
            if self.nvme_options:
                self.assertEqual(type(self.nvme_options.host_iface_supp), bool)

        def test_str(self):
            self.assertIsInstance(str(self.nvme_options), str)

    unittest.main()
