#!/usr/bin/python3
import unittest
from staslib.version import KernelVersion

if __name__ == '__main__':

    class VersionUnitTests(unittest.TestCase):
        '''Unit tests for class KernelVersion'''

        version = KernelVersion('5.8.0-63-generic')

        def test_str(self):
            self.assertIsInstance(str(self.version), str)

        def test_repr(self):
            self.assertIsInstance(repr(self.version), str)

        def test_eq(self):
            '''Test equality'''
            self.assertEqual(self.version, '5.8.0-63')
            self.assertNotEqual(self.version, '5.8.0')

        def test_lt(self):
            '''Test lower than'''
            self.assertTrue(self.version < '5.9')
            self.assertFalse(self.version < '5.7')

        def test_le(self):
            '''Test lower equal'''
            self.assertTrue(self.version <= '5.8.0-63')
            self.assertTrue(self.version <= '5.8.1')
            self.assertFalse(self.version <= '5.7')

        def test_gt(self):
            '''Test greater than'''
            self.assertTrue(self.version > '5.8')
            self.assertFalse(self.version > '5.9')

        def test_ge(self):
            '''Test greater equal'''
            self.assertTrue(self.version >= '5.8.0-63')
            self.assertTrue(self.version >= '5.7.0')
            self.assertFalse(self.version >= '5.9')

    unittest.main()
