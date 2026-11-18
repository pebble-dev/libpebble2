from __future__ import absolute_import
__author__ = 'katharine'

import json
import os
import struct
import uuid
import zipfile

from .hardware import PebbleHardware
from .platform import KNOWN_PLATFORMS, Platform, compatible_directories, platform_for_hardware

__all__ = ["PebbleBundle"]


class PebbleBundle(object):
    MANIFEST_FILENAME = 'manifest.json'
    UNIVERSAL_FILES = {'appinfo.json', 'pebble-js-app.js'}

    STRUCT_DEFINITION = [
            '8s',   # header
            '2B',   # struct version
            '2B',   # sdk version
            '2B',   # app version
            'H',    # size
            'I',    # offset
            'I',    # crc
            '32s',  # app name
            '32s',  # company name
            'I',    # icon resource id
            'I',    # symbol table address
            'I',    # flags
            'I',    # num relocation list entries
            '16s'   # uuid
    ]

    PLATFORM_PATHS = {
        'unknown': ('',),
        'aplite': ('aplite/', ''),  # this will fail if you have a dual aplite2/3 app and try
                                    # installing on 2.x. Such apps are unsupported, so this is okay.
        'basalt': ('basalt/', ''),
        'chalk': ('chalk/',),
        'diorite': ('diorite/', 'aplite/', ''),
        'emery': ('emery/', 'basalt/', ''),
        'flint': ('flint/', 'diorite/', 'aplite/', ''),
        'gabbro': ('gabbro/', 'chalk/'),
    }

    #: Platforms no firmware is built for anymore.
    FROZEN_PLATFORMS = ('aplite', 'basalt', 'chalk', 'diorite')

    MAX_COMPATIBILITY_VERSIONS = {
        'basalt': {'': 0x16},
        'diorite': {'aplite/': 0x50, '': 0x16},
        'emery': {'basalt/': 0x54, '': 0x16},
        'flint': {'aplite/': 0x50, '': 0x16},
        'gabbro': {'chalk/': 0x54},
    }

    def __init__(self, bundle_path, hardware=PebbleHardware.UNKNOWN, platform=None, any_fit=False):
        """
        :param bundle_path: Path of the bundle.
        :param hardware: The hardware revision of the watch the bundle is for.
        :param platform: What the watch's platform is like, when the watch describes it; it then decides
                         which of the bundle's binaries is used, rather than ``hardware``.
        :type platform: .Platform
        :param any_fit: Take the best of all the binaries the watch can run, rather than only one built
                        for its platform or one its platform has always taken.
        :type any_fit: bool
        """
        self.hardware = hardware
        self.platform = platform or platform_for_hardware(hardware)
        self.any_fit = any_fit
        self._prefixes = None
        bundle_abs_path = os.path.abspath(bundle_path)
        if not os.path.exists(bundle_abs_path):
            raise Exception("Bundle does not exist: " + bundle_path)

        self.zip = zipfile.ZipFile(bundle_abs_path)
        self.path = bundle_abs_path
        self.manifest = None
        self.header = None
        self._zip_contents = set(self.zip.namelist())

        self.app_metadata_struct = struct.Struct(''.join(self.STRUCT_DEFINITION))
        self.app_metadata_length_bytes = self.app_metadata_struct.size

        self.print_pbl_logs = False

    @classmethod
    def prefixes_for_hardware(cls, hardware):
        platform = PebbleHardware.hardware_platform(hardware)
        return cls.PLATFORM_PATHS[platform]

    def get_platforms(self):
        """
        The platform each directory of the bundle is for, by directory prefix (``"emery/"``, or ``""`` for the
        root). A directory's manifest describes its platform; one that does not is of the platform it is named
        after.

        :rtype: dict[str, .Platform]
        """
        platforms = {}
        for name in self._zip_contents:
            prefix, _, filename = name.rpartition('/')
            if filename != self.MANIFEST_FILENAME or '/' in prefix:
                continue
            prefix = prefix + '/' if prefix else ''
            try:
                manifest = json.loads(self.zip.read(name).decode('utf-8'))
            except ValueError:
                continue
            # A binary at the root is from before pbws had directories.
            platform = (Platform.from_manifest(manifest.get('platform'))
                        or KNOWN_PLATFORMS.get(prefix.rstrip('/') or 'aplite'))
            if platform is not None:
                platforms[prefix] = platform
        return platforms

    def _is_frozen(self):
        return self.platform.name in self.FROZEN_PLATFORMS

    def _get_prefixes(self):
        """The directories to take files from, best first."""
        if self._prefixes is None:
            if self.platform is None:
                self._prefixes = self.PLATFORM_PATHS['unknown']
            elif self._is_frozen() or (not self.any_fit and self.platform.name in self.PLATFORM_PATHS):
                # What the platform has always taken. Firmware of the frozen ones takes nothing else.
                self._prefixes = self.PLATFORM_PATHS[self.platform.name]
            else:
                self._prefixes = tuple(compatible_directories(self.platform, self.get_platforms()))
        return self._prefixes

    def get_real_path(self, path):
        if path in self.UNIVERSAL_FILES:
            return path
        else:
            for prefix in self._get_prefixes():
                real_path = prefix + path
                if real_path in self._zip_contents:
                    return real_path
            return None

    def _get_real_prefix(self):
        for prefix in self._get_prefixes():
            real_path = prefix + self.MANIFEST_FILENAME
            if real_path in self._zip_contents:
                return prefix
        return None

    def should_permit_install(self):
        """Whether the bundle has a binary meant for the watch. Without ``any_fit``, a binary that merely fits
        the watch does not count: an app that leaves the watch's platform out says it is not for that watch."""
        platform = self.platform.name if self.platform else 'unknown'
        prefix = self._get_real_prefix()
        if prefix is None:
            return False
        if self.any_fit:
            return True
        if platform not in self.PLATFORM_PATHS:
            # A platform that only the watch has described: its own binary, or one for its very display.
            built_for = self.get_platforms()[prefix]
            return built_for.name == platform or built_for.same_display(self.platform)
        if platform in self.MAX_COMPATIBILITY_VERSIONS:
            max_version = self.MAX_COMPATIBILITY_VERSIONS[platform].get(prefix, None)
            if max_version is None:
                return True
            metadata = self.get_app_metadata()
            return metadata['sdk_version_minor'] < max_version
        return True

    def get_manifest(self):
        if self.manifest:
            return self.manifest

        if self.get_real_path(self.MANIFEST_FILENAME) not in self.zip.namelist():
            raise Exception("Could not find {}; are you sure this is a PebbleBundle?".format(self.MANIFEST_FILENAME))

        self.manifest = json.loads(self.zip.read(self.get_real_path(self.MANIFEST_FILENAME)).decode('utf-8'))
        return self.manifest

    def get_app_metadata(self):
        if self.header:
            return self.header

        app_manifest = self.get_manifest()['application']

        app_bin = self.zip.open(self.get_real_path(app_manifest['name'])).read()

        header = app_bin[0:self.app_metadata_length_bytes]
        values = self.app_metadata_struct.unpack(header)
        self.header = {
            'sentinel': values[0],
            'struct_version_major': values[1],
            'struct_version_minor': values[2],
            'sdk_version_major': values[3],
            'sdk_version_minor': values[4],
            'app_version_major': values[5],
            'app_version_minor': values[6],
            'app_size': values[7],
            'offset': values[8],
            'crc': values[9],
            'app_name': values[10].rstrip(b'\0').decode('utf-8'),
            'company_name': values[11].rstrip(b'\0').decode('utf-8'),
            'icon_resource_id': values[12],
            'symbol_table_addr': values[13],
            'flags': values[14],
            'num_relocation_entries': values[15],
            'uuid': uuid.UUID(bytes=values[16])
        }
        return self.header

    def close(self):
        self.zip.close()

    @property
    def is_firmware_bundle(self):
        return 'firmware' in self.get_manifest()

    @property
    def is_app_bundle(self):
        return 'application' in self.get_manifest()

    @property
    def has_resources(self):
        return 'resources' in self.get_manifest()

    @property
    def has_worker(self):
        return 'worker' in self.get_manifest()

    @property
    def has_javascript(self):
        return 'js' in self.get_manifest()

    def get_firmware_info(self):
        if not self.is_firmware_bundle:
            return None

        return self.get_manifest()['firmware']

    def get_application_info(self):
        if not self.is_app_bundle:
            return None

        return self.get_manifest()['application']

    def get_resources_info(self):
        if not self.has_resources:
            return None

        return self.get_manifest()['resources']

    def get_worker_info(self):
        if not self.is_app_bundle or not self.has_worker:
            return None

        return self.get_manifest()['worker']

    def get_app_path(self):
        return self.get_real_path(self.get_application_info()['name'])

    def get_resource_path(self):
        return self.get_real_path(self.get_resources_info()['name'])

    def get_worker_path(self):
        return self.get_real_path(self.get_worker_info()['name'])
