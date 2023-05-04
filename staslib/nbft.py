# Copyright (c) 2023, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''Code used to access the NVMe Boot Firmware Tables'''

import os
import glob
import logging
from libnvme import nvme
from staslib import defs


def get_nbft_files(root_dir=defs.NBFT_SYSFS_PATH):
    """Return a dictionary containing the NBFT data for all the NBFT binary files located in @root_dir"""
    if not defs.HAS_NBFT_SUPPORT:
        logging.warning(
            "libnvme-%s does not have NBFT support. Please upgrade libnvme.",
            defs.LIBNVME_VERSION,
        )
        return {}

    pathname = os.path.join(root_dir, defs.NBFT_SYSFS_FILENAME)
    return {fname: nvme.nbft_get(fname) or {} for fname in glob.iglob(pathname=pathname)}  # pylint: disable=no-member
