#!/usr/bin/python3
import logging
import unittest
import subprocess
from pyfakefs.fake_filesystem_unittest import TestCase
from staslib import log

try:
    cmd = ['python3', '-c', 'import systemd.journal; print(f"{systemd.journal.__file__}")']
    p = subprocess.run(cmd, stdout=subprocess.PIPE, check=True)
    JOURNAL_MODULE  = p.stdout.decode().strip()
except subprocess.CalledProcessError:
    JOURNAL_MODULE  = None

class StaslibLogTest(TestCase):
    '''Test for log.py module'''

    def setUp(self):
        self.setUpPyfakefs()

#    def tearDown(self):
#        # No longer need self.tearDownPyfakefs()
#        pass
#
#    @classmethod
#    def setUpClass(cls):
#        pass
#
#    @classmethod
#    def tearDownClass(cls):
#        pass

    def test_log_with_syslog_handler(self):
        '''Check that we can set the handler to SysLogHandler'''
        if JOURNAL_MODULE is not None:
            # We need to mask the real journal module by creating
            # a fake journal module with invalid contents
            self.fs.create_file(JOURNAL_MODULE, contents='import bzgatejgtlatdfke-094n\n')

        log.init(syslog=False)
        self.assertEqual(log.level(), 'DEBUG')
        logging.shutdown()


    def test_log_with_systemd_journal(self):
        '''Check that we can set the handler to journal (needs python-systemd to be installed)'''
        if JOURNAL_MODULE is not None:
            log.init(syslog=False)
            self.assertEqual(log.level(), 'DEBUG')
            logging.shutdown()


    def test_log_with_stdout(self):
        '''Check that we can set the handler to SysLogHandler'''
        log.init(syslog=True)
        self.assertEqual(log.level(), 'INFO')
        logging.shutdown()


if __name__ == '__main__':
    unittest.main()
