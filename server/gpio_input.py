"""Optional BCM inputs for a future button and encoder harness.

Nothing is wired by default. Enable the block in the config, then connect
active-low buttons to ground and a quadrature encoder. This module is idle
when gpio.enabled is false, so a desktop demo never opens the GPIO chip.
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any

from logic import KEYS, QuadratureDecoder


class GpioService:
    def __init__(self) -> None:
        self._events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=64)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def apply(self, config: dict[str, Any]) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.5)
        self._stop = threading.Event()
        self._thread = None
        self.last_error = None
        if not config.get("gpio", {}).get("enabled"):
            return
        self._thread = threading.Thread(
            target=self._run,
            args=(config, self._stop),
            name="flight-tracker-gpio",
            daemon=True,
        )
        self._thread.start()

    def drain(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while len(items) < 32:
            try:
                items.append(self._events.get_nowait())
            except queue.Empty:
                break
        return items

    def close(self) -> None:
        self._stop.set()

    def _emit(self, event: dict[str, Any]) -> None:
        try:
            self._events.put_nowait(event)
        except queue.Full:
            pass

    def _run(self, config: dict[str, Any], stop: threading.Event) -> None:
        try:
            self._run_gpiozero(config, stop)
            return
        except Exception as exc:  # library missing or pin claim failed
            gpiozero_error = exc
        try:
            self._run_lgpio(config, stop)
            return
        except Exception as exc:
            self.last_error = f"GPIO unavailable ({gpiozero_error}; {exc})"
            self._emit({"type": "error", "message": self.last_error})

    def _run_gpiozero(self, config: dict[str, Any], stop: threading.Event) -> None:
        from gpiozero import Button, RotaryEncoder

        held: list[Any] = []
        pins = config["gpio"]["pins"]
        for key in KEYS:
            button = Button(int(pins[key]), pull_up=True, bounce_time=0.04)
            button.when_pressed = lambda name=key: self._emit({"type": "button", "key": name})
            held.append(button)
        encoder_cfg = config["gpio"]["encoder"]
        encoder = RotaryEncoder(
            int(encoder_cfg["clk"]),
            int(encoder_cfg["dt"]),
            max_steps=100000,
            wrap=False,
        )

        def clockwise() -> None:
            self._emit({"type": "encoder", "delta": 1})
            encoder.steps = 0

        def counterclockwise() -> None:
            self._emit({"type": "encoder", "delta": -1})
            encoder.steps = 0

        encoder.when_rotated_clockwise = clockwise
        encoder.when_rotated_counter_clockwise = counterclockwise
        held.append(encoder)
        switch = Button(int(encoder_cfg["sw"]), pull_up=True, bounce_time=0.04)
        switch.when_pressed = lambda: self._emit({"type": "button", "key": "BRT"})
        held.append(switch)
        try:
            stop.wait()
        finally:
            for device in held:
                try:
                    device.close()
                except Exception:
                    pass

    def _run_lgpio(self, config: dict[str, Any], stop: threading.Event) -> None:
        import lgpio

        handle = lgpio.gpiochip_open(0)
        pins = config["gpio"]["pins"]
        encoder_cfg = config["gpio"]["encoder"]
        pull_up = int(getattr(lgpio, "SET_PULL_UP", 0))
        claimed: list[int] = []
        try:
            levels: dict[str, int] = {}
            for key in KEYS:
                pin = int(pins[key])
                lgpio.gpio_claim_input(handle, pin, pull_up)
                claimed.append(pin)
                levels[key] = lgpio.gpio_read(handle, pin)
            for name in ("clk", "dt", "sw"):
                pin = int(encoder_cfg[name])
                lgpio.gpio_claim_input(handle, pin, pull_up)
                claimed.append(pin)
            decoder = QuadratureDecoder()
            clk_pin = int(encoder_cfg["clk"])
            dt_pin = int(encoder_cfg["dt"])
            sw_pin = int(encoder_cfg["sw"])
            sw_level = lgpio.gpio_read(handle, sw_pin)
            last_fire = {key: 0.0 for key in KEYS}
            last_sw = 0.0
            while not stop.is_set():
                now = time.monotonic()
                for key in KEYS:
                    pin = int(pins[key])
                    level = lgpio.gpio_read(handle, pin)
                    if levels[key] == 1 and level == 0 and now - last_fire[key] > 0.04:
                        last_fire[key] = now
                        self._emit({"type": "button", "key": key})
                    levels[key] = level
                detent = decoder.update(lgpio.gpio_read(handle, clk_pin), lgpio.gpio_read(handle, dt_pin))
                if detent:
                    self._emit({"type": "encoder", "delta": detent})
                sw_now = lgpio.gpio_read(handle, sw_pin)
                if sw_level == 1 and sw_now == 0 and now - last_sw > 0.04:
                    last_sw = now
                    self._emit({"type": "button", "key": "BRT"})
                sw_level = sw_now
                stop.wait(0.002)
        finally:
            for pin in claimed:
                try:
                    lgpio.gpio_free(handle, pin)
                except Exception:
                    pass
            lgpio.gpiochip_close(handle)
