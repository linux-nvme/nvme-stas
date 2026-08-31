#!/usr/bin/python3
import os
import unittest
import tempfile
from staslib import conf

HOSTNQN = 'nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab'
HOSTID = '01234567-89ab-cdef-0123-456789abcdef'


class Test(unittest.TestCase):
    '''Unit tests for ConnConf, the connectivity configuration'''

    def setUp(self):
        # A real path: libnvme derives the drop-in directory from it, so the
        # configuration is reached by an explicit path rather than a sandbox.
        fd, self.fname = tempfile.mkstemp(prefix='stas-conn-conf-', suffix='.conf', dir='/tmp')
        os.close(fd)
        self.addCleanup(self._remove, self.fname)
        conf.ConnConf.destroy()  # Make sure singleton does not exist
        self.addCleanup(conf.ConnConf.destroy)

    @staticmethod
    def _remove(fname):
        if os.path.exists(fname):
            os.remove(fname)

    def _write(self, text):
        with open(self.fname, 'w') as f:
            f.write(text)

    def _load(self, text):
        self._write(text)
        conf.ConnConf.destroy()
        return conf.ConnConf(conf_file=self.fname)

    def test_absent_file_configures_nothing(self):
        # "If neither exists, the configuration is empty - a gentle no-op."
        os.remove(self.fname)
        cnf = conf.ConnConf(conf_file=self.fname)
        self.assertEqual(cnf.get_controllers(True), [])
        self.assertEqual(cnf.get_controllers(False), [])

    def test_empty_file_configures_nothing(self):
        cnf = self._load('')
        self.assertEqual(cnf.get_controllers(True), [])
        self.assertEqual(cnf.get_controllers(False), [])

    def test_discovery_controller(self):
        cnf = self._load(
            '[Discovery Controller]\n'
            'controller = transport=tcp;traddr=1.1.1.1;trsvcid=8009\n'
        )
        dcs = cnf.get_controllers(True)
        self.assertEqual(len(dcs), 1)
        self.assertEqual(dcs[0]['transport'], 'tcp')
        self.assertEqual(dcs[0]['traddr'], '1.1.1.1')
        self.assertEqual(dcs[0]['trsvcid'], '8009')
        # An omitted nqn means the well-known discovery NQN
        self.assertEqual(dcs[0]['subsysnqn'], 'nqn.2014-08.org.nvmexpress.discovery')
        # A Discovery Controller is not an I/O controller
        self.assertEqual(cnf.get_controllers(False), [])

    def test_subsystem(self):
        cnf = self._load(
            '[Subsystem]\n'
            'nqn        = nqn.2024-01.com.example:vol1\n'
            'controller = transport=tcp;traddr=2.2.2.2;trsvcid=4420\n'
        )
        iocs = cnf.get_controllers(False)
        self.assertEqual(len(iocs), 1)
        self.assertEqual(iocs[0]['subsysnqn'], 'nqn.2024-01.com.example:vol1')
        self.assertEqual(cnf.get_controllers(True), [])

    def test_each_controller_line_is_one_connection(self):
        '''A [Subsystem] with N "controller =" lines is N connections, one per
        path. The grouping is an authoring convenience that then evaporates.'''
        cnf = self._load(
            '[Subsystem]\n'
            'nqn        = nqn.2024-01.com.example:vol1\n'
            'controller = transport=tcp;traddr=3.3.3.1;trsvcid=4420;host-iface=eth0\n'
            'controller = transport=tcp;traddr=3.3.3.2;trsvcid=4420;host-iface=eth1\n'
        )
        iocs = cnf.get_controllers(False)
        self.assertEqual(len(iocs), 2)
        self.assertEqual({ioc['traddr'] for ioc in iocs}, {'3.3.3.1', '3.3.3.2'})
        self.assertEqual({ioc['host-iface'] for ioc in iocs}, {'eth0', 'eth1'})

    def test_host_identity_reaches_every_connection(self):
        cnf = self._load(
            '[Host]\n'
            'hostnqn     = %s\n'
            'hostid      = %s\n'
            'hostsymname = lab-host-01\n'
            '\n'
            '[Discovery Controller]\n'
            'controller = transport=tcp;traddr=1.1.1.1;trsvcid=8009\n' % (HOSTNQN, HOSTID)
        )
        dc = cnf.get_controllers(True)[0]
        self.assertEqual(dc['hostnqn'], HOSTNQN)
        self.assertEqual(dc['hostid'], HOSTID)
        self.assertEqual(dc['hostsymname'], 'lab-host-01')

    def test_defaults_cascade_and_are_overridden(self):
        '''The type defaults apply to their own class of controller, and a more
        specific setting wins.'''
        cnf = self._load(
            '[Discovery Controller Defaults]\n'
            'keep-alive-tmo = 30\n'
            'ctrl-loss-tmo  = 600\n'
            '\n'
            '[I/O Controller Defaults]\n'
            'ctrl-loss-tmo  = 900\n'
            'nr-io-queues   = 4\n'
            '\n'
            '[Discovery Controller]\n'
            'controller = transport=tcp;traddr=1.1.1.1;trsvcid=8009\n'
            '\n'
            '[Subsystem]\n'
            'nqn           = nqn.2024-01.com.example:vol1\n'
            'ctrl-loss-tmo = 1800\n'
            'controller    = transport=tcp;traddr=2.2.2.2;trsvcid=4420\n'
        )
        dc = cnf.get_controllers(True)[0]
        self.assertEqual(dc['keep-alive-tmo'], 30)
        self.assertEqual(dc['ctrl-loss-tmo'], 600)
        self.assertNotIn('nr-io-queues', dc)  # an I/O default, not a DC one

        ioc = cnf.get_controllers(False)[0]
        self.assertEqual(ioc['nr-io-queues'], 4)
        self.assertEqual(ioc['ctrl-loss-tmo'], 1800)  # the section beats the default

    def test_values_are_converted_to_the_types_the_kernel_wants(self):
        cnf = self._load(
            '[I/O Controller Defaults]\n'
            'nr-io-queues   = 8\n'
            'hdr-digest     = true\n'
            'data-digest    = no\n'
            '\n'
            '[Subsystem]\n'
            'nqn        = nqn.2024-01.com.example:vol1\n'
            'controller = transport=tcp;traddr=2.2.2.2;trsvcid=4420\n'
        )
        ioc = cnf.get_controllers(False)[0]
        self.assertIsInstance(ioc['nr-io-queues'], int)
        self.assertEqual(ioc['nr-io-queues'], 8)
        self.assertIs(ioc['hdr-digest'], True)
        self.assertIs(ioc['data-digest'], False)

    def test_empty_value_leaves_the_parameter_unset(self):
        '''"key =" resets a parameter so the kernel default applies.'''
        cnf = self._load(
            '[I/O Controller Defaults]\n'
            'ctrl-loss-tmo =\n'
            '\n'
            '[Subsystem]\n'
            'nqn        = nqn.2024-01.com.example:vol1\n'
            'controller = transport=tcp;traddr=2.2.2.2;trsvcid=4420\n'
        )
        self.assertNotIn('ctrl-loss-tmo', cnf.get_controllers(False)[0])

    def test_defaults_are_exposed_by_controller_class(self):
        '''What a controller we discovered draws on: it is in no file, so it
        gets the top-level defaults for its class.'''
        cnf = self._load(
            '[Discovery Controller Defaults]\n'
            'keep-alive-tmo = 30\n'
            '\n'
            '[I/O Controller Defaults]\n'
            'ctrl-loss-tmo = 900\n'
        )
        self.assertEqual(cnf.defaults(True), {'keep-alive-tmo': 30})
        self.assertEqual(cnf.defaults(False), {'ctrl-loss-tmo': 900})

    def test_host_identity_without_connections(self):
        '''A [Host] and nothing else still names the persona - the case of a
        host that connects only what it discovers.'''
        cnf = self._load(
            '[Host]\n'
            'hostnqn     = %s\n'
            'hostid      = %s\n'
            'hostsymname = solo\n' % (HOSTNQN, HOSTID)
        )
        self.assertEqual(cnf.get_controllers(True), [])
        self.assertEqual(cnf.hostnqn, HOSTNQN)
        self.assertEqual(cnf.hostid, HOSTID)
        self.assertEqual(cnf.hostsymname, 'solo')

    def test_no_host_section(self):
        cnf = self._load('[Discovery Controller]\ncontroller = transport=tcp;traddr=1.1.1.1\n')
        self.assertIsNone(cnf.hostnqn)
        self.assertIsNone(cnf.hostid)
        self.assertIsNone(cnf.hostsymname)

    def test_a_rejected_file_keeps_the_previous_configuration(self):
        '''A fat-fingered edit must never tear down working connections.'''
        cnf = self._load(
            '[Discovery Controller]\n'
            'controller = transport=tcp;traddr=1.1.1.1;trsvcid=8009\n'
        )
        self.assertEqual(len(cnf.get_controllers(True)), 1)

        # Two [Host] sections in one file: personas never merge, so this is an
        # error rather than something to resolve.
        self._write(
            '[Host]\nhostnqn = %s\n'
            '[Host]\nhostnqn = nqn.2014-08.org.nvmexpress:uuid:aaaaaaaa-0000-0000-0000-000000000002\n'
            '[Discovery Controller]\n'
            'controller = transport=tcp;traddr=9.9.9.9;trsvcid=8009\n' % HOSTNQN
        )
        self.assertFalse(cnf.reload())
        dcs = cnf.get_controllers(True)
        self.assertEqual(len(dcs), 1)
        self.assertEqual(dcs[0]['traddr'], '1.1.1.1')  # the good one, still there


if __name__ == '__main__':
    unittest.main()
