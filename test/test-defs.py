#!/usr/bin/python3
import gc
import sys
import copy
import unittest

from unittest import mock


class MockLibnvmeTestCase(unittest.TestCase):
    '''Testing defs.py by mocking the libnvme package'''

    def test_libnvme_version(self):
        # implement your testing logic, for example:
        from staslib import defs

        libnvme_ver = defs.LIBNVME_VERSION
        self.assertEqual(libnvme_ver, '?.?')

    @classmethod
    def setUpClass(cls):  # called once before all the tests
        # define what to patch sys.modules with
        cls._modules_patcher = mock.patch.dict(
            sys.modules,
            {'libnvme': mock.Mock()},
        )
        # actually patch it
        cls._modules_patcher.start()
        # make the package globally visible and import it,
        #   just like if you have imported it in a usual way
        #   placing import statement at the top of the file,
        #   but relying on a patched dependency
        global libnvme
        import libnvme

    @classmethod  # called once after all tests
    def tearDownClass(cls):
        # restore initial sys.modules state back
        cls._modules_patcher.stop()


class RealLibnvmeUnitTest(unittest.TestCase):
    '''Testing defs.py with the real libnvme package'''

    def test_LIBNVME_VERSION(self):
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
