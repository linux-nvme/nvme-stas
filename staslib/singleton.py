# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''Implementation of a singleton pattern'''


class Singleton(type):
    '''metaclass implementation of a singleton pattern'''

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            # This variable declaration is required to force a
            # strong reference on the instance.
            instance = super(Singleton, cls).__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]

    def destroy(cls):
        '''Delete a singleton instance.

        This is to be invoked using the derived class Name.

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
        cls._instances.pop(cls, None)
