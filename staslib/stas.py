# Copyright (c) 2021, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''Library for staf/stac'''

import os
import sys
import ipaddress
import logging

from libnvme import nvme
from staslib import conf, defs, singleton, trid


TRON = False  # Singleton


class Nvme(metaclass=singleton.Singleton):  # pylint: disable=too-few-public-methods
    '''Singleton object to keep libnvme's root and host objects.
    The root and host objects cannot be created too early as
    they depend on configuration files being present. So we
    can't create them as singleton during module import, but
    instead they need to be created once stafd/stacd have started.
    By using this class we ensure that things happen in the right
    sequence.
    '''

    def __init__(self):
        sysconf = conf.SysConf()
        self.root = nvme.root()
        self.host = nvme.host(self.root, sysconf.hostnqn, sysconf.hostid, sysconf.hostsymname)


# ******************************************************************************
def check_if_allowed_to_continue():
    '''@brief Let's perform some basic checks before going too far. There are
           a few pre-requisites that need to be met before this program
           is allowed to proceed:

             1) The program needs to have root privileges
             2) The nvme-tcp kernel module must be loaded

    @return This function will only return if all conditions listed above
            are met. Otherwise the program exits.
    '''
    # 1) Check root privileges
    if os.geteuid() != 0:
        sys.exit(f'Permission denied. You need root privileges to run {defs.PROG_NAME}.')

    # 2) Check that nvme-tcp kernel module is running
    if not os.path.exists('/dev/nvme-fabrics'):
        # There's no point going any further if the kernel module hasn't been loaded
        sys.exit('Fatal error: missing nvme-tcp kernel module')


# ******************************************************************************
def trace_control(tron: bool):
    '''@brief Allows changing debug level in real time. Setting tron to True
    enables full tracing.
    '''
    global TRON  # pylint: disable=global-statement
    TRON = tron
    log = logging.getLogger()
    log.setLevel(logging.DEBUG if TRON else logging.INFO)
    Nvme().root.log_level("debug" if TRON else "err")


# ******************************************************************************
def cid_from_dlpe(dlpe, host_traddr, host_iface):
    '''@brief Take a Discovery Log Page Entry and return a Controller ID as a dict.'''
    return {
        'transport':   dlpe['trtype'],
        'traddr':      dlpe['traddr'],
        'trsvcid':     dlpe['trsvcid'],
        'host-traddr': host_traddr,
        'host-iface':  host_iface,
        'subsysnqn':   dlpe['subnqn'],
    }


# ******************************************************************************
def _blacklisted(blacklisted_ctrl_list, controller):
    '''@brief Check if @controller is black-listed.'''
    for blacklisted_ctrl in blacklisted_ctrl_list:
        test_results = [val == controller.get(key, None) for key, val in blacklisted_ctrl.items()]
        if all(test_results):
            return True
    return False


# ******************************************************************************
def remove_blacklisted(controllers: list):
    '''@brief Remove black-listed controllers from the list of controllers.'''
    blacklisted_ctrl_list = conf.SvcConf().get_blacklist()
    if blacklisted_ctrl_list:
        logging.debug('remove_blacklisted()               - blacklisted_ctrl_list = %s', blacklisted_ctrl_list)
        controllers = [controller for controller in controllers if not _blacklisted(blacklisted_ctrl_list, controller)]
    return controllers


# ******************************************************************************
def remove_invalid_addresses(controllers: list):
    '''@brief Remove controllers with invalid addresses from the list of controllers.'''
    valid_controllers = list()
    for controller in controllers:
        if controller.get('transport') in ('tcp', 'rdma'):
            # Let's make sure that traddr is
            # syntactically a valid IPv4 or IPv6 address.
            traddr = controller.get('traddr')
            try:
                ip = ipaddress.ip_address(traddr)
            except ValueError:
                logging.warning('%s IP address is not valid', trid.TID(controller))
                continue

            service_conf = conf.SvcConf()
            if ip.version not in service_conf.ip_family:
                logging.debug(
                    '%s ignored because IPv%s is disabled in %s',
                    trid.TID(controller),
                    ip.version,
                    service_conf.conf_file,
                )
                continue

        # At some point, need to validate FC addresses as well...

        valid_controllers.append(controller)

    return valid_controllers
