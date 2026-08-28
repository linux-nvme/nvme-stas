# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''Implementation of a singleton pattern'''

import threading


class Singleton(type):
    '''metaclass implementation of a singleton pattern

    Any caller may be the one that creates the instance; everybody else gets
    the one that already exists. That is the point: code with no context of
    its own can reach a singleton without some other component having had to
    initialise a global first.

    Callers that create the singleton pass its arguments, and callers that
    only want to read it pass none. A caller that passes arguments once the
    instance exists gets them checked against the ones it was created with:
    the same arguments are fine (several components may each be prepared to be
    the first one), different arguments are a bug and raise TypeError. Without
    that check the arguments are silently dropped and the caller walks away
    with an instance somebody else configured, which shows up much later in
    whatever those arguments were supposed to configure.

    Note the arguments are compared as they were passed, so Child('x') and
    Child(value='x') count as different even though they call the same
    constructor.
    '''

    # Maps a class to the (instance, args, kwargs) it was created with. The
    # three live in one entry, written with a single assignment, so a caller
    # on the lock-free path can never see an instance whose creation
    # arguments have not been recorded yet, or one that a concurrent
    # destroy() has half removed.
    _instances = {}

    # One lock for every singleton class. Creation happens a handful of times
    # per process, so contention is irrelevant, and a single lock cannot be
    # taken out of order the way per-class locks could. It is reentrant
    # because a singleton's __init__ is free to reach for another singleton;
    # a plain Lock would deadlock the thread against itself.
    _lock = threading.RLock()

    def __call__(cls, *args, **kwargs):
        # Fast path: a singleton is created once and read from everywhere, so
        # a caller that finds an instance never waits for the lock. Publishing
        # the entry with one assignment is what makes this safe - whoever sees
        # the entry sees a fully constructed object.
        created = cls._instances.get(cls)

        if created is None:
            with cls._lock:
                # Somebody may have created it while we waited for the lock.
                created = cls._instances.get(cls)
                if created is None:
                    # This variable declaration is required to force a
                    # strong reference on the instance.
                    instance = super(Singleton, cls).__call__(*args, **kwargs)
                    cls._instances[cls] = (instance, args, kwargs)
                    return instance

        instance, created_args, created_kwargs = created

        if (args or kwargs) and (args, kwargs) != (created_args, created_kwargs):
            raise TypeError(
                '{name}() already exists and was created with different arguments; '
                'the ones given here would be ignored. Use {name}() to get the '
                'existing instance, or {name}.destroy() first to build a new '
                'one.'.format(name=cls.__name__)
            )

        return instance

    def destroy(cls):
        '''Delete a singleton instance.

        This is to be invoked using the derived class Name. It is meant for
        unit tests: nothing in the daemons destroys a singleton, and doing so
        while other threads are running is racy by nature, since they may
        still hold a reference to the instance being dropped.

        For example:

        class Child(Singleton):
            pass

        child1 = Child() # Instantiate singleton
        child2 = Child() # Get a reference to the singleton

        print(f'{child1 is child2}') # True

        Child.destroy()  # Delete the singleton

        print(f'{child1 is child2}') # Still True because child1 and child2 still hold reference to the singleton

        child1 = Child() # Instantiate a new singleton and assign to child1

        print(f'{child1 is child2}') # False
        '''
        with cls._lock:
            cls._instances.pop(cls, None)
