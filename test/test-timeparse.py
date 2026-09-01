#!/usr/bin/python3
import math
import unittest
from staslib import timeparse

USEC_PER_SEC = timeparse.USEC_PER_SEC
MSEC = timeparse.USEC_PER_MSEC / USEC_PER_SEC
SEC = 1
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR
WEEK = timeparse.USEC_PER_WEEK // USEC_PER_SEC
MONTH = timeparse.USEC_PER_MONTH // USEC_PER_SEC
YEAR = timeparse.USEC_PER_YEAR // USEC_PER_SEC


class StasTimeparseUnitTest(unittest.TestCase):
    '''Time parse unit tests.

    timeparse() must accept exactly what systemd's parse_time() accepts, and
    mean the same thing by it, because nvme-stas and nvme-discoverd share the
    dc-giveup-timeout encoding. These cases mirror nvme-cli's own
    time-span tests.'''

    def test_units(self):
        '''Every suffix in the table, so a future edit that drops one is
        caught here rather than by a user whose config stops parsing'''
        self.assertEqual(timeparse.timeparse('1usec'), 1 / USEC_PER_SEC)
        self.assertEqual(timeparse.timeparse('1us'), 1 / USEC_PER_SEC)
        self.assertEqual(timeparse.timeparse('1μs'), 1 / USEC_PER_SEC)  # U+03BC
        self.assertEqual(timeparse.timeparse('1µs'), 1 / USEC_PER_SEC)  # U+00B5
        self.assertEqual(timeparse.timeparse('1msec'), MSEC)
        self.assertEqual(timeparse.timeparse('500ms'), 500 * MSEC)
        self.assertEqual(timeparse.timeparse('5s'), 5 * SEC)
        self.assertEqual(timeparse.timeparse('5sec'), 5 * SEC)
        self.assertEqual(timeparse.timeparse('5second'), 5 * SEC)
        self.assertEqual(timeparse.timeparse('5seconds'), 5 * SEC)
        self.assertEqual(timeparse.timeparse('1min'), MINUTE)
        self.assertEqual(timeparse.timeparse('1minute'), MINUTE)
        self.assertEqual(timeparse.timeparse('1minutes'), MINUTE)
        self.assertEqual(timeparse.timeparse('1hr'), HOUR)
        self.assertEqual(timeparse.timeparse('1hour'), HOUR)
        self.assertEqual(timeparse.timeparse('1hours'), HOUR)
        self.assertEqual(timeparse.timeparse('1d'), DAY)
        self.assertEqual(timeparse.timeparse('1day'), DAY)
        self.assertEqual(timeparse.timeparse('1days'), DAY)
        self.assertEqual(timeparse.timeparse('1w'), WEEK)
        self.assertEqual(timeparse.timeparse('1week'), WEEK)
        self.assertEqual(timeparse.timeparse('1weeks'), WEEK)
        self.assertEqual(timeparse.timeparse('1month'), MONTH)
        self.assertEqual(timeparse.timeparse('1months'), MONTH)
        self.assertEqual(timeparse.timeparse('1y'), YEAR)
        self.assertEqual(timeparse.timeparse('1year'), YEAR)
        self.assertEqual(timeparse.timeparse('1years'), YEAR)

    def test_the_case_of_m_matters(self):
        '''"M" is months and "m" is minutes'''
        self.assertEqual(timeparse.timeparse('1M'), MONTH)
        self.assertEqual(timeparse.timeparse('1m'), MINUTE)

    def test_the_approximations_are_systemds(self):
        '''A month is 30.44 days and a year is 365.25 days. Rounding either
        one would make a span mean something else here than in a unit file.'''
        self.assertEqual(MONTH, 2629800)
        self.assertEqual(YEAR, 31557600)

    def test_infinity(self):
        self.assertEqual(timeparse.timeparse('infinity'), math.inf)
        self.assertEqual(timeparse.timeparse('  infinity  '), math.inf)

    def test_zero(self):
        self.assertEqual(timeparse.timeparse('0'), 0)

    def test_a_unit_less_value_is_seconds(self):
        '''"72" is 72 seconds, not 72 hours'''
        self.assertEqual(timeparse.timeparse('72'), 72 * SEC)

    def test_terms_are_summed(self):
        '''With or without separating whitespace'''
        self.assertEqual(timeparse.timeparse('72hours'), 72 * HOUR)
        self.assertEqual(timeparse.timeparse('72 h'), 72 * HOUR)
        self.assertEqual(timeparse.timeparse('3 days 5 hours'), 3 * DAY + 5 * HOUR)
        self.assertEqual(timeparse.timeparse('3d5h'), 3 * DAY + 5 * HOUR)
        self.assertEqual(timeparse.timeparse('1h30m'), HOUR + 30 * MINUTE)
        self.assertEqual(timeparse.timeparse('  2 d  '), 2 * DAY)

    def test_fractions(self):
        self.assertEqual(timeparse.timeparse('1.5h'), HOUR + 30 * MINUTE)
        self.assertEqual(timeparse.timeparse('0.5s'), 500 * MSEC)
        self.assertEqual(timeparse.timeparse('12.34 .56'), 12.9)

    def test_a_whole_number_of_seconds_is_an_int(self):
        '''The value ends up in GLib timers, which want a number'''
        self.assertIsInstance(timeparse.timeparse('1'), int)
        self.assertIsInstance(timeparse.timeparse('1.5h'), int)
        self.assertIsInstance(timeparse.timeparse('500ms'), float)

    def test_syntax_errors_are_rejected(self):
        self.assertIsNone(timeparse.timeparse(''))
        self.assertIsNone(timeparse.timeparse('   '))
        self.assertIsNone(timeparse.timeparse('hours'))
        self.assertIsNone(timeparse.timeparse('1hoge'))
        self.assertIsNone(timeparse.timeparse('12.34.56'))
        self.assertIsNone(timeparse.timeparse('3.sec'))
        self.assertIsNone(timeparse.timeparse('infinityx'))
        self.assertIsNone(timeparse.timeparse('blah'))

    def test_negatives_are_rejected(self):
        '''Not clamped: say "infinity" instead'''
        self.assertIsNone(timeparse.timeparse('-1'))
        self.assertIsNone(timeparse.timeparse('-0'))
        self.assertIsNone(timeparse.timeparse('1h -1m'))

    def test_overflow_is_rejected(self):
        '''On the multiply, and on the sum of two valid terms'''
        self.assertIsNone(timeparse.timeparse('100000000000000y'))
        self.assertIsNone(timeparse.timeparse('300000y 300000y'))

    def test_pytimeparse_syntax_is_gone(self):
        '''This module used to be pytimeparse, which accepted colon notation,
        comma-separated terms and signs. systemd accepts none of the three,
        and a span must mean the same thing in both daemons.'''
        self.assertIsNone(timeparse.timeparse('1:30'))
        self.assertIsNone(timeparse.timeparse('1:01'))
        self.assertIsNone(timeparse.timeparse(':22'))
        self.assertIsNone(timeparse.timeparse('1 minute, 24 secs'))
        self.assertIsNone(timeparse.timeparse('- 1 minute'))
        self.assertIsNone(timeparse.timeparse('+ 1 minute'))

    def test_a_non_string_is_rejected(self):
        '''conf.py hands us whatever the config file yielded, including None
        when the key was empty'''
        self.assertIsNone(timeparse.timeparse(None))
        self.assertIsNone(timeparse.timeparse(72))


if __name__ == '__main__':
    unittest.main()
