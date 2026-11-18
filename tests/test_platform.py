from __future__ import absolute_import

import json
import os

import pytest

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
