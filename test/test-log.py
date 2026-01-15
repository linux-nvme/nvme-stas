#!/usr/bin/python3
import logging
import unittest
from pyfakefs.fake_filesystem_unittest import TestCase
from staslib import log


class StaslibLogTest(TestCase):
    '''Test for log.py module'''

    def setUp(self):
        self.setUpPyfakefs()

    def test_log_with_systemd_journal(self):
        '''Check that we can set the handler to systemd.journal.JournalHandler'''
        try:
            # We can't proceed with this test if the
            # module systemd.journal is not installed.
            import systemd.journal
        except ModuleNotFoundError:
            return

        log.init(syslog=True)

        logger = logging.getLogger()
        handler = logger.handlers[-1]

        self.assertIsInstance(handler, systemd.journal.JournalHandler)

        self.assertEqual(log.level(), 'INFO')

        log.set_level_from_tron(tron=True)
        self.assertEqual(log.level(), 'DEBUG')
        log.set_level_from_tron(tron=False)
        self.assertEqual(log.level(), 'INFO')

        logger.removeHandler(handler)
        handler.close()

    def test_log_with_syslog_handler(self):
        '''Check that we can set the handler to logging.handlers.SysLogHandler'''
        try:
            # The log.py module uses systemd.journal.JournalHandler() as the
            # default logging handler (if present). Therefore, in order to force
            # log.py to use SysLogHandler as the handler, we need to mock
            # systemd.journal.JournalHandler() with an invalid class.
            import systemd.journal
        except ModuleNotFoundError:
            original_handler = None
        else:

            class MockJournalHandler:
                def __new__(cls, *args, **kwargs):
                    raise ModuleNotFoundError

            original_handler = systemd.journal.JournalHandler
            systemd.journal.JournalHandler = MockJournalHandler

        log.init(syslog=True)

        logger = logging.getLogger()
        handler = logger.handlers[-1]

        self.assertIsInstance(handler, logging.handlers.SysLogHandler)

        self.assertEqual(log.level(), 'INFO')

        log.set_level_from_tron(tron=True)
        self.assertEqual(log.level(), 'DEBUG')
        log.set_level_from_tron(tron=False)
        self.assertEqual(log.level(), 'INFO')

        logger.removeHandler(handler)
        handler.close()

        if original_handler is not None:
            # Restore original systemd.journal.JournalHandler()
            systemd.journal.JournalHandler = original_handler

    def test_log_with_stdout(self):
        '''Check that we can set the handler to logging.StreamHandler (i.e. stdout)'''
        log.init(syslog=False)

        logger = logging.getLogger()
        handler = logger.handlers[-1]

        self.assertIsInstance(handler, logging.StreamHandler)

        self.assertEqual(log.level(), 'DEBUG')

        log.set_level_from_tron(tron=True)
        self.assertEqual(log.level(), 'DEBUG')
        log.set_level_from_tron(tron=False)
        self.assertEqual(log.level(), 'INFO')

        logger.removeHandler(handler)
        handler.close()


if __name__ == '__main__':
    unittest.main()
