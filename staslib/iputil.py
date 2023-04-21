# Copyright (c) 2022, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>

'''A collection of IP address and network interface utilities'''

import struct
import socket
import ipaddress

RTM_BASE = 16
RTM_GETLINK = 18
RTM_NEWADDR = 20
RTM_GETADDR = 22
NLM_F_REQUEST = 0x01
NLM_F_ROOT = 0x100
NLMSG_DONE = 3
NLMSG_HDRLEN = 16
IFADDRMSG_SZ = 8
IFINFOMSG_SZ = 16
ARPHRD_ETHER = 1
ARPHRD_LOOPBACK = 772
NLMSG_LENGTH = lambda msg_len: msg_len + NLMSG_HDRLEN  # pylint: disable=unnecessary-lambda-assignment

RTATTR_SZ = 4
RTA_ALIGN = lambda length: ((length + 3) & ~3)  # pylint: disable=unnecessary-lambda-assignment
IFLA_ADDRESS = 1


def _nlmsghdr(nlmsg_type, nlmsg_flags, nlmsg_seq, nlmsg_pid, msg_len: int):
    '''Implement this C struct:
    struct nlmsghdr {
        __u32 nlmsg_len;   /* Length of message including header */
        __u16 nlmsg_type;  /* Message content */
        __u16 nlmsg_flags; /* Additional flags */
        __u32 nlmsg_seq;   /* Sequence number */
        __u32 nlmsg_pid;   /* Sending process port ID */
    };
    '''
    return struct.pack('<LHHLL', NLMSG_LENGTH(msg_len), nlmsg_type, nlmsg_flags, nlmsg_seq, nlmsg_pid)


def _ifaddrmsg(family=0, prefixlen=0, flags=0, scope=0, index=0):
    '''Implement this C struct:
    struct ifaddrmsg {
        __u8   ifa_family;
        __u8   ifa_prefixlen;  /* The prefix length        */
        __u8   ifa_flags;      /* Flags            */
        __u8   ifa_scope;      /* Address scope        */
        __u32  ifa_index;      /* Link index           */
    };
    '''
    return struct.pack('<BBBBL', family, prefixlen, flags, scope, index)


def _ifinfomsg(family=0, dev_type=0, index=0, flags=0, change=0):
    '''Implement this C struct:
    struct ifinfomsg {
        unsigned char   ifi_family; /* AF_UNSPEC */
        unsigned char   __ifi_pad;
        unsigned short  ifi_type;   /* Device type: ARPHRD_* */
        int             ifi_index;  /* Interface index */
        unsigned int    ifi_flags;  /* Device flags: IFF_* */
        unsigned int    ifi_change; /* change mask: IFF_* */
    };
    '''
    return struct.pack('<BBHiII', family, 0, dev_type, index, flags, change)


def _nlmsg(nlmsg_type, nlmsg_flags, msg: bytes):
    '''Build a Netlink message'''
    return _nlmsghdr(nlmsg_type, nlmsg_flags, 0, 0, len(msg)) + msg


# Netlink request (Get address command)
GETADDRCMD = _nlmsg(RTM_GETADDR, NLM_F_REQUEST | NLM_F_ROOT, _ifaddrmsg())

# Netlink request (Get address command)
GETLINKCMD = _nlmsg(RTM_GETLINK, NLM_F_REQUEST | NLM_F_ROOT, _ifinfomsg(family=socket.AF_UNSPEC, change=0xFFFFFFFF))


# ******************************************************************************
def _data_matches_mac(data, mac):
    return mac.lower() == ':'.join([f'{x:02x}' for x in data[0:6]])


def mac2iface(mac: str):  # pylint: disable=too-many-locals
    '''@brief Find the interface that has @mac as its assigned MAC address.
    @param mac: The MAC address to match
    '''
    with socket.socket(family=socket.AF_NETLINK, type=socket.SOCK_RAW, proto=socket.NETLINK_ROUTE) as sock:
        sock.sendall(GETLINKCMD)
        nlmsg = sock.recv(8192)
        nlmsg_idx = 0
        while True:  # pylint: disable=too-many-nested-blocks
            if nlmsg_idx >= len(nlmsg):
                nlmsg += sock.recv(8192)

            nlmsghdr = nlmsg[nlmsg_idx : nlmsg_idx + NLMSG_HDRLEN]
            nlmsg_len, nlmsg_type, _, _, _ = struct.unpack('<LHHLL', nlmsghdr)

            if nlmsg_type == NLMSG_DONE:
                break

            if nlmsg_type == RTM_BASE:
                msg_indx = nlmsg_idx + NLMSG_HDRLEN
                msg = nlmsg[msg_indx : msg_indx + IFINFOMSG_SZ]  # ifinfomsg
                _, _, ifi_type, ifi_index, _, _ = struct.unpack('<BBHiII', msg)

                if ifi_type in (ARPHRD_LOOPBACK, ARPHRD_ETHER):
                    rtattr_indx = msg_indx + IFINFOMSG_SZ
                    while rtattr_indx < (nlmsg_idx + nlmsg_len):
                        rtattr = nlmsg[rtattr_indx : rtattr_indx + RTATTR_SZ]
                        rta_len, rta_type = struct.unpack('<HH', rtattr)
                        if rta_type == IFLA_ADDRESS:
                            data = nlmsg[rtattr_indx + RTATTR_SZ : rtattr_indx + rta_len]
                            if _data_matches_mac(data, mac):
                                return socket.if_indextoname(ifi_index)

                        rta_len = RTA_ALIGN(rta_len)  # Round up to multiple of 4
                        rtattr_indx += rta_len  # Move to next rtattr

            nlmsg_idx += nlmsg_len  # Move to next Netlink message

    return ''


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


def _iface_of(src_addr):  # pylint: disable=too-many-locals
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

            nlmsghdr = nlmsg[nlmsg_idx : nlmsg_idx + NLMSG_HDRLEN]
            nlmsg_len, nlmsg_type, _, _, _ = struct.unpack('<LHHLL', nlmsghdr)

            if nlmsg_type == NLMSG_DONE:
                break

            if nlmsg_type == RTM_NEWADDR:
                msg_indx = nlmsg_idx + NLMSG_HDRLEN
                msg = nlmsg[msg_indx : msg_indx + IFADDRMSG_SZ]  # ifaddrmsg
                ifa_family, _, _, _, ifa_index = struct.unpack('<BBBBL', msg)

                rtattr_indx = msg_indx + IFADDRMSG_SZ
                while rtattr_indx < (nlmsg_idx + nlmsg_len):
                    rtattr = nlmsg[rtattr_indx : rtattr_indx + RTATTR_SZ]
                    rta_len, rta_type = struct.unpack('<HH', rtattr)
                    if rta_type == IFLA_ADDRESS:
                        data = nlmsg[rtattr_indx + RTATTR_SZ : rtattr_indx + rta_len]
                        if _data_matches_ip(ifa_family, data, src_addr):
                            return socket.if_indextoname(ifa_index)

                    rta_len = RTA_ALIGN(rta_len)  # Round up to multiple of 4
                    rtattr_indx += rta_len  # Move to next rtattr

            nlmsg_idx += nlmsg_len  # Move to next Netlink message

    return ''


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
def get_interface(src_addr):
    '''Get interface for given source address
    @param src_addr: The source address
    @type src_addr: str
    '''
    if not src_addr:
        return ''

    src_addr = src_addr.split('%')[0]  # remove scope-id (if any)
    src_addr = get_ipaddress_obj(src_addr)
    return '' if src_addr is None else _iface_of(src_addr)
