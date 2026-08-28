#!/usr/bin/python3
import time
import threading
import unittest
from staslib import singleton


class Dummy(metaclass=singleton.Singleton):
    '''Stand-in for the real singletons (SvcConf, SysConf, ...)'''

    def __init__(self, value=None):
        self.value = value


class SlowDummy(metaclass=singleton.Singleton):
    '''__init__ is slow on purpose, to widen the window for a race'''

    instances_created = 0

    def __init__(self, value=None):
        time.sleep(0.05)
        SlowDummy.instances_created += 1
        self.value = value


class Test(unittest.TestCase):
    '''Unit tests for the Singleton metaclass'''

    def setUp(self):
        Dummy.destroy()  # Make sure singleton does not exist
        self.addCleanup(Dummy.destroy)

    def test_same_instance_is_returned(self):
        self.assertIs(Dummy(), Dummy())

    def test_first_call_takes_the_arguments(self):
        self.assertEqual(Dummy('first').value, 'first')

    def test_existing_instance_is_reachable_without_arguments(self):
        Dummy('first')
        self.assertEqual(Dummy().value, 'first')

    def test_same_arguments_are_allowed(self):
        # Several components may each be prepared to be the one that creates
        # the singleton. Whoever gets there first wins, and the others are
        # handed the instance they would have built themselves.
        first = Dummy('same')
        self.assertIs(Dummy('same'), first)
        self.assertIs(Dummy(), first)

    def test_same_keyword_arguments_are_allowed(self):
        first = Dummy(value='same')
        self.assertIs(Dummy(value='same'), first)

    def test_different_arguments_are_refused(self):
        # Dropping them silently hands the caller an instance somebody else
        # configured. The symptom then shows up much later, in whatever the
        # ignored arguments were supposed to configure.
        Dummy('first')
        with self.assertRaises(TypeError):
            Dummy('second')
        with self.assertRaises(TypeError):
            Dummy(value='second')

    def test_arguments_are_compared_as_passed(self):
        # Positional and keyword forms of the same call are not equal. The
        # check is deliberately literal rather than signature-aware.
        Dummy('first')
        with self.assertRaises(TypeError):
            Dummy(value='first')

    def test_arguments_are_refused_against_an_instance_created_without_any(self):
        Dummy()
        with self.assertRaises(TypeError):
            Dummy('first')

    def test_refusing_the_arguments_leaves_the_instance_alone(self):
        first = Dummy('first')
        with self.assertRaises(TypeError):
            Dummy('second')
        self.assertIs(Dummy(), first)
        self.assertEqual(Dummy().value, 'first')

    def test_destroy_allows_new_arguments(self):
        Dummy('first')
        Dummy.destroy()
        self.assertEqual(Dummy('second').value, 'second')

    def test_concurrent_creation_builds_exactly_one_instance(self):
        '''Any thread may be the one that creates the singleton, but only one
        of them may actually build it.'''
        threads_count = 8

        SlowDummy.destroy()
        SlowDummy.instances_created = 0
        self.addCleanup(SlowDummy.destroy)

        barrier = threading.Barrier(threads_count)
        results = []
        results_lock = threading.Lock()

        def create():
            barrier.wait()  # Let every thread pile into __call__ at once
            instance = SlowDummy('same')
            with results_lock:
                results.append(instance)

        threads = [threading.Thread(target=create) for _ in range(threads_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(SlowDummy.instances_created, 1)
        self.assertEqual(len(results), threads_count)
        self.assertEqual(len({id(instance) for instance in results}), 1)


if __name__ == '__main__':
    unittest.main()
