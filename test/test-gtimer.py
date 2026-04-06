#!/usr/bin/python3
import unittest
from staslib import gutil


class Test(unittest.TestCase):
    '''Unit tests for class GTimer'''

    def test_new_timer(self):
        tmr = gutil.GTimer(interval_sec=5)
        self.assertEqual(tmr.get_timeout(), 5)
        self.assertEqual(tmr.time_remaining(), 0)
        self.assertEqual(str(tmr), '5.0s [off]')
        tmr.set_timeout(new_interval_sec=18)
        self.assertEqual(tmr.get_timeout(), 18)
        self.assertEqual(tmr.time_remaining(), 0)

    def test_callback(self):
        tmr = gutil.GTimer(interval_sec=1, user_cback=lambda: "ok")
        self.assertEqual(tmr._callback(), "ok")
        tmr.set_callback(user_cback=lambda: "notok")
        self.assertEqual(tmr._callback(), "notok")
        tmr.kill()
        self.assertEqual(tmr._user_cback, None)
        self.assertRaises(TypeError, tmr._user_cback)

    def test_start_timer(self):
        tmr = gutil.GTimer(interval_sec=1, user_cback=lambda: "ok")
        self.assertEqual(str(tmr), '1.0s [off]')
        tmr.start()
        self.assertNotEqual(tmr.time_remaining(), 0)
        self.assertNotEqual(str(tmr), '1.0s [off]')

    def test_clear(self):
        tmr = gutil.GTimer(interval_sec=1, user_cback=lambda: "ok")
        tmr.start()
        tmr.clear()
        self.assertEqual(tmr.time_remaining(), 0)
        self.assertEqual(str(tmr), '1.0s [0s]')

    def test_callback_source_remove_clears_source(self):
        from gi.repository import GLib

        tmr = gutil.GTimer(interval_sec=1, user_cback=lambda: GLib.SOURCE_REMOVE)
        tmr.start()
        self.assertIsNotNone(tmr._source)
        result = tmr._callback()
        self.assertEqual(result, GLib.SOURCE_REMOVE)
        # _callback() must clear _source when the user callback returns SOURCE_REMOVE
        self.assertIsNone(tmr._source)

    def test_restart_running_timer_reschedules_in_place(self):
        from gi.repository import GLib

        tmr = gutil.GTimer(interval_sec=10, user_cback=lambda: GLib.SOURCE_REMOVE)
        tmr.start()
        self.assertIsNotNone(tmr._source)
        source_before = tmr._source
        # start() on an already-running timer must reuse the existing GLib source
        # (via set_ready_time) rather than creating a new one.
        tmr.start()
        self.assertIs(tmr._source, source_before)
        tmr.kill()


if __name__ == '__main__':
    unittest.main()
