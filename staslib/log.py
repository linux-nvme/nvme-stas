# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''nvme-stas logging module'''

import sys
import logging
from staslib import defs


def init(syslog: bool):
    '''Init log module
    @param syslog: True to send messages to the syslog,
                   False to send messages to stdout.
    '''
    log = logging.getLogger()
    log.propagate = False

    if syslog:
        try:
            # Try journal logger first
            import systemd.journal  # pylint: disable=redefined-outer-name,import-outside-toplevel

            handler = systemd.journal.JournalHandler(SYSLOG_IDENTIFIER=defs.PROG_NAME)
        except ModuleNotFoundError:
            # Go back to standard syslog handler
            from logging.handlers import SysLogHandler  # pylint: disable=import-outside-toplevel

            handler = SysLogHandler(address="/dev/log")
            handler.setFormatter(
                logging.Formatter('{}: %(message)s'.format(defs.PROG_NAME))  # pylint: disable=consider-using-f-string
            )
    else:
        # Log to stdout
        handler = logging.StreamHandler(stream=sys.stdout)

    log.addHandler(handler)
    log.setLevel(logging.INFO if syslog else logging.DEBUG)


def level() -> str:
    '''@brief return current log level'''
    log = logging.getLogger()
    return str(logging.getLevelName(log.getEffectiveLevel()))
