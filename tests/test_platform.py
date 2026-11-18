from __future__ import absolute_import

import json
import os
import struct

import pytest

from libpebble2.protocol.system import WatchVersionResponse
from libpebble2.util.hardware import PebbleHardware
from libpebble2.util.platform import (KNOWN_PLATFORMS, Platform, compatible_directories,
                                      platform_for_hardware)

# The cases every implementation of the rule is held to, from PebbleOS
# (tools/tests/platform_fit_cases.json).
with open(os.path.join(os.path.dirname(__file__), 'platform_fit_cases.json')) as f:
    TABLE = json.load(f)
PLATFORMS = {name: Platform.from_manifest(p) for name, p in TABLE['platforms'].items()}

SLATE = PLATFORMS['slate']


@pytest.mark.parametrize("case", TABLE['cases'], ids=lambda case: case['name'])
def test_fit_cases(case):
    directories = {name + '/': PLATFORMS[name] for name in case['binaries']}
    best = compatible_directories(PLATFORMS[case['watch']], directories)
    assert [d.rstrip('/') for d in best] == case['expected']


def test_known_platforms_are_the_tables():
    assert [name for name in TABLE['age']] == sorted(KNOWN_PLATFORMS, key=TABLE['age'].index)
    for name in TABLE['age']:
        assert KNOWN_PLATFORMS[name] == PLATFORMS[name]


def test_root_is_aplite_and_comes_last():
    directories = {'': KNOWN_PLATFORMS['aplite'], 'aplite/': KNOWN_PLATFORMS['aplite']}
    assert compatible_directories(KNOWN_PLATFORMS['flint'], directories) == ['aplite/', '']


def test_platform_for_hardware():
    assert platform_for_hardware(PebbleHardware.SNOWY_DVT).name == 'basalt'
    assert platform_for_hardware(0x7f) is None


def _version_response(capabilities, trailer=b''):
    return (bytes(bytearray(47 * 2 + 4 + 9 + 12 + 6 + 4 + 4 + 6 + 2)) + struct.pack('<Q', capabilities) +
            bytes(bytearray(1 + 2 + 2)) + trailer)


def _platform_info(length=32, extra=b''):
    return struct.pack('>BBBBHHIHBB16s', 1, length, 1, 0, 240, 280, 1 << 5, 128, 6, 0, b'slate') + extra


def test_version_response_with_platform():
    old, _ = WatchVersionResponse.parse(_version_response(0)[:-5])
    assert Platform.from_watch(old.capabilities, old.platform_info) is None
    old, _ = WatchVersionResponse.parse(_version_response(0))
    assert Platform.from_watch(old.capabilities, old.platform_info) is None

    new, _ = WatchVersionResponse.parse(_version_response(1 << 30, _platform_info()))
    assert Platform.from_watch(new.capabilities, new.platform_info) == SLATE
    # A later version of the description is longer.
    later, _ = WatchVersionResponse.parse(_version_response(1 << 30, _platform_info(36, b'\x01\x02\x03\x04')))
    assert Platform.from_watch(later.capabilities, later.platform_info) == SLATE
    # Without the capability, whatever follows is not a description.
    other, _ = WatchVersionResponse.parse(_version_response(0, _platform_info()))
    assert Platform.from_watch(other.capabilities, other.platform_info) is None
    short, _ = WatchVersionResponse.parse(_version_response(1 << 30, _platform_info()[:10]))
    assert Platform.from_watch(short.capabilities, short.platform_info) is None


def test_unknown_values_fit_nothing():
    info = struct.pack('>BBBBHHIHBB16s', 1, 32, 9, 7, 240, 280, 0xffffffff, 128, 6, 0, b'odd')
    odd = Platform.from_watch(1 << 30, info)
    assert (odd.abi, odd.shape) == ('unknown', 'unknown')
    assert odd.features == Platform.FEATURES
    assert compatible_directories(odd, {'emery/': KNOWN_PLATFORMS['emery'], 'odd/': odd}) == []
