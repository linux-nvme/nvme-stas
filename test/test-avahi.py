#!/usr/bin/python3
import shutil
import socket
import logging
import unittest
import unittest.mock
from staslib import avahi
import dasbus.error
import dasbus.connection
import subprocess

SYSTEMCTL = shutil.which('systemctl')


class Test(unittest.TestCase):
    '''Unit tests for class Avahi'''

    def test_new(self):
        sysbus = dasbus.connection.SystemMessageBus()
        srv = avahi.Avahi(sysbus, lambda: "ok")
        self.assertEqual(srv.info(), {'avahi wake up timer': '60.0s [off]', 'service types': [], 'services': {}})
        self.assertEqual(srv.get_controllers(), [])

        try:
            # Check that the Avahi daemon is running
            subprocess.run([SYSTEMCTL, 'is-active', 'avahi-daemon.service'], check=True)
            self.assertFalse(srv._on_kick_avahi())
        except subprocess.CalledProcessError:
            self.assertTrue(srv._on_kick_avahi())

        with self.assertLogs(logger=logging.getLogger(), level='INFO') as captured:
            srv._avahi_available(None)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].getMessage(), "avahi-daemon service available, zeroconf supported.")
        with self.assertLogs(logger=logging.getLogger(), level='WARN') as captured:
            srv._avahi_unavailable(None)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].getMessage(), "avahi-daemon not available, zeroconf not supported.")
        srv.kill()
        self.assertEqual(srv.info(), {'avahi wake up timer': 'None', 'service types': [], 'services': {}})

    def test_error_paths(self):
        '''Failures that depend on avahi-daemon misbehaving or on a race'''
        sysbus = dasbus.connection.SystemMessageBus()
        srv = avahi.Avahi(sysbus, lambda: "ok")
        dbus_error = dasbus.error.DBusError('injected')

        # avahi-daemon shows up but cannot create a browser: retry later
        broken_avahi = unittest.mock.Mock()
        broken_avahi.ServiceBrowserNew.side_effect = dbus_error
        broken_avahi.ServiceResolverNew.side_effect = dbus_error
        with unittest.mock.patch.object(srv, '_avahi', broken_avahi), unittest.mock.patch.object(
            srv, '_kick_avahi_tmr'
        ) as kick_tmr:
            srv._stypes = {'_nvme-disc._tcp'}
            srv._avahi_available(None)
            kick_tmr.start.assert_called_once_with()

            # A browser for a service type no longer wanted cannot be freed
            browser = unittest.mock.Mock()
            browser.Free.side_effect = dbus_error
            srv._stypes = set()
            srv._service_browsers = {'_nvme-disc._tcp': browser}
            with self.assertLogs(logger=logging.getLogger(), level='DEBUG') as captured:
                self.assertTrue(srv._configure_browsers())
            self.assertIn('Failed to Free() browser', captured.output[-1])
            self.assertEqual(srv._service_browsers, {})

            # A service is discovered but its resolver cannot be created
            args = (socket.if_nametoindex('lo'), avahi.Avahi.PROTO_INET, 'SFSS', '_nvme-disc._tcp', 'local', 0)
            with self.assertLogs(logger=logging.getLogger(), level='WARNING') as captured:
                srv._service_discovered(None, None, None, None, None, args)
            self.assertIn('Failed to create resolver', captured.output[0])
            self.assertEqual(len(srv._services), 1)

        # Resolver timeouts are expected and not reported; other failures are
        with unittest.mock.patch('staslib.avahi.logging.error') as log_error:
            srv._failure_handler(
                None,
                None,
                None,
                avahi.Avahi.DBUS_INTERFACE_SERVICE_RESOLVER,
                None,
                ('org.freedesktop.Avahi.TimeoutError',),
            )
            log_error.assert_not_called()
            srv._failure_handler(
                None, None, None, avahi.Avahi.DBUS_INTERFACE_SERVICE_BROWSER, None, ('org.freedesktop.Avahi.Failure',)
            )
            log_error.assert_called_once()

        srv.kill()

    def test_service_connect_check(self):
        '''Connectivity checks that cannot start, or are pending on close'''
        args = (socket.if_nametoindex('lo'), avahi.Avahi.PROTO_INET, 'SFSS', '_nvme-disc._tcp', 'local', 0)
        service = avahi.Service(args, lambda: None)
        service._data = {'traddr': '127.0.0.1', 'trsvcid': '8009', 'host-iface': 'lo'}

        with unittest.mock.patch('staslib.avahi.gutil.TcpChecker') as checker_cls:
            checker = checker_cls.return_value
            checker.connect.side_effect = RuntimeError('injected')
            with self.assertLogs(logger=logging.getLogger(), level='ERROR') as captured:
                service._connect_check()
            self.assertIn('Unable to verify connectivity', captured.output[0])
            checker.close.assert_called_once_with()
            self.assertIsNone(service._connect_checker)

        pending = unittest.mock.Mock()
        service._connect_checker = pending
        service.close()
        pending.close.assert_called_once_with()
        self.assertIsNone(service._connect_checker)

    def test_ValueRange(self):
        vr = avahi.ValueRange([2, 5, 10, 30])
        self.assertEqual(vr.get_next(), 2)
        self.assertEqual(vr.get_next(), 5)
        self.assertEqual(vr.get_next(), 10)
        self.assertEqual(vr.get_next(), 30)
        # Ceiling: should keep returning last value
        self.assertEqual(vr.get_next(), 30)
        self.assertEqual(vr.get_next(), 30)
        # Reset brings it back to the start
        vr.reset()
        self.assertEqual(vr.get_next(), 2)

    def test_ValueRange_empty(self):
        vr = avahi.ValueRange([])
        # Empty list must not crash; returns 0
        self.assertEqual(vr.get_next(), 0)

    def test__txt2dict(self):
        txt = [
            list('NqN=Starfleet'.encode('utf-8')),
            list('p=tcp'.encode('utf-8')),
        ]
        self.assertEqual(avahi._txt2dict(txt), {'nqn': 'Starfleet', 'p': 'tcp'})

        txt = [
            list('Nqn=Starfleet'.encode('utf-8')),
            list('p='.encode('utf-8')),  # Try with a missing value for p
            list('blah'.encode('utf-8')),  # Missing '='
            list('='.encode('utf-8')),  # Just '='
        ]
        self.assertEqual(avahi._txt2dict(txt), {'nqn': 'Starfleet', 'p': ''})

        txt = [
            [1000, ord('='), 123456],  # Try with non printable characters
        ]
        self.assertEqual(avahi._txt2dict(txt), {})


if __name__ == '__main__':
    unittest.main()
