#!/usr/bin/python3
import contextlib
import os
import sys
import unittest


class LibnvmeUnitTest(unittest.TestCase):
    '''Testing defs.py with the real libnvme package'''

    def test_libnvme_version(self):
        try:
            # We can't proceed with this test if the
            # module libnvme is not installed.
            import libnvme
        except ModuleNotFoundError:
            return

        from staslib import defs

        libnvme_ver = defs.LIBNVME_VERSION
        self.assertNotEqual(libnvme_ver, '?.?')


if __name__ == '__main__':
    unittest.main()
