#!/usr/bin/python3
import os
import atexit
import shutil
import tempfile
import unittest
from libnvme3 import nvme
from staslib import conf, defs, stas, trid

TEST_DIR = os.path.dirname(__file__)
HOSTNQN = 'nqn.1988-11.com.dell:PowerEdge.R760.1234567'

# Controllers described by the NBFT tables under test/NBFT (see test-nbft_conf.py)
NBFT_DC = {
    'transport': 'tcp',
    'traddr': '100.71.103.50',
    'trsvcid': '8009',
    'subsysnqn': 'nqn.2014-08.org.nvmexpress.discovery',
    'hostnqn': HOSTNQN,
}
NBFT_IOC = {
    'transport': 'tcp',
    'traddr': '100.71.103.48',
    'trsvcid': '4420',
    'subsysnqn': 'nqn.1988-11.com.dell:powerstore:00:2a64abf1c5b81F6C4549',
    'hostnqn': HOSTNQN,
}


def libnvme_sandbox():
    '''Return a directory where libnvme reads its host-wide config files.

    libnvme's test base dir is process-global and only the first call takes
    effect, so every test file that needs one must agree on the same path:
    "meson test" runs each file in its own process, but pytest runs them all
    in one. The path must be under /tmp.
    '''
    path = os.path.join(tempfile.gettempdir(), 'nvme-stas-test-%d' % os.getpid())
    if not os.path.exists(path):
        os.makedirs(path)
        atexit.register(shutil.rmtree, path, ignore_errors=True)
    conf.libnvme_ctx().set_test_base_dir(path)
    return path


# ==============================================================================
class TestProtected(unittest.TestCase):
    '''Unit tests for stas.protected(), which decides whether a connection is
    ours to disconnect.'''

    @classmethod
    def setUpClass(cls):
        cls.SANDBOX = libnvme_sandbox()

    def setUp(self):
        # An empty NBFT: the tests that need one load the sample tables
        conf.NbftConf.destroy()
        conf.NbftConf('/tmp')
        self.addCleanup(conf.NbftConf.destroy)

    def _register(self, device, owner):
        nvme.registry_update(conf.libnvme_ctx(), device, 'owner', owner)
        self.addCleanup(nvme.registry_delete, conf.libnvme_ctx(), device)

    def _make_tid(self, **kwargs):
        cid = {'transport': 'tcp', 'traddr': '1.1.1.1', 'subsysnqn': 'nqn.unrelated', 'hostnqn': HOSTNQN}
        cid.update(kwargs)
        return trid.TID(cid)

    def test_no_device_and_no_nbft(self):
        self.assertFalse(stas.protected(self._make_tid()))

    def test_unregistered_device_is_not_protected(self):
        # A connection nobody claimed stays eligible: that is what every
        # connection predating the registry looks like.
        self.assertFalse(stas.protected(self._make_tid(), 'nvme9'))

    def test_owned_by_another_orchestrator(self):
        self._register('nvme1', 'discoverd')
        self.assertTrue(stas.protected(self._make_tid(), 'nvme1'))

    def test_owned_by_us(self):
        self._register('nvme2', defs.REGISTRY_OWNER)
        self.assertFalse(stas.protected(self._make_tid(), 'nvme2'))

    def test_owned_by_nbft(self):
        self._register('nvme3', 'nbft')
        self.assertTrue(stas.protected(self._make_tid(), 'nvme3'))

    def test_unconnected_controller(self):
        # Controller.device is "nvme?" while there is no connection. libnvme
        # rejects that as a device name, so we must not hand it over.
        self.assertIsNone(stas._owner('nvme?'))
        self.assertFalse(stas.protected(self._make_tid(), 'nvme?'))

    def test_nbft_discovery_controller(self):
        conf.NbftConf.destroy()
        conf.NbftConf(TEST_DIR)
        self.assertTrue(stas.protected(trid.TID(NBFT_DC)))

    def test_nbft_io_controller(self):
        conf.NbftConf.destroy()
        conf.NbftConf(TEST_DIR)
        self.assertTrue(stas.protected(trid.TID(NBFT_IOC)))

    def test_controller_absent_from_the_nbft(self):
        conf.NbftConf.destroy()
        conf.NbftConf(TEST_DIR)
        self.assertFalse(stas.protected(self._make_tid()))

    def test_nbft_controller_with_no_registry_entry(self):
        # The NBFT check stands on its own: it does not need the initramfs to
        # have registered "owner=nbft".
        conf.NbftConf.destroy()
        conf.NbftConf(TEST_DIR)
        self.assertTrue(stas.protected(trid.TID(NBFT_DC), 'nvme9'))

    def test_nbft_controller_registered_to_us(self):
        # Even if we somehow own the registry entry, the NBFT wins
        conf.NbftConf.destroy()
        conf.NbftConf(TEST_DIR)
        self._register('nvme4', defs.REGISTRY_OWNER)
        self.assertTrue(stas.protected(trid.TID(NBFT_DC), 'nvme4'))


