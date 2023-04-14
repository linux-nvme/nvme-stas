#!/usr/bin/python3
import unittest
from staslib import gutil


class GutilUnitTest(unittest.TestCase):
    '''Run unit test for gutil.py'''

    def _on_success(self, op_obj: gutil.AsyncTask, data):
        op_obj.kill()

    def _on_fail(self, op_obj: gutil.AsyncTask, err, fail_cnt):
        op_obj.kill()

    def _operation(self, data):
        return data

    def test_AsyncTask(self):
        op = gutil.AsyncTask(self._on_success, self._on_fail, self._operation, 'hello')

        self.assertIsInstance(str(op), str)
        self.assertEqual(op.as_dict(), {'fail count': 0, 'completed': None, 'alive': True})

        op.retry(10)
        self.assertIsNotNone(op.as_dict().get('retry timer'))

        errmsg = 'something scarry happened'
        op._errmsg = errmsg
        self.assertEqual(op.as_dict().get('error'), errmsg)


if __name__ == '__main__':
    unittest.main()
