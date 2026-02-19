#!/usr/bin/python3
import os
import sys
import uuid
import tempfile
import unittest
import configparser
import unittest.mock as mock
import importlib.util

# ---------------------------------------------------------------------------
# Load stasadm as a module. stasadm.py has module-level entry-point code
# (parse_args / sys.exit / ARGS.cmd) that runs at import time. We suppress
# it by mocking sys.argv and sys.exit, then catching the AttributeError that
# results from ARGS.cmd not existing when no subcommand is given.
# ---------------------------------------------------------------------------
_STASADM_PY = os.path.join(os.path.dirname(__file__), '..', 'stasadm.py')
_spec = importlib.util.spec_from_file_location('stasadm', _STASADM_PY)
_mod = importlib.util.module_from_spec(_spec)
with mock.patch.object(sys, 'argv', ['stasadm']), \
        mock.patch.object(sys, 'exit'), \
        mock.patch('sys.stdout'), \
        mock.patch('sys.stderr'):
    try:
        _spec.loader.exec_module(_mod)
    except AttributeError:
        pass  # Expected: sys.exit is mocked so execution falls through to ARGS.cmd(ARGS)


class TestReadFromFile(unittest.TestCase):
    '''Tests for read_from_file()'''

    def test_read_existing_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write('hello world!')
            fname = f.name
        try:
            result = _mod.read_from_file(fname, 12)
            self.assertEqual(result, 'hello world!')
        finally:
            os.unlink(fname)

    def test_read_short_file(self):
        '''If the file is shorter than requested size, return None'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write('hi')
            fname = f.name
        try:
            result = _mod.read_from_file(fname, 100)
            self.assertIsNone(result)
        finally:
            os.unlink(fname)

    def test_read_missing_file(self):
        result = _mod.read_from_file('/tmp/this-file-does-not-exist-stasadm-test', 10)
        self.assertIsNone(result)


class TestGetMachineAppSpecific(unittest.TestCase):
    '''Tests for get_machine_app_specific()'''

    # A 32-char hex string is the format of /etc/machine-id
    _FAKE_MACHINE_ID = 'a' * 32

    def test_returns_valid_uuid(self):
        with mock.patch.object(_mod, 'read_from_file', return_value=self._FAKE_MACHINE_ID):
            result = _mod.get_machine_app_specific(b'$test.app$')
        self.assertIsNotNone(result)
        # Must parse as a valid UUID without raising
        uuid.UUID(result)

    def test_missing_machine_id_returns_none(self):
        with mock.patch.object(_mod, 'read_from_file', return_value=None):
            result = _mod.get_machine_app_specific(b'$test.app$')
        self.assertIsNone(result)

    def test_deterministic(self):
        '''Same inputs must always produce the same output'''
        app_id = b'$test.app$'
        with mock.patch.object(_mod, 'read_from_file', return_value=self._FAKE_MACHINE_ID):
            r1 = _mod.get_machine_app_specific(app_id)
            r2 = _mod.get_machine_app_specific(app_id)
        self.assertEqual(r1, r2)

    def test_different_app_ids_produce_different_uuids(self):
        with mock.patch.object(_mod, 'read_from_file', return_value=self._FAKE_MACHINE_ID):
            r1 = _mod.get_machine_app_specific(b'$app.one$')
            r2 = _mod.get_machine_app_specific(b'$app.two$')
        self.assertNotEqual(r1, r2)


class TestSave(unittest.TestCase):
    '''Tests for save()'''

    def test_save_string_to_plain_file(self):
        with tempfile.NamedTemporaryFile(mode='r', suffix='.txt', delete=False) as f:
            fname = f.name
        try:
            _mod.save('Host', 'nqn', 'test-value', None, fname)
            with open(fname) as f:
                content = f.read()
            self.assertIn('test-value', content)
        finally:
            os.unlink(fname)

    def test_save_to_conf_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
            fname = f.name
        try:
            _mod.save('Host', 'nqn', 'my-nqn', fname, None)
            config = configparser.ConfigParser(
                default_section=None, allow_no_value=True,
                delimiters=('='), interpolation=None, strict=False,
            )
            config.read(fname)
            self.assertEqual(config['Host']['nqn'], 'my-nqn')
        finally:
            os.unlink(fname)

    def test_remove_option_from_conf_file(self):
        '''save() with string=None removes the option'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as f:
            fname = f.name
        try:
            _mod.save('Host', 'nqn', 'my-nqn', fname, None)
            _mod.save('Host', 'nqn', None, fname, None)
            config = configparser.ConfigParser(
                default_section=None, allow_no_value=True,
                delimiters=('='), interpolation=None, strict=False,
            )
            config.read(fname)
            self.assertFalse(config.has_option('Host', 'nqn'))
        finally:
            os.unlink(fname)

    def test_save_adds_file_uri_when_fname_given(self):
        '''When both conf_file and fname are given, conf_file gets a file:// URI'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.conf', delete=False) as cf:
            conf_fname = cf.name
        with tempfile.NamedTemporaryFile(mode='r', suffix='.nqn', delete=False) as pf:
            plain_fname = pf.name
        try:
            _mod.save('Host', 'nqn', 'my-nqn', conf_fname, plain_fname)
            config = configparser.ConfigParser(
                default_section=None, allow_no_value=True,
                delimiters=('='), interpolation=None, strict=False,
            )
            config.read(conf_fname)
            self.assertEqual(config['Host']['nqn'], f'file://{plain_fname}')
        finally:
            os.unlink(conf_fname)
            os.unlink(plain_fname)


class TestGetParser(unittest.TestCase):
    '''Tests for get_parser()'''

    def test_returns_argumentparser(self):
        from argparse import ArgumentParser
        self.assertIsInstance(_mod.get_parser(), ArgumentParser)

    def test_hostnqn_subcommand(self):
        args = _mod.get_parser().parse_args(['hostnqn'])
        self.assertTrue(hasattr(args, 'cmd'))
        self.assertIs(args.cmd, _mod.hostnqn)

    def test_hostid_subcommand(self):
        args = _mod.get_parser().parse_args(['hostid'])
        self.assertTrue(hasattr(args, 'cmd'))
        self.assertIs(args.cmd, _mod.hostid)

    def test_set_symname_subcommand(self):
        args = _mod.get_parser().parse_args(['set-symname', 'myhost'])
        self.assertTrue(hasattr(args, 'cmd'))
        self.assertIs(args.cmd, _mod.set_symname)
        self.assertEqual(args.symname, 'myhost')

    def test_clear_symname_subcommand(self):
        args = _mod.get_parser().parse_args(['clear-symname'])
        self.assertTrue(hasattr(args, 'cmd'))
        self.assertIs(args.cmd, _mod.clr_symname)

    def test_no_subcommand_sets_no_cmd(self):
        args = _mod.get_parser().parse_args([])
        self.assertFalse(hasattr(args, 'cmd'))

    def test_version_flag(self):
        args = _mod.get_parser().parse_args(['--version'])
        self.assertTrue(args.version)


if __name__ == '__main__':
    unittest.main()
