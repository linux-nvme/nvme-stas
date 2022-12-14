# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>

'''A collection of IP address and network interface utilities'''

import socket
import logging
import ipaddress
from staslib import conf

RTM_NEWADDR = 20
RTM_GETADDR = 22
NLM_F_REQUEST = 0x01
NLM_F_ROOT = 0x100
NLMSG_DONE = 3
IFLA_ADDRESS = 1
NLMSGHDR_SZ = 16
IFADDRMSG_SZ = 8
RTATTR_SZ = 4

# Netlink request (Get address command)
GETADDRCMD = (
    # BEGIN: struct nlmsghdr
    b'\0' * 4  # nlmsg_len (placeholder - actual length calculated below)
    + (RTM_GETADDR).to_bytes(2, byteorder='little', signed=False)  # nlmsg_type
    + (NLM_F_REQUEST | NLM_F_ROOT).to_bytes(2, byteorder='little', signed=False)  # nlmsg_flags
    + b'\0' * 2  # nlmsg_seq
    + b'\0' * 2  # nlmsg_pid
    # END: struct nlmsghdr
    + b'\0' * 8  # struct ifaddrmsg
)
GETADDRCMD = len(GETADDRCMD).to_bytes(4, byteorder='little') + GETADDRCMD[4:]  # nlmsg_len

# ******************************************************************************
def get_ipaddress_obj(ipaddr):
    '''@brief Return a IPv4Address or IPv6Address depending on whether @ipaddr
    is a valid IPv4 or IPv6 address. Return None otherwise.'''
    try:
        ip = ipaddress.ip_address(ipaddr)
    except ValueError:
        return None

    return ip


# ******************************************************************************
def _data_matches_ip(data_family, data, ip):
    if data_family == socket.AF_INET:
        try:
            other_ip = ipaddress.IPv4Address(data)
        except ValueError:
            return False
        if ip.version == 6:
            ip = ip.ipv4_mapped
    elif data_family == socket.AF_INET6:
        try:
            other_ip = ipaddress.IPv6Address(data)
        except ValueError:
            return False
        if ip.version == 4:
            other_ip = other_ip.ipv4_mapped
    else:
        return False

    return other_ip == ip


# ******************************************************************************
def iface_of(src_addr):
    '''@brief Find the interface that has src_addr as one of its assigned IP addresses.
    @param src_addr: The IP address to match
    @type src_addr: Instance of ipaddress.IPv4Address or ipaddress.IPv6Address
    '''
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW) as sock:
        sock.sendall(GETADDRCMD)
        nlmsg = sock.recv(8192)
        nlmsg_idx = 0
        while True:
            if nlmsg_idx >= len(nlmsg):
                nlmsg += sock.recv(8192)

            nlmsg_type = int.from_bytes(nlmsg[nlmsg_idx + 4 : nlmsg_idx + 6], byteorder='little', signed=False)
            if nlmsg_type == NLMSG_DONE:
                break

            if nlmsg_type != RTM_NEWADDR:
                break

            nlmsg_len = int.from_bytes(nlmsg[nlmsg_idx : nlmsg_idx + 4], byteorder='little', signed=False)
            if nlmsg_len % 4:  # Is msg length not a multiple of 4?
                break

            ifaddrmsg_indx = nlmsg_idx + NLMSGHDR_SZ
            ifa_family = nlmsg[ifaddrmsg_indx]
            ifa_index = int.from_bytes(nlmsg[ifaddrmsg_indx + 4 : ifaddrmsg_indx + 8], byteorder='little', signed=False)

            rtattr_indx = ifaddrmsg_indx + IFADDRMSG_SZ
            while rtattr_indx < (nlmsg_idx + nlmsg_len):
                rta_len = int.from_bytes(nlmsg[rtattr_indx : rtattr_indx + 2], byteorder='little', signed=False)
                rta_type = int.from_bytes(nlmsg[rtattr_indx + 2 : rtattr_indx + 4], byteorder='little', signed=False)
                if rta_type == IFLA_ADDRESS:
                    data = nlmsg[rtattr_indx + RTATTR_SZ : rtattr_indx + rta_len]
                    if _data_matches_ip(ifa_family, data, src_addr):
                        return socket.if_indextoname(ifa_index)

                rta_len = (rta_len + 3) & ~3  # Round up to multiple of 4
                rtattr_indx += rta_len  # Move to next rtattr

            nlmsg_idx += nlmsg_len  # Move to next Netlink message

    return ''


# ******************************************************************************
def get_interface(src_addr):
    '''Get interface for given source address
    @param src_addr: The source address
    @type src_addr: str
    '''
    if not src_addr:
        return ''

    src_addr = src_addr.split('%')[0]  # remove scope-id (if any)
    src_addr = get_ipaddress_obj(src_addr)
    return '' if src_addr is None else iface_of(src_addr)


# ******************************************************************************
def remove_invalid_addresses(controllers: list):
    '''@brief Remove controllers with invalid addresses from the list of controllers.
    @param controllers: List of TIDs
    '''
    service_conf = conf.SvcConf()
    valid_controllers = list()
    for controller in controllers:
        if controller.transport in ('tcp', 'rdma'):
            # Let's make sure that traddr is
            # syntactically a valid IPv4 or IPv6 address.
            ip = get_ipaddress_obj(controller.traddr)
            if ip is None:
                logging.warning('%s IP address is not valid', controller)
                continue

            # Let's make sure the address family is enabled.
            if ip.version not in service_conf.ip_family:
                logging.debug(
                    '%s ignored because IPv%s is disabled in %s',
                    controller,
                    ip.version,
                    service_conf.conf_file,
                )
                continue

            valid_controllers.append(controller)

        elif controller.transport in ('fc', 'loop'):
            # At some point, need to validate FC addresses as well...
            valid_controllers.append(controller)

        else:
            logging.warning('Invalid transport %s', controller.transport)

    return valid_controllers
