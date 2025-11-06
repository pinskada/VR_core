"""In-memory shared config with get/set APIs."""

import threading
from contextlib import contextmanager
from typing import Any, Callable, List, DefaultDict, Tuple, Iterator
from collections import defaultdict

from vr_core.base_service import BaseService
from vr_core.config_service.config_modules import RootConfig
import vr_core.config_service.config_modules as config_modules
from vr_core.utilities.logger_setup import setup_logger


class Config(BaseService):
    """
    Shared, in-memory config with just two APIs:
      - set("camera.exposure", 25)
      - get("imu.rate_hz") -> 200
    Thread-safe, updates happen in-place on dataclass instances.
    """
    def __init__(
        self,
        config_ready_s: threading.Event,
        mock_mode: bool = False,
    ) -> None:
        super().__init__(name="Config")
        self.logger = setup_logger("Config")

        self.config_ready_s = config_ready_s

        self.mock_mode = mock_mode

        self._lock = threading.RLock()
        self._root = RootConfig()
        self._subs_by_key: DefaultDict[
            str,
            List[Callable[[str, Any, Any], None]]
        ] = defaultdict(list)
        self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Start the config service."""
        if not self.mock_mode:
            self.config_ready_s.wait(timeout=float("inf"))

        self._ready.set()
        self.logger.info("Service is ready.")


    def _run(self) -> None:
        """Config service main loop (does nothing)."""
        while not self._stop.is_set():
            self._stop.wait(0.5)


    def _on_stop(self) -> None:
        """Stop the config service."""

        self.config_ready_s.clear()
        self.logger.info("Service stopping.")


    # --- direct accessors ---
    @property
    def tcp(self) -> config_modules.TCP:
        """Direct access to TCP config."""
        return self._root.tcp
    @property
    def tracker(self) -> config_modules.Tracker:
        """Direct access to tracker config."""
        return self._root.tracker
    @property
    def gaze(self) -> config_modules.Gaze:
        """Direct access to gaze config."""
        return self._root.gaze
    @property
    def camera(self) -> config_modules.Camera:
        """Direct access to camera config."""
        return self._root.camera
    @property
    def imu(self) -> config_modules.IMU:
        """Direct access to IMU config."""
        return self._root.imu
    @property
    def esp32(self) -> config_modules.ESP32:
        """Direct access to ESP32 config."""
        return self._root.esp32
    @property
    def health(self) -> config_modules.Health:
        """Direct access to health config."""
        return self._root.health
    @property
    def eyeloop(self) -> config_modules.Eyeloop:
        """Direct access to eyeloop config."""
        return self._root.eyeloop


    @contextmanager
    def read(self) -> Iterator[RootConfig]:
        """Hold the lock while reading config (strong typing preserved)."""
        with self._lock:
            yield self._root


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
            old = getattr(obj, attr)
            target_type = type(old)

            new: Any
            try:
                # handle bool specially because bool("0") is True
                if target_type is bool and isinstance(value, str):
                    v = value.strip().lower()
                    if v in ("1", "true", "yes", "on"):
                        new = True
                    elif v in ("0", "false", "no", "off"):
                        new = False
                    else:
                        self.logger.error("Config: cannot parse bool from '%s'", value)
                        raise ValueError(f"cannot parse bool from '{value}'")
                elif target_type is int and isinstance(value, str) and value.isdigit():
                    new = int(value)
                elif target_type in (int, float) and isinstance(value, str):
                    new = target_type(float(value))
                elif target_type is str:
                    new = str(value)
                else:
                    new = target_type(value)

            except (ValueError, TypeError) as e:
                self.logger.error("Failed to set %s to %r (expected %s): %s",
                    path, value, target_type.__name__, e)
                return
            if new == old:
                return
            setattr(obj, attr, new)

        self._notify(path, old, new)

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

        def _unsub() -> None:
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
                self.logger.error("Notify subscriber %s failed: %s", cb.__name__, e)


    def _traverse(
        self,
        path: str
    ) -> Tuple[Any, str]:
        """
        Returns (parent_object, attribute_name) for a dotted path like 'camera.exposure'.
        """
        parts = path.split(".")

        if len(parts) < 2:
            self.logger.error("Config: invalid path '%s'", path)
            raise ValueError("Use dotted path like 'camera.exposure'")

        node = self._root

        for p in parts[:-1]:
            node = getattr(node, p)

        return node, parts[-1]
