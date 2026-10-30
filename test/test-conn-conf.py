#!/usr/bin/python3
import os
import types
import shutil
import logging
import unittest
import tempfile
import unittest.mock
from staslib import conf

HOSTNQN = 'nqn.2014-08.org.nvmexpress:uuid:01234567-0123-0123-0123-0123456789ab'
HOSTID = '01234567-89ab-cdef-0123-456789abcdef'
DROPIN_HOSTNQN = 'nqn.2014-08.org.nvmexpress:uuid:22222222-2222-2222-2222-222222222222'
DROPIN_HOSTID = '22222222-2222-2222-2222-222222222222'
SYSTEM_HOSTNQN = 'nqn.2014-08.org.nvmexpress:uuid:33333333-3333-3333-3333-333333333333'
SUB1 = 'nqn.2026-10.com.example:sub1'
DISC = 'nqn.2014-08.org.nvmexpress.discovery'

# libnvme checks the form of a secret, not what it decodes to
DEFAULT_IOC_SECRET = 'DHHC-1:00:ZGVmYXVsdC1pb2MtaG9zdC1zZWNyZXQtMDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3:'
DEFAULT_DC_SECRET = 'DHHC-1:00:ZGVmYXVsdC1kYy1ob3N0LXNlY3JldC0wMTIzNDU2Nzg5YWJjZGVmMDEyMzQ1Njc4:'
SECTION_SECRET = 'DHHC-1:00:c2VjdGlvbi1ob3N0LXNlY3JldC0wMTIzNDU2Nzg5YWJjZGVmMDEyMzQ1Njc4OTAx:'
SECTION_CTRL_SECRET = 'DHHC-1:00:c2VjdGlvbi1jdHJsLXNlY3JldC0wMTIzNDU2Nzg5YWJjZGVmMDEyMzQ1Njc4OTAx:'
DROPIN_SECRET = 'DHHC-1:00:ZHJvcGluLWhvc3Qtc2VjcmV0LTAxMjM0NTY3ODlhYmNkZWYwMTIzNDU2Nzg5MDEy:'

DEFAULTS = (
    '[I/O Controller Defaults]\n'
    'kxchap-secret  = %s\n'
    'ctrl-loss-tmo  = 900\n'
    '\n'
    '[Discovery Controller Defaults]\n'
    'kxchap-secret  = %s\n' % (DEFAULT_IOC_SECRET, DEFAULT_DC_SECRET)
)
SUB1_SECTION = (
    '[Subsystem]\n'
    'nqn                = %s\n'
    'kxchap-secret      = %s\n'
    'kxchap-ctrl-secret = %s\n' % (SUB1, SECTION_SECRET, SECTION_CTRL_SECRET)
)


