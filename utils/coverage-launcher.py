#!/usr/bin/python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026, Dell Inc. or its subsidiaries.  All rights reserved.
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>

'''Run stafd or stacd for the coverage test with a shorter EPCSD poll.

epcsd-poll-interval-minutes accepts nothing below 1, so a coverage phase that
waits for a parked DC's poll waits a full minute. Here that shortest interval
lasts 10 seconds instead; any longer one is left as configured. The daemons
themselves know nothing of this.

usage: coverage run coverage-launcher.py DAEMON [ARGS...]
'''

import os
import sys
import runpy

SHORTEST_INTERVAL_SEC = 60  # epcsd-poll-interval-minutes = 1
COVERAGE_INTERVAL_SEC = 10


def main():
    # Become the daemon before importing staslib: defs.PROG_NAME, which the
    # daemon logs under, is taken from sys.argv[0] at import time.
    sys.argv = sys.argv[1:]
    sys.path[0] = os.path.dirname(os.path.abspath(sys.argv[0]))

    from staslib import conf  # pylint: disable=import-outside-toplevel

    epcsd_poll_interval_sec = conf.SvcConf.epcsd_poll_interval_sec

    def shortened_epcsd_poll_interval_sec(self):
        interval = epcsd_poll_interval_sec.fget(self)
        return COVERAGE_INTERVAL_SEC if interval == SHORTEST_INTERVAL_SEC else interval

    conf.SvcConf.epcsd_poll_interval_sec = property(shortened_epcsd_poll_interval_sec)

    runpy.run_path(sys.argv[0], run_name='__main__')


main()
