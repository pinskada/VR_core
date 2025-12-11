# ruff: noqa: N815

"""Communication contracts RPI <-> Unity."""

from enum import IntEnum


# pylint: disable=invalid-name
class MessageType(IntEnum):
    """Message types for communication between RPI and Unity.

    camelCase used for consistency with Unity definition.
    """

    imuSensor = 0
    imuCmd = 1
    gazeData = 2
    gazeCalcControl = 3
    gazeSceneControl = 4
    trackerControl = 5
    tcpConfig = 6
    espConfig = 7
    tcpLogg = 8
    espLogg = 9
    trackerPreview = 10
    eyePreview = 11
    eyeImage = 12
    configReady = 13
    trackerData = 14
    ipdPreview = 15
    sceneMarker = 16
    calibData = 17
    eyeVectors = 18

class MessageFormat(IntEnum):
    """Message formats for communication between RPI and Unity.

    camelCase used for consistency with Unity definition.
    """

    json = 0
    jpeg = 1
    png = 2
