#!/usr/bin/python3
import os
import unittest
from staslib import stas


class Test(unittest.TestCase):
    '''Unit tests for class GTimer'''

    def test_new_timer(self):
        tmr = stas.GTimer(interval_sec=5)
        self.assertEqual(tmr.get_timeout(), 5)
        self.assertEqual(tmr.time_remaining(), 0)
        self.assertEqual(str(tmr), '5.0s [off]')
        tmr.set_timeout(new_interval_sec=18)
        self.assertEqual(tmr.get_timeout(), 18)
        self.assertEqual(tmr.time_remaining(), 0)

    def test_callback(self):
        tmr = stas.GTimer(interval_sec=1, user_cback=lambda:"ok")
        self.assertEqual(tmr._callback(), "ok")
        tmr.set_callback(user_cback=lambda:"notok")
        self.assertEqual(tmr._callback(), "notok")
        tmr.kill()
        self.assertEqual(tmr._user_cback, None)
        self.assertRaises(TypeError, tmr._user_cback)

    def test_start_timer(self):
        tmr = stas.GTimer(interval_sec=1, user_cback=lambda:"ok")
        self.assertEqual(str(tmr), '1.0s [off]')
        tmr.start()
        self.assertNotEqual(tmr.time_remaining(), 0)
        self.assertNotEqual(str(tmr), '1.0s [off]')

if __name__ == '__main__':
    unittest.main()
