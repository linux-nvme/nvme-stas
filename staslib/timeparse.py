# Copyright (c) 2026, Dell Inc. or its subsidiaries.  All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# See the LICENSE file for details.
#
# This file is part of NVMe STorage Appliance Services (nvme-stas).
#
# Authors: Martin Belanger <Martin.Belanger@dell.com>
#
'''Parse a time span the way systemd does.

Implements a single function, `timeparse`, which converts a time span to a
number of seconds. It accepts what systemd's `parse_time()` accepts and means
the same thing by it: a sum of `<number><unit>` terms ("3 days 5 hours"),
fractions ("1.5h"), the keyword "infinity", and a unit-less term as seconds.

nvme-stas and nvme-discoverd take the same `dc-giveup-timeout` key with the
same documented encoding, and nvme-discoverd parses it with a copy of
systemd's `parse_time()`. A span a user writes once has to be read the same
way by both daemons and by systemd itself. So anything below that looks like
an arbitrary choice is not one: the suffix table, the "M" months / "m" minutes
case distinction, systemd's month and year approximations, the truncating
arithmetic on fractional digits and the microsecond ceiling all match systemd
deliberately, and changing any of them breaks that agreement.
'''

import math

USEC_PER_MSEC = 1000
USEC_PER_SEC = 1000 * USEC_PER_MSEC
USEC_PER_MINUTE = 60 * USEC_PER_SEC
USEC_PER_HOUR = 60 * USEC_PER_MINUTE
USEC_PER_DAY = 24 * USEC_PER_HOUR
USEC_PER_WEEK = 7 * USEC_PER_DAY
USEC_PER_MONTH = 2629800 * USEC_PER_SEC  # 30.44 days, systemd's approximation
USEC_PER_YEAR = 31557600 * USEC_PER_SEC  # 365.25 days, systemd's approximation

# "infinity", and the value no finite span may reach. systemd carries spans in
# a uint64_t, and rejects anything that would reach the sentinel. Python has no
# such limit, but the same ceiling is applied so that a span accepted here is
# a span accepted there.
USEC_INFINITY = 2**64 - 1

# Order matters: a suffix is matched as a prefix of what remains, so the longer
# spellings must come first. "M" is months and "m" is minutes, case-sensitive.
MULTIPLIERS = (
    ('seconds', USEC_PER_SEC),
    ('second', USEC_PER_SEC),
    ('sec', USEC_PER_SEC),
    ('s', USEC_PER_SEC),
    ('minutes', USEC_PER_MINUTE),
    ('minute', USEC_PER_MINUTE),
    ('min', USEC_PER_MINUTE),
    ('months', USEC_PER_MONTH),
    ('month', USEC_PER_MONTH),
    ('M', USEC_PER_MONTH),
    ('msec', USEC_PER_MSEC),
    ('ms', USEC_PER_MSEC),
    ('m', USEC_PER_MINUTE),
    ('hours', USEC_PER_HOUR),
    ('hour', USEC_PER_HOUR),
    ('hr', USEC_PER_HOUR),
    ('h', USEC_PER_HOUR),
    ('days', USEC_PER_DAY),
    ('day', USEC_PER_DAY),
    ('d', USEC_PER_DAY),
    ('weeks', USEC_PER_WEEK),
    ('week', USEC_PER_WEEK),
    ('w', USEC_PER_WEEK),
    ('years', USEC_PER_YEAR),
    ('year', USEC_PER_YEAR),
    ('y', USEC_PER_YEAR),
    ('usec', 1),
    ('us', 1),
    ('μs', 1),  # U+03BC GREEK SMALL LETTER MU
    ('µs', 1),  # U+00B5 MICRO SIGN
)

WHITESPACE = ' \t\n\r'
DIGITS = '0123456789'

INFINITY = 'infinity'


def _skip(text, index, chars):
    '''Return the index of the first character at or after @index that is not
    one of @chars.'''
    while index < len(text) and text[index] in chars:
        index += 1
    return index


