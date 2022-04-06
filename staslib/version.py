# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
''' distutils (and hence LooseVersion) is being deprecated. None of the
    suggested replacements (e.g. from pkg_resources import parse_version) quite
    work with Linux kernel versions the way LooseVersion does.

    It was suggested to simply lift the LooseVersion code and vendor it in,
    which is what this module is about.
'''

import re

class KernelVersion():
    ''' Code loosely lifted from distutils's LooseVersion
    '''
    component_re = re.compile(r'(\d+ | [a-z]+ | \.)', re.VERBOSE)

    def __init__(self, string:str):
        self.string = string
        self.version = self.__parse(string)

    def __str__ (self):
        return self.string

    def __repr__ (self):
        return f'KernelVersion ("{self}")'

    def __eq__(self, other):
        return self.version == self.__version(other)

    def __lt__(self, other):
        return self.version < self.__version(other)

    def __le__(self, other):
        return self.version <= self.__version(other)

    def __gt__(self, other):
        return self.version > self.__version(other)

    def __ge__(self, other):
        return self.version >= self.__version(other)

    @staticmethod
    def __version(obj):
        return obj.version if isinstance(obj, KernelVersion) else KernelVersion.__parse(obj)

    @staticmethod
    def __parse(string):
        components = []
        for item in KernelVersion.component_re.split(string):
            if item and item != '.':
                try:
                    components.append(int(item))
                except ValueError:
                    pass

        return components


if __name__ == '__main__':
    import unittest
    class VersionUnitTests(unittest.TestCase):
        ''' Unit tests for class KernelVersion
        '''
        version = KernelVersion('5.8.0-63-generic')

        def test_eq(self):
            ''' Test equality '''
            self.assertEqual(self.version, '5.8.0-63')
            self.assertNotEqual(self.version, '5.8.0')

        def test_lt(self):
            ''' Test lower than '''
            self.assertTrue(self.version < '5.9')
            self.assertFalse(self.version < '5.7')

        def test_le(self):
            ''' Test lower equal '''
            self.assertTrue(self.version <= '5.8.0-63')
            self.assertTrue(self.version <= '5.8.1')
            self.assertFalse(self.version <= '5.7')

        def test_gt(self):
            ''' Test greater than '''
            self.assertTrue(self.version > '5.8')
            self.assertFalse(self.version > '5.9')

        def test_ge(self):
            ''' Test greater equal '''
            self.assertTrue(self.version >= '5.8.0-63')
            self.assertTrue(self.version >= '5.7.0')
            self.assertFalse(self.version >= '5.9')

    unittest.main()