# ==============================================================================
class TestClaim(unittest.TestCase):
    '''Unit tests for stas.claim(), which records that a connection is ours.
    Controller._do_connect() borrows an existing connection instead of making a
    new one, and a borrow never goes through libnvme's connect path, so nothing
    would register us as the owner without this.'''

    @classmethod
    def setUpClass(cls):
        cls.SANDBOX = libnvme_sandbox()

    def _owner_of(self, device):
        self.addCleanup(nvme.registry_delete, conf.libnvme_ctx(), device)
        return nvme.registry_retrieve(conf.libnvme_ctx(), device, 'owner')

    def _register(self, device, owner):
        nvme.registry_update(conf.libnvme_ctx(), device, 'owner', owner)
        self.addCleanup(nvme.registry_delete, conf.libnvme_ctx(), device)

    def _make_tid(self):
        return trid.TID({'transport': 'tcp', 'traddr': '1.1.1.1', 'subsysnqn': 'nqn.unrelated', 'hostnqn': HOSTNQN})

    def test_unowned_connection_becomes_ours(self):
        stas.claim(self._make_tid(), 'nvme20')
        self.assertEqual(self._owner_of('nvme20'), defs.REGISTRY_OWNER)

    def test_already_ours_stays_ours(self):
        self._register('nvme21', defs.REGISTRY_OWNER)
        stas.claim(self._make_tid(), 'nvme21')
        self.assertEqual(nvme.registry_retrieve(conf.libnvme_ctx(), 'nvme21', 'owner'), defs.REGISTRY_OWNER)

    def test_somebody_elses_connection_is_left_alone(self):
        # remove_protected() should have kept this out of our hands, but
        # ownership can change under a connection we already hold. Taking it
        # away from its owner is never ours to do.
        self._register('nvme22', 'discoverd')
        stas.claim(self._make_tid(), 'nvme22')
        self.assertEqual(nvme.registry_retrieve(conf.libnvme_ctx(), 'nvme22', 'owner'), 'discoverd')

    def test_unconnected_controller(self):
        # Controller.device is "nvme?" while there is no connection. libnvme
        # rejects that as a device name, so we must not hand it over.
        stas.claim(self._make_tid(), 'nvme?')
        self.assertIsNone(stas._owner('nvme?'))

    def test_no_device(self):
        stas.claim(self._make_tid(), None)


# ==============================================================================
class TestRemoveProtected(unittest.TestCase):
    '''Unit tests for stas.remove_protected(), which keeps controllers that
    aren't ours out of the set stafd/stacd manage.'''

    class Device:
        '''Stand-in for the udev device of an existing connection.'''

        def __init__(self, sys_name):
            self.sys_name = sys_name

    @classmethod
    def setUpClass(cls):
        cls.SANDBOX = libnvme_sandbox()

    def setUp(self):
        conf.NbftConf.destroy()
        conf.NbftConf('/tmp')  # no NBFT unless a test asks for one
        self.addCleanup(conf.NbftConf.destroy)

    def _register(self, device, owner):
        nvme.registry_update(conf.libnvme_ctx(), device, 'owner', owner)
        self.addCleanup(nvme.registry_delete, conf.libnvme_ctx(), device)

    def _make_tid(self, traddr):
        return trid.TID({'transport': 'tcp', 'traddr': traddr, 'subsysnqn': 'nqn.unrelated', 'hostnqn': HOSTNQN})

    @staticmethod
    def _finder(devices):
        '''Return a find_device() that maps the given TIDs to device names.'''
        return lambda tid: TestRemoveProtected.Device(devices[tid]) if tid in devices else None

    def test_no_existing_connections(self):
        controllers = [self._make_tid('1.1.1.1'), self._make_tid('2.2.2.2')]
        self.assertEqual(stas.remove_protected(controllers, self._finder({})), controllers)

    def test_connection_owned_by_another_orchestrator_is_dropped(self):
        theirs = self._make_tid('1.1.1.1')
        ours = self._make_tid('2.2.2.2')
        self._register('nvme1', 'discoverd')
        find = self._finder({theirs: 'nvme1'})
        self.assertEqual(stas.remove_protected([theirs, ours], find), [ours])

    def test_our_own_connection_is_kept(self):
        tid = self._make_tid('1.1.1.1')
        self._register('nvme2', defs.REGISTRY_OWNER)
        self.assertEqual(stas.remove_protected([tid], self._finder({tid: 'nvme2'})), [tid])

    def test_unowned_connection_is_kept(self):
        # A connection nobody claimed is one we may adopt: that is what every
        # connection predating the registry looks like.
        tid = self._make_tid('1.1.1.1')
        self.assertEqual(stas.remove_protected([tid], self._finder({tid: 'nvme9'})), [tid])

    def test_nbft_controller_is_dropped_even_with_no_connection(self):
        # The NBFT check needs no device: a boot controller stays out of the
        # managed set whether or not it is connected right now.
        conf.NbftConf.destroy()
        conf.NbftConf(TEST_DIR)
        nbft_tid = trid.TID(NBFT_IOC)
        ours = self._make_tid('2.2.2.2')
        self.assertEqual(stas.remove_protected([nbft_tid, ours], self._finder({})), [ours])


# ==============================================================================
class TestNbftIsNotManaged(unittest.TestCase):
    '''The NBFT must not contribute to the list of controllers we connect to.'''

    def setUp(self):
        conf.NbftConf.destroy()
        conf.NbftConf(TEST_DIR)
        self.addCleanup(conf.NbftConf.destroy)

    def test_nbft_is_populated(self):
        # Guard against the test passing because the sample tables went away
        nbft_conf = conf.NbftConf()
        self.assertTrue(nbft_conf.dcs)
        self.assertTrue(nbft_conf.iocs)

    def test_nbft_conf_has_no_get_controllers(self):
        # get_controllers() was how the NBFT used to reach _config_ctrls()
        self.assertFalse(hasattr(conf.NbftConf(), 'get_controllers'))


if __name__ == '__main__':
    unittest.main()
