from __future__ import absolute_import

__all__ = ["Platform", "KNOWN_PLATFORMS", "platform_for_hardware", "compatible_directories"]

import struct

from .hardware import PebbleHardware


class Platform(object):
    """
    What an SDK platform is like. Watches report it, and each binary of a pbw says which it was
    built for, so the two can be matched without a table of the platforms there are.

    :param name: The platform's name, which is also its directory in a pbw.
    :type name: str
    :param width: Display width in pixels.
    :type width: int
    :param height: Display height in pixels.
    :type height: int
    :param shape: Shape of the display, ``"rect"`` or ``"round"``.
    :type shape: str
    :param color: Whether the display has colour.
    :type color: bool
    :param app_memory: Bytes an app is given for its code and memory.
    :type app_memory: int
    :param abi: What app binaries are compiled for.
    :type abi: str
    :param features: Names of what the watch has, e.g. ``"microphone"``.
    :type features: tuple
    """
    FEATURES = ("microphone", "smartstrap", "smartstrap_power", "health", "compass", "touch",
                "rgb_backlight", "speaker")
    ABIS = {1: "armv7m"}
    SHAPES = {0: "rect", 1: "round"}

    #: Capability of a watch's version response: the platform's description ends it.
    CAPABILITY = 1 << 30
    _WATCH_INFO = struct.Struct('>BBBBHHIHBB16s')

    def __init__(self, name, width, height, shape="rect", color=False, app_memory=0x10000,
                 abi="armv7m", features=()):
        self.name = name
        self.width = width
        self.height = height
        self.shape = shape
        self.color = color
        self.app_memory = app_memory
        self.abi = abi
        self.features = tuple(features)

    @classmethod
    def from_manifest(cls, platform):
        """The platform a pbw directory's manifest.json describes, or ``None`` if it does not
        describe one that can be read."""
        try:
            display = platform['display']
            return cls(str(platform['name']), int(display['width']), int(display['height']),
                       str(display['shape']), bool(display['color']),
                       int(platform['limits']['app_memory']), str(platform['abi']),
                       platform.get('features', ()))
        except (KeyError, TypeError, ValueError):
            return None

    @classmethod
    def from_watch(cls, capabilities, info):
        """
        The platform a watch describes in its version response, or ``None`` if it describes none.

        :param capabilities: The response's capabilities.
        :type capabilities: int
        :param info: What follows the fields of the response older firmware sends.
        :type info: bytes
        """
        if not (capabilities or 0) & cls.CAPABILITY or info is None or len(info) < cls._WATCH_INFO.size:
            return None
        # Later versions only add fields, which the length is there to skip.
        (version, length, abi, shape, width, height, features, app_memory_kib, color_depth, _,
         name) = cls._WATCH_INFO.unpack_from(bytes(info))
        if version == 0 or length < cls._WATCH_INFO.size or width == 0 or height == 0:
            return None
        return cls(name.split(b'\0')[0].decode('utf-8', 'replace'), width, height,
                   cls.SHAPES.get(shape, 'unknown'), color_depth > 1, app_memory_kib * 1024,
                   cls.ABIS.get(abi, 'unknown'),
                   [f for bit, f in enumerate(cls.FEATURES) if features & (1 << bit)])

    def fits(self, watch):
        """Whether a watch of the given platform runs a binary built for this one: the same ABI
        and shape, a display no larger than the watch's, no colour on a black and white display
        and no more app memory than the watch gives."""
        return (self.abi == watch.abi and self.abi in self.ABIS.values()
                and self.shape == watch.shape and self.shape in self.SHAPES.values()
                and self.width <= watch.width and self.height <= watch.height
                and (watch.color or not self.color)
                and self.app_memory <= watch.app_memory)

    def same_display(self, other):
        return ((self.width, self.height, self.shape, self.color)
                == (other.width, other.height, other.shape, other.color))

    def __eq__(self, other):
        return isinstance(other, Platform) and self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        return "Platform({!r}, {}x{}, {}, {}, {} bytes, {})".format(
            self.name, self.width, self.height, self.shape, 'color' if self.color else 'bw',
            self.app_memory, self.abi)


_OLD = ("microphone", "smartstrap", "smartstrap_power", "health", "compass")

#: The platforms a pbw and a watch may name without describing, oldest first.
_PLATFORMS = (
    Platform('aplite', 144, 168, app_memory=0x6000, features=("compass",)),
    Platform('basalt', 144, 168, color=True, features=_OLD),
    Platform('chalk', 180, 180, shape="round", color=True, features=_OLD),
    Platform('diorite', 144, 168, features=("microphone", "smartstrap", "health")),
    Platform('emery', 200, 228, color=True, app_memory=0x20000, features=Platform.FEATURES),
    Platform('flint', 144, 168, features=("microphone", "health", "compass", "speaker")),
    Platform('gabbro', 260, 260, shape="round", color=True, app_memory=0x20000,
             features=("microphone", "health", "compass", "touch")),
)
KNOWN_PLATFORMS = {p.name: p for p in _PLATFORMS}
_AGE = [p.name for p in _PLATFORMS]


def platform_for_hardware(hardware):
    """The platform of a watch that does not describe one, from its hardware revision, or
    ``None`` for hardware this library does not know."""
    return KNOWN_PLATFORMS.get(PebbleHardware.hardware_platform(hardware))


def compatible_directories(watch, directories):
    """
    The directories of a pbw a watch can take an app from, best first: that of its own platform,
    then one for its very display, the largest display, its colour depth, the newest platform.

    :param watch: The watch's platform.
    :type watch: Platform
    :param directories: The platform each directory of the pbw is for, by directory prefix
                        (``"emery/"``; ``""`` for a binary at the root).
    :type directories: dict[str, Platform]
    :rtype: list[str]
    """
    def rank(item):
        prefix, platform = item
        return (
            platform.name != watch.name,
            not platform.same_display(watch),
            -(platform.width * platform.height),
            platform.color != watch.color,
            # A platform this library has not heard of is newer than those it has.
            -(_AGE.index(platform.name) if platform.name in _AGE else len(_AGE)),
            platform.name,
            prefix == '',                             # a directory over the root
        )

    eligible = [(d, p) for d, p in directories.items() if p.fits(watch)]
    return [d for d, _ in sorted(eligible, key=rank)]
