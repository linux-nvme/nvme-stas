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
from libnvme3 import nvme
from staslib import defs


def get_nbft_files(root_dir=defs.NBFT_SYSFS_PATH):
    """Return a dict mapping file path to parsed NBFT data for every NBFT binary file found under root_dir."""
    pathname = os.path.join(root_dir, defs.NBFT_SYSFS_FILENAME)
    ctx = nvme.GlobalCtx()
    return {fname: nvme.nbft_get(ctx, fname) or {} for fname in glob.iglob(pathname=pathname)}