def _extract_multiplier(text, index):
    '''Match a unit suffix at @index. Return (multiplier, index-past-suffix),
    or (None, @index) when nothing matches.'''
    for suffix, usec in MULTIPLIERS:
        if text.startswith(suffix, index):
            return usec, index + len(suffix)

    return None, index


def _to_seconds(usec):
    '''Convert microseconds to seconds, as an `int` when the span is a whole
    number of seconds and a `float` when it is not.'''
    if usec % USEC_PER_SEC == 0:
        return usec // USEC_PER_SEC

    return usec / USEC_PER_SEC


def timeparse(sval):
    '''
    Parse a time span the way systemd does, returning it as a number of
    seconds. If possible, the return value will be an `int`; if this is not
    possible, the return will be a `float`. The keyword "infinity" returns
    `math.inf`. Returns `None` if a time span cannot be parsed from the given
    string.

    A term with no unit is a number of seconds, and terms are summed.

    Arguments:
    - `sval`: the string value to parse

    >>> timeparse('72')
    72
    >>> timeparse('72hours')
    259200
    >>> timeparse('3 days 5 hours')
    277200
    >>> timeparse('1h30m')
    5400
    >>> timeparse('1.5h')
    5400
    >>> timeparse('500ms')
    0.5
    >>> timeparse('infinity')
    inf

    Signs, colon notation and comma-separated terms are not systemd syntax.

    >>> timeparse('-1') is None
    True
    >>> timeparse('1:30') is None
    True
    >>> timeparse('1 minute, 24 secs') is None
    True
    '''
    if not isinstance(sval, str):
        return None

    index = _skip(sval, 0, WHITESPACE)

    if sval.startswith(INFINITY, index):
        # "infinity" may be followed by whitespace, but by nothing else.
        if _skip(sval, index + len(INFINITY), WHITESPACE) != len(sval):
            return None

        return math.inf

    usec = 0
    something = False

    while True:
        index = _skip(sval, index, WHITESPACE)
        if index == len(sval):
            return _to_seconds(usec) if something else None

        if sval[index] == '-':  # rejects "-0" too
            return None

        start = index
        digits_at = index + 1 if sval[index] == '+' else index
        digits_end = _skip(sval, digits_at, DIGITS)
        if digits_end > digits_at:
            value = int(sval[start:digits_end])
            integer_end = digits_end
        else:
            value = 0
            integer_end = start  # no integer part: this may still be ".5"

        fraction = integer_end < len(sval) and sval[integer_end] == '.'
        if fraction:
            index = _skip(sval, integer_end + 1, DIGITS)
        elif integer_end == start:  # neither digits nor a decimal point
            return None
        else:
            index = integer_end

        # A suffix may be separated from its number by whitespace. When no
        # suffix follows, the term is in seconds -- but only if whitespace or
        # the end of the string separates it from what comes next. That is
        # what makes "12.34 .56" a sum and "12.34.56" a syntax error.
        before_space = index
        multiplier, index = _extract_multiplier(sval, _skip(sval, index, WHITESPACE))
        if multiplier is None:
            if index == before_space and index != len(sval):
                return None

            multiplier = USEC_PER_SEC

        if value >= USEC_INFINITY // multiplier:
            return None

        term = value * multiplier
        if term >= USEC_INFINITY - usec:
            return None

        usec += term
        something = True

        if fraction:
            # Fractional digits are consumed one at a time, each worth a tenth
            # of the previous one, truncating as systemd does.
            scale = multiplier // 10
            digit_at = integer_end + 1
            while digit_at < len(sval) and sval[digit_at] in DIGITS:
                term = int(sval[digit_at]) * scale
                if term >= USEC_INFINITY - usec:
                    return None

                usec += term
                digit_at += 1
                scale //= 10

            # Rejects "0.-0", "3.+1", "3. 1", "3.sec" and "3.hoge"
            if digit_at == integer_end + 1:
                return None
