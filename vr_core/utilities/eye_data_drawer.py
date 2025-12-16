# ruff: noqa: F405, BLE001, TRY400
"""Module for drawing eye data on images."""

import numpy as np
import cv2

import vr_core.eye_tracker.tracker_types as tt
from vr_core.eye_tracker.eyeloop_module.eyeloop.constants.minimum_gui_constants import *  # noqa: F403
from vr_core.eye_tracker.eyeloop_module.eyeloop.utilities.general_operations import to_int, tuple_int
from vr_core.utilities.logger_setup import setup_logger

logger = setup_logger("EyeDataDrawer")


def draw(
    source_rgb: np.ndarray,
    tracker_data: tt.OneSideTrackerData,
    radius: int,
    ) -> np.ndarray:
    """Draw pupil and CR marks on the source image."""
    pupil_data = tracker_data.pupil
    cr_data_list = tracker_data.crs

    source_rgb = cv2.cvtColor(source_rgb, cv2.COLOR_GRAY2BGR)

    try:
        cv2.ellipse(
            source_rgb,
            tuple_int(pupil_data.center),
            tuple_int((pupil_data.radius, pupil_data.radius)),
            0, 0, 360, red, 1,
        )
        cv2.ellipse(
                source_rgb,
                tuple_int(pupil_data.center),
                tuple_int((radius, radius)),
                0, 0, 360, blue, 1,
            )
        place_cross(source_rgb, pupil_data.center, red, 1, 20)
    except Exception as e:
        logger.error("Pupil mark error: %s", e)

    try:
        for cr in cr_data_list:
            color = bluish if cr.is_filled else green
            place_cross(source_rgb, cr.center, color, 2, 12)
    except Exception as e:
        logger.error("CR mark error: %s", e)

    try:
        x_coords = [cr.center[0] for cr in cr_data_list]
        y_coords = [cr.center[1] for cr in cr_data_list]

        centroid_x = sum(x_coords) / len(cr_data_list)
        centroid_y = sum(y_coords) / len(cr_data_list)
        place_cross(source_rgb, (centroid_x, centroid_y), pink, 2, 12)
        cv2.line(
            source_rgb,
            tuple_int(pupil_data.center),
            tuple_int((centroid_x, centroid_y)),
            pink,
            3,
        )
    except Exception as e:
        logger.error("Pupil-CR line error: %s", e)

    return source_rgb


def place_cross(
        source: np.ndarray,
        center: tuple[float, float],
        color: tuple[float, float, float],
        thickness: int,
        size: int,
    ) -> None:
        """Place a cross at the specified center on the source image."""
        try:
            source[
                to_int(center[1] - size):to_int(center[1] + size-1),
                to_int(center[0]-thickness):to_int(center[0]+thickness),
            ] = color
            source[
                to_int(center[1]-thickness):to_int(center[1]+thickness),
                to_int(center[0] - size):to_int(center[0] + size-1),
            ] = color
        except Exception as e:
            logger.error("Cross placement error at center: %s, with source shape: %s, thickness: %s and size: %s", center, source.shape, thickness, size)
            logger.error("Error: %s", e)