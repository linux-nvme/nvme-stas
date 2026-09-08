#!/usr/bin/python3
# SPDX-License-Identifier: Apache-2.0
import unittest
import xml.etree.ElementTree as ET

from staslib import defs, stas


class IdlUnitTest(unittest.TestCase):
    '''Test the D-Bus introspection XML files'''

    def test_declared_interfaces(self):
        '''The DocBooks generated from the IDLs are listed by name in
        doc/meson.build and doc/readthedocs/meson.build, which assume each IDL
        declares the daemon's interface and its ".debug" companion. An interface
        added without updating those lists would silently go undocumented, since
        meson ignores a generated file it was not told to expect.'''

        for idl_fname, dbus_name in (
            ('stafd.idl', defs.STAFD_DBUS_NAME),
            ('stacd.idl', defs.STACD_DBUS_NAME),
        ):
            with self.subTest(idl=idl_fname):
                idl = stas.load_idl(idl_fname)
                self.assertNotEqual(idl, '', f'{idl_fname} could not be loaded')

                interfaces = {node.get('name') for node in ET.fromstring(idl).findall('.//interface')}
                self.assertEqual(
                    interfaces,
                    {dbus_name, dbus_name + '.debug'},
                    f'{idl_fname} declares unexpected interfaces. The documentation lists the '
                    f'DocBooks by name: update doc/meson.build and doc/readthedocs/.',
                )


if __name__ == '__main__':
    unittest.main()
