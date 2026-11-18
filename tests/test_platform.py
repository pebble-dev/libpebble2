from __future__ import absolute_import

import json
import os
import struct
import zipfile

import pytest

from libpebble2.protocol.system import WatchVersionResponse
from libpebble2.util.bundle import PebbleBundle
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


def _pbw(tmp_path, directories):
    path = str(tmp_path / 'app.pbw')
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('appinfo.json', '{}')
        for prefix, platform in directories.items():
            manifest = {'application': {'name': 'pebble-app.bin'}}
            if platform is not None:
                manifest['platform'] = platform
            z.writestr(prefix + 'manifest.json', json.dumps(manifest))
            # Enough of a header for the SDK version to be read: 5.0.
            z.writestr(prefix + 'pebble-app.bin', struct.pack('<8s2B2B', b'PBLAPP', 16, 0, 5, 0).ljust(200, b'\0'))
    return path


def test_bundle_reads_described_platforms(tmp_path):
    path = _pbw(tmp_path, {'slate/': TABLE['platforms']['slate'], 'emery/': None, 'basalt/': None})

    bundle = PebbleBundle(path, platform=SLATE)
    assert bundle.get_platforms()['slate/'] == SLATE
    assert bundle.get_platforms()['emery/'] == KNOWN_PLATFORMS['emery']
    assert bundle.get_app_path() == 'slate/pebble-app.bin'
    assert bundle.should_permit_install()

    # A watch that only says what hardware it is still gets its binary.
    assert PebbleBundle(path, hardware=PebbleHardware.SNOWY_DVT).get_app_path() == 'basalt/pebble-app.bin'
    # And one nothing is known about gets none.
    assert PebbleBundle(path).get_real_path('pebble-app.bin') is None


def test_known_watches_take_what_they_took(tmp_path):
    path = _pbw(tmp_path, {'flint/': None, 'aplite/': None, 'chalk/': None})
    # Emery runs Flint's apps, but the pbw was not built for it: only when asked for any fit.
    emery = PebbleBundle(path, platform=KNOWN_PLATFORMS['emery'])
    assert emery.get_real_path('pebble-app.bin') is None
    assert not emery.should_permit_install()
    emery = PebbleBundle(path, platform=KNOWN_PLATFORMS['emery'], any_fit=True)
    assert emery.get_app_path() == 'flint/pebble-app.bin'
    assert emery.should_permit_install()
    # Flint always took Aplite's.
    flint = PebbleBundle(_pbw(tmp_path, {'aplite/': None}), platform=KNOWN_PLATFORMS['flint'])
    assert flint.get_app_path() == 'aplite/pebble-app.bin'
    # The frozen platforms take nothing else, asked or not.
    basalt = PebbleBundle(path, platform=KNOWN_PLATFORMS['basalt'], any_fit=True)
    assert basalt.get_real_path('pebble-app.bin') is None


def test_new_platform_wants_its_own_binary(tmp_path):
    path = _pbw(tmp_path, {'emery/': None, 'basalt/': None})
    slate = PebbleBundle(path, platform=SLATE)
    assert slate.get_app_path() == 'emery/pebble-app.bin'
    assert not slate.should_permit_install()
    assert PebbleBundle(path, platform=SLATE, any_fit=True).should_permit_install()
    # One built for the very display of the watch is as good as its own.
    path = _pbw(tmp_path, {'granite/': TABLE['platforms']['granite'], 'emery/': None})
    slate = PebbleBundle(path, platform=SLATE)
    assert slate.get_app_path() == 'granite/pebble-app.bin'
    assert slate.should_permit_install()


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
