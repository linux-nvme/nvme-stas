#!/usr/bin/env python3
import sys

KEYS = [
    ('transport', None),
    ('traddr', None),
    ('subsysnqn', 'nqn'),
    ('host-iface', None),
    ('host-traddr', None) ,
]

for ctrl in eval(sys.stdin.read()):
    print(f"{' '.join([f'--{kout or kin}={ctrl[kin]}' for kin,kout in KEYS if ctrl[kin] != ''])}")
