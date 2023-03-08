#!/usr/bin/python3
import unittest
from staslib import timeparse


class StasTimeparseUnitTest(unittest.TestCase):
    '''Time parse unit tests'''

    def test_timeparse(self):
        '''Check that timeparse() converts time spans properly'''
        self.assertEqual(timeparse.timeparse('1'), 1)
        self.assertEqual(timeparse.timeparse('1s'), 1)
        self.assertEqual(timeparse.timeparse('1 sec'), 1)
        self.assertEqual(timeparse.timeparse('1 second'), 1)
        self.assertEqual(timeparse.timeparse('1 seconds'), 1)
        self.assertEqual(timeparse.timeparse('1:01'), 61)
        self.assertEqual(timeparse.timeparse('1 day'), 24 * 60 * 60)
        self.assertEqual(timeparse.timeparse('1 hour'), 60 * 60)
        self.assertEqual(timeparse.timeparse('1 min'), 60)
        self.assertEqual(timeparse.timeparse('0.5'), 0.5)
        self.assertEqual(timeparse.timeparse('-1'), -1)
        self.assertEqual(timeparse.timeparse(':22'), 22)
        self.assertEqual(timeparse.timeparse('1 minute, 24 secs'), 84)
        self.assertEqual(timeparse.timeparse('1.2 minutes'), 72)
        self.assertEqual(timeparse.timeparse('1.2 seconds'), 1.2)
        self.assertEqual(timeparse.timeparse('- 1 minute'), -60)
        self.assertEqual(timeparse.timeparse('+ 1 minute'), 60)
        self.assertIsNone(timeparse.timeparse('blah'))


if __name__ == '__main__':
    unittest.main()