class Test(unittest.TestCase):
    '''Unit tests for ConnConf, the connectivity configuration'''

    def setUp(self):
        # A real path: libnvme derives the drop-in directory from it, so the
        # configuration is reached by an explicit path rather than a sandbox.
        fd, self.fname = tempfile.mkstemp(prefix='stas-conn-conf-', suffix='.conf', dir='/tmp')
        os.close(fd)
        self.addCleanup(self._remove, self.fname)
        self.addCleanup(shutil.rmtree, self.fname + '.d', True)  # the drop-in directory
        conf.ConnConf.destroy()  # Make sure singleton does not exist
        self.addCleanup(conf.ConnConf.destroy)

    @staticmethod
    def _remove(fname):
        if os.path.exists(fname):
            os.remove(fname)

    def _write(self, text):
        with open(self.fname, 'w') as f:
            f.write(text)

    def _write_dropin(self, text):
        os.makedirs(self.fname + '.d', exist_ok=True)
        with open(os.path.join(self.fname + '.d', 'persona.conf'), 'w') as f:
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

    def test_a_number_we_cannot_represent_is_left_to_the_kernel(self):
        '''libnvme validates the file first, so this is defensive: a numeric
        parameter that is not a number is left unset'''
        cnf = self._load('')
        with self.assertLogs(logger=logging.getLogger(), level='WARNING') as captured:
            self.assertIsNone(cnf._value('queue-size', 'NaN'))
        self.assertIn('the kernel default will be used', captured.output[0])
        self.assertEqual(cnf._value('queue-size', '128'), 128)

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

    def test_empty_value_resets_the_parameter(self):
        '''"key =" resets a parameter so the kernel default applies. It stays
        in as an empty value, so that nothing fills it back in.'''
        cnf = self._load(
            '[I/O Controller Defaults]\n'
            'ctrl-loss-tmo =\n'
            '\n'
            '[Subsystem]\n'
            'nqn        = nqn.2024-01.com.example:vol1\n'
            'controller = transport=tcp;traddr=2.2.2.2;trsvcid=4420\n'
        )
        self.assertEqual(cnf.get_controllers(False)[0]['ctrl-loss-tmo'], '')

    def test_a_discovered_controller_gets_its_sections_secrets(self):
        '''A section with the controller's NQN gives it its secrets, on top of
        the defaults for its class. The section needs no "controller =".'''
        cnf = self._load(DEFAULTS + SUB1_SECTION)
        self.assertEqual(
            cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN),
            {'kxchap-secret': SECTION_SECRET, 'kxchap-ctrl-secret': SECTION_CTRL_SECRET, 'ctrl-loss-tmo': 900},
        )

    def test_a_discovered_controller_without_a_section_gets_the_defaults(self):
        '''What nvme-discoverd does. The secret of the Discovery Controller
        that reported the controller is not inherited.'''
        cnf = self._load(DEFAULTS + SUB1_SECTION)
        self.assertEqual(
            cnf.discovered_params(False, 'nqn.2026-10.com.example:other', SYSTEM_HOSTNQN),
            {'kxchap-secret': DEFAULT_IOC_SECRET, 'ctrl-loss-tmo': 900},
        )
        self.assertEqual(cnf.discovered_params(True, DISC, SYSTEM_HOSTNQN), {'kxchap-secret': DEFAULT_DC_SECRET})

    def test_a_section_of_the_other_class_does_not_match(self):
        '''A [Subsystem] is for an I/O controller, not a Discovery Controller
        with the same NQN.'''
        cnf = self._load(DEFAULTS + SUB1_SECTION)
        self.assertEqual(cnf.discovered_params(True, SUB1, SYSTEM_HOSTNQN), {'kxchap-secret': DEFAULT_DC_SECRET})

    def test_an_empty_secret_in_the_section_resets_it(self):
        cnf = self._load(DEFAULTS + '[Subsystem]\nnqn = %s\nkxchap-secret =\n' % SUB1)
        self.assertEqual(cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN)['kxchap-secret'], '')

    def test_a_drop_in_persona_gets_its_own_section(self):
        '''A secret belongs to one (host, subsystem) pair: the drop-in's
        section is for the drop-in's persona only, and the reverse.'''
        self._write_dropin(
            '[Host]\n'
            'hostnqn = %s\n'
            'hostid  = %s\n'
            '\n'
            '[Subsystem]\n'
            'nqn           = %s\n'
            'kxchap-secret = %s\n' % (DROPIN_HOSTNQN, DROPIN_HOSTID, SUB1, DROPIN_SECRET)
        )
        cnf = self._load(DEFAULTS + SUB1_SECTION)
        self.assertEqual(cnf.discovered_params(False, SUB1, DROPIN_HOSTNQN)['kxchap-secret'], DROPIN_SECRET)
        self.assertNotIn('kxchap-ctrl-secret', cnf.discovered_params(False, SUB1, DROPIN_HOSTNQN))
        self.assertEqual(cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN)['kxchap-secret'], SECTION_SECRET)

    def test_the_top_level_persona_is_found_by_its_hostnqn(self):
        cnf = self._load('[Host]\nhostnqn = %s\nhostid = %s\n\n' % (HOSTNQN, HOSTID) + DEFAULTS + SUB1_SECTION)
        self.assertEqual(cnf.discovered_params(False, SUB1, HOSTNQN)['kxchap-secret'], SECTION_SECRET)

    def test_another_host_identity_gets_no_secret(self):
        '''A host NQN no file has, while the top-level file names its own: the
        top-level defaults may apply to it, the secrets may not.'''
        cnf = self._load('[Host]\nhostnqn = %s\nhostid = %s\n\n' % (HOSTNQN, HOSTID) + DEFAULTS + SUB1_SECTION)
        self.assertEqual(cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN), {'ctrl-loss-tmo': 900})

    def test_the_answers_are_kept_until_a_reload(self):
        '''The file is not read again on every connection attempt, and a
        reload picks up the new secrets.'''
        cnf = self._load(DEFAULTS + SUB1_SECTION)
        self.assertEqual(cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN)['kxchap-secret'], SECTION_SECRET)

        self._write(DEFAULTS)
        self.assertEqual(cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN)['kxchap-secret'], SECTION_SECRET)
        self.assertTrue(cnf.reload())
        self.assertEqual(cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN)['kxchap-secret'], DEFAULT_IOC_SECRET)

    def test_a_rejected_reload_keeps_the_answers(self):
        cnf = self._load(DEFAULTS + SUB1_SECTION)
        self.assertEqual(cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN)['kxchap-secret'], SECTION_SECRET)

        # Two sections with one NQN and different secrets: rejected.
        self._write(DEFAULTS + SUB1_SECTION + '[Subsystem]\nnqn = %s\nkxchap-secret = %s\n' % (SUB1, DROPIN_SECRET))
        with self.assertLogs(level='ERROR'):
            self.assertFalse(cnf.reload())
        self.assertEqual(cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN)['kxchap-secret'], SECTION_SECRET)

    def test_a_file_that_cannot_be_read_gives_no_secret(self):
        '''Edited into something libnvme rejects since the last reload: the
        last defaults read apply, without their secrets.'''
        cnf = self._load(DEFAULTS + SUB1_SECTION)
        self._write(DEFAULTS + SUB1_SECTION + '[Subsystem]\nnqn = %s\nkxchap-secret = %s\n' % (SUB1, DROPIN_SECRET))
        with self.assertLogs(level='WARNING') as captured:
            self.assertEqual(cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN), {'ctrl-loss-tmo': 900})
        self.assertIn('Unable to read the parameters of %s' % SUB1, captured.output[0])

    def test_an_older_libnvme_gives_no_secret(self):
        '''libnvme before 3.2 cannot match a section, and its defaults are not
        attributed to a persona.'''
        cnf = self._load(DEFAULTS + SUB1_SECTION)
        with unittest.mock.patch.object(conf, 'nvme', types.SimpleNamespace()):
            self.assertEqual(cnf.discovered_params(False, SUB1, SYSTEM_HOSTNQN), {'ctrl-loss-tmo': 900})

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
        with self.assertLogs(level='ERROR') as logs:
            self.assertFalse(cnf.reload())
        self.assertIn('keeping the previous one', logs.output[0])

        dcs = cnf.get_controllers(True)
        self.assertEqual(len(dcs), 1)
        self.assertEqual(dcs[0]['traddr'], '1.1.1.1')  # the good one, still there

    def test_a_rejected_file_at_startup_says_so(self):
        '''There is no previous configuration to keep the first time round, so
        the daemon starts with nothing configured and must not claim otherwise.'''
        self._write(
            '[Host]\nhostnqn = %s\n'
            '[Host]\nhostnqn = nqn.2014-08.org.nvmexpress:uuid:aaaaaaaa-0000-0000-0000-000000000002\n' % HOSTNQN
        )
        conf.ConnConf.destroy()
        with self.assertLogs(level='ERROR') as logs:
            cnf = conf.ConnConf(conf_file=self.fname)

        self.assertIn('no controllers will be configured', logs.output[0])
        self.assertNotIn('keeping the previous one', logs.output[0])
        self.assertEqual(cnf.get_controllers(True), [])
        self.assertEqual(cnf.get_controllers(False), [])


if __name__ == '__main__':
    unittest.main()
