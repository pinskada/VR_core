"""In-memory shared config with get/set APIs."""

import threading
from typing import Any, Callable, List, DefaultDict, Tuple
from collections import defaultdict

from vr_core.config_service.config_modules import RootConfig


class Config:
    """
    Shared, in-memory config with just two APIs:
      - set("camera.exposure", 25)
      - get("imu.rate_hz") -> 200
    Thread-safe, updates happen in-place on dataclass instances.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._root = RootConfig()
        self._subs_by_key: DefaultDict[
            str,
            List[Callable[[str, Any, Any], None]]
        ] = defaultdict(list)


    # --- direct accessors ---
    @property
    def tcp(self):
        """Direct access to TCP config."""
        return self._root.tcp
    @property
    def tracker(self):
        """Direct access to tracker config."""
        return self._root.tracker
    @property
    def gaze(self):
        """Direct access to gaze config."""
        return self._root.gaze
    @property
    def camera(self):
        """Direct access to camera config."""
        return self._root.camera
    @property
    def imu(self):
        """Direct access to IMU config."""
        return self._root.imu
    @property
    def esp32(self):
        """Direct access to ESP32 config."""
        return self._root.esp32
    @property
    def health(self):
        """Direct access to health config."""
        return self._root.health


    #-- get/set API ---
    def get(self, path: str) -> Any:
        """Get a config value."""
        with self._lock:
            obj, attr = self._traverse(path)
            return getattr(obj, attr)


    def set(
        self,
        path: str,
        value: Any
    ) -> None:
        """Set a config value.

        Arguments:
            path: The config path to set (e.g., "camera.exposure").
            value: The new value to set.
        """

        with self._lock:
            obj, attr = self._traverse(path)
            # light type coerce to the current field's type (keeps it simple)
            current = getattr(obj, attr)
            try:
                target_type = type(current)
                # handle bool specially because bool("0") is True
                if target_type is bool and isinstance(value, str):
                    v = value.strip().lower()
                    if v in ("1", "true", "yes", "on"):
                        value = True
                    elif v in ("0", "false", "no", "off"):
                        value = False
                else:
                    if target_type is int and isinstance(value, str) and value.isdigit():
                        value = int(value)
                    elif target_type in (int, float) and isinstance(value, str):
                        value = target_type(float(value))  # e.g., "120" -> 120
                    else:
                        value = target_type(value)

                setattr(obj, attr, value)

            except (ValueError, TypeError, AttributeError) as e:
                print(f"Config: failed to set {path} to {value} (type {type(value)}): {e}")


    # --- subscribe API ---
    def subscribe(
        self,
        key: str,
        callback: Callable[[str, Any, Any], None]
    ) -> Callable[[], None]:
        """
        Subscribe to changes on a section ("camera") or a specific field ("camera.exposure").
        Callback signature: (path, old_value, new_value).
        Returns an unsubscribe function.
        """
        with self._lock:
            self._subs_by_key[key].append(callback)

        def _unsub():
            with self._lock:
                lst = self._subs_by_key.get(key, [])
                if callback in lst:
                    lst.remove(callback)

        return _unsub


    # --- helpers ---
    def _notify(
        self,
        path: str,
        old_val: Any,
        new_val: Any
    ) -> None:
        """Notify both section-level and exact-path subscribers."""
        section = path.split(".", 1)[0]

        # make copies to avoid mutation during iteration
        targets = list(self._subs_by_key.get(section, [])) + list(self._subs_by_key.get(path, []))

        for cb in targets:
            try:
                cb(path, old_val, new_val)
            except (RuntimeError, ValueError, TypeError) as e:
                print(f"Config notify: subscriber {cb.__name__} failed: {e}")


    def _traverse(
        self,
        path: str
    ) -> Tuple[Any, str]:
        """
        Returns (parent_object, attribute_name) for a dotted path like 'camera.exposure'.
        """
        parts = path.split(".")

        if len(parts) < 2:
            raise ValueError("Use dotted path like 'camera.exposure'")

        node = self._root

        for p in parts[:-1]:
            node = getattr(node, p)

        return node, parts[-1]
