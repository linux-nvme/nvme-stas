# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''STorage Appliance Services'''

__version__ = '@VERSION@'


def __apply_overrides_if_any():
    '''It is possible to override the modules found in this directory by placing
    a module with the same exact file name in a directory named 'override'.
    This can be used, for example, to allow reusing the nvme-stas framework,
    but a different platform that uses a different driver than the linux-nvme
    driver (e.g. SPDK). This function detects if an 'override' directory is
    present, and if so, inserts that directory in the search path as the first
    location to look for modules.
    '''
    import os  # pylint: disable=import-outside-toplevel

    override_dir = os.path.join(__path__[0], 'override')
    if os.path.isdir(override_dir):
        __path__.insert(0, override_dir)


__apply_overrides_if_any()
del __apply_overrides_if_any  # Remove this function from staslib package (once we've used it we need not keep it around)
