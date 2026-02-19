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
NLMSG_LENGTH = lambda msg_len: msg_len + NLMSG_HDRLEN  # noqa: E731

RTATTR_SZ = 4
RTA_ALIGN = lambda length: (length + 3) & ~3  # noqa: E731
IFLA_ADDRESS = 1
IFLA_IFNAME = 3


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
    return struct.pack('=LHHLL', NLMSG_LENGTH(msg_len), nlmsg_type, nlmsg_flags, nlmsg_seq, nlmsg_pid)


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
    return struct.pack('=BBBBL', family, prefixlen, flags, scope, index)


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
    return struct.pack('=BBHiII', family, 0, dev_type, index, flags, change)


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


def mac2iface(mac: str):
    '''@brief Find the interface that has @mac as its assigned MAC address.
    @param mac: The MAC address to match
    '''
    with socket.socket(family=socket.AF_NETLINK, type=socket.SOCK_RAW, proto=socket.NETLINK_ROUTE) as sock:
        sock.sendall(GETLINKCMD)
        nlmsg = sock.recv(8192)
        nlmsg_idx = 0
        while True:
            if nlmsg_idx >= len(nlmsg):
                nlmsg += sock.recv(8192)

            nlmsghdr = nlmsg[nlmsg_idx : nlmsg_idx + NLMSG_HDRLEN]
            nlmsg_len, nlmsg_type, _, _, _ = struct.unpack('=LHHLL', nlmsghdr)

            if nlmsg_type == NLMSG_DONE:
                break

            if nlmsg_type == RTM_BASE:
                msg_indx = nlmsg_idx + NLMSG_HDRLEN
                msg = nlmsg[msg_indx : msg_indx + IFINFOMSG_SZ]  # ifinfomsg
                _, _, ifi_type, ifi_index, _, _ = struct.unpack('=BBHiII', msg)

                if ifi_type in (ARPHRD_LOOPBACK, ARPHRD_ETHER):
                    rtattr_indx = msg_indx + IFINFOMSG_SZ
                    while rtattr_indx < (nlmsg_idx + nlmsg_len):
                        rtattr = nlmsg[rtattr_indx : rtattr_indx + RTATTR_SZ]
                        rta_len, rta_type = struct.unpack('=HH', rtattr)
                        if rta_type == IFLA_ADDRESS:
                            data = nlmsg[rtattr_indx + RTATTR_SZ : rtattr_indx + rta_len]
                            if _data_matches_mac(data, mac):
                                return socket.if_indextoname(ifi_index)

                        rta_len = RTA_ALIGN(rta_len)  # Round up to multiple of 4
                        rtattr_indx += rta_len  # Move to next rtattr

            nlmsg_idx += nlmsg_len  # Move to next Netlink message

    return ''


