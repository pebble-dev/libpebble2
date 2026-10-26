from __future__ import absolute_import

from libpebble2.protocol.system import Reset, WatchFirmwareVersion


def test_reset_commands():
    assert Reset(command=Reset.Command.Reset).serialise() == b'\x00'
    assert Reset(command=Reset.Command.DumpCore).serialise() == b'\x01'
    assert Reset(command=Reset.Command.FactoryReset).serialise() == b'\xfe'
    assert Reset(command=Reset.Command.PRF).serialise() == b'\xff'


def _firmware_version(flags):
    return (b'\x00' * 4 + b'v4.42.0'.ljust(32, b'\x00') + b'abcdef0'.ljust(8, b'\x00') +
            bytearray([flags, 0, 2]))


def test_firmware_version_flags():
    normal, _ = WatchFirmwareVersion.parse(_firmware_version(0x0c))
    assert not normal.is_recovery
    assert normal.is_dual_slot
    assert normal.is_slot_0

    recovery, _ = WatchFirmwareVersion.parse(_firmware_version(0x01))
    assert recovery.is_recovery
    assert not recovery.is_dual_slot


def test_firmware_version_is_recovery_construction():
    version = WatchFirmwareVersion(timestamp=0, version_tag='v4.42.0', git_hash='abcdef0',
                                   is_recovery=True, hardware_platform=0, metadata_version=2)
    assert version.flags == 0x01
    assert version.serialise()[44] in (1, b'\x01')
    version.is_recovery = False
    assert version.flags == 0