# ******************************************************************************
def ip_equal(ip1, ip2):
    '''Check whether two IP addresses are equal.
    @param ip1: IPv4Address or IPv6Address object
    @param ip2: IPv4Address or IPv6Address object
    '''
    if not isinstance(ip1, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return False
    if not isinstance(ip2, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return False

    if ip1.version == 4 and ip2.version == 6:
        ip2 = ip2.ipv4_mapped
    elif ip1.version == 6 and ip2.version == 4:
        ip1 = ip1.ipv4_mapped

    return ip1 == ip2


# ******************************************************************************
def get_ipaddress_obj(ipaddr, ipv4_mapped_convert=False):
    '''@brief Return a IPv4Address or IPv6Address depending on whether @ipaddr
    is a valid IPv4 or IPv6 address. Return None otherwise.

    If ipv4_mapped_resolve is set to True, IPv6 addresses that are IPv4-Mapped,
    will be converted to their IPv4 equivalent.
    '''
    try:
        ip = ipaddress.ip_address(ipaddr)
    except ValueError:
        return None

    if ipv4_mapped_convert:
        ipv4_mapped = getattr(ip, 'ipv4_mapped', None)
        if ipv4_mapped is not None:
            ip = ipv4_mapped

    return ip


# ******************************************************************************
def net_if_addrs():
    '''@brief Return a dictionary listing every IP addresses for each interface.
    The first IP address of a list is the primary address used as the default
    source address.
    @example: {
        'wlp0s20f3': {
             4: [IPv4Address('10.0.0.28')],
             6: [
                IPv6Address('fd5e:9a9e:c5bd:0:5509:890c:1848:3843'),
                IPv6Address('fd5e:9a9e:c5bd:0:1fd5:e527:8df7:7912'),
                IPv6Address('2605:59c8:6128:fb00:c083:1b8:c467:81d2'),
                IPv6Address('2605:59c8:6128:fb00:e99d:1a02:38e0:ad52'),
                IPv6Address('fe80::d71b:e807:d5ee:7614'),
             ],
        },
        'lo': {
             4: [IPv4Address('127.0.0.1')],
             6: [IPv6Address('::1')],
        },
        'docker0': {
            4: [IPv4Address('172.17.0.1')],
            6: []
        },
    }
    '''
    interfaces = {}
    with socket.socket(socket.AF_NETLINK, socket.SOCK_RAW) as sock:
        sock.sendall(GETADDRCMD)
        nlmsg = sock.recv(8192)
        nlmsg_idx = 0
        while True:
            if nlmsg_idx >= len(nlmsg):
                nlmsg += sock.recv(8192)

            nlmsghdr = nlmsg[nlmsg_idx : nlmsg_idx + NLMSG_HDRLEN]
            nlmsg_len, nlmsg_type, _, _, _ = struct.unpack('=LHHLL', nlmsghdr)

            if nlmsg_type == NLMSG_DONE:
                break

            if nlmsg_type == RTM_NEWADDR:
                msg_indx = nlmsg_idx + NLMSG_HDRLEN
                msg = nlmsg[msg_indx : msg_indx + IFADDRMSG_SZ]  # ifaddrmsg
                ifa_family, _, _, _, ifa_index = struct.unpack('=BBBBL', msg)

                if ifa_family in (socket.AF_INET, socket.AF_INET6):
                    interfaces.setdefault(ifa_index, {4: [], 6: []})

                    rtattr_indx = msg_indx + IFADDRMSG_SZ
                    while rtattr_indx < (nlmsg_idx + nlmsg_len):
                        rtattr = nlmsg[rtattr_indx : rtattr_indx + RTATTR_SZ]
                        rta_len, rta_type = struct.unpack('=HH', rtattr)

                        if rta_type == IFLA_IFNAME:
                            data = nlmsg[rtattr_indx + RTATTR_SZ : rtattr_indx + rta_len]
                            ifname = data.rstrip(b'\0').decode()
                            interfaces[ifa_index]['name'] = ifname

                        elif rta_type == IFLA_ADDRESS:
                            data = nlmsg[rtattr_indx + RTATTR_SZ : rtattr_indx + rta_len]
                            ip = get_ipaddress_obj(data)
                            if ip:
                                family = 4 if ifa_family == socket.AF_INET else 6
                                interfaces[ifa_index][family].append(ip)

                        rta_len = RTA_ALIGN(rta_len)  # Round up to multiple of 4
                        rtattr_indx += rta_len  # Move to next rtattr

            nlmsg_idx += nlmsg_len  # Move to next Netlink message

    if_addrs = {}
    for value in interfaces.values():
        name = value.pop('name', None)
        if name is not None:
            if_addrs[name] = value

    return if_addrs


# ******************************************************************************
def get_interface(ifaces: dict, src_addr):
    '''Get interface for given source address
    @param ifaces: Interface info previously returned by @net_if_addrs()
    @param src_addr: IPv4Address or IPv6Address object
    '''
    if not isinstance(src_addr, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        return ''

    for iface, addr_map in ifaces.items():
        for addrs in addr_map.values():
            for addr in addrs:
                if ip_equal(src_addr, addr):
                    return iface

    return ''
