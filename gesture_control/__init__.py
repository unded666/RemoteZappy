"""Vendored minimal gesture_control shim for RemoteZappy.

This package provides a small, safe stand-in for the external GestureControl
package so cloud builds and headless runs won't fail when importing it.

Provided API (minimal):
- GestureRecognizer(dataset_dir=None, models_dir=None, required_gestures=None)
    - recognize(on_gesture)  # blocking loop; call stop() from another thread to end
    - stop()
- studio(destination, models, required_gestures, root=None) -> object with .window (tk.Toplevel)
- close_studio()  # close the last studio window if open

This shim intentionally does not perform any real gesture recognition. It
implements the runtime API enough that RemoteZappy can import and call it.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from types import SimpleNamespace
from typing import Callable, Iterable, Optional


class GestureRecognizer:
    """Minimal stub recognizer.

    Methods are intentionally lightweight and safe for headless/cloud runs.
    `recognize(on_gesture)` runs a simple loop that sleeps and only invokes
    the callback if `on_gesture` is provided with a 'No gesture' placeholder.
    Call `stop()` from another thread to exit the recognize loop.
    """

    def __init__(self, dataset_dir: Optional[str] = None, models_dir: Optional[str] = None, required_gestures: Optional[Iterable[str]] = None):
        self.dataset_dir = dataset_dir
        self.models_dir = models_dir
        self.required_gestures = list(required_gestures) if required_gestures else []
        self._running = False

    def recognize(self, on_gesture: Optional[Callable] = None):
        """Blocking recognition loop. Call `stop()` to exit.

        The real project would run a model loop here. This stub sleeps and
        only occasionally calls `on_gesture` with None/No gesture to avoid
        spamming the main app.
        """
        self._running = True
        try:
            while self._running:
                # Sleep a short time to avoid busy loop; production recognizer would
                # block on camera frames or model inference.
                time.sleep(0.1)
                # Do not call the callback with a positive gesture by default;
                # the consuming app expects to see real gestures only when present.
                # If a callback was provided and you want to test gesture flow,
                # you can run a separate helper that injects test gestures.
                # We'll occasionally call the callback with 'No gesture' if provided.
                if on_gesture and False:
                    try:
                        on_gesture('No gesture', {}, {}, self.required_gestures, [])
                    except Exception:
                        pass
        finally:
            self._running = False

    def stop(self):
        """Request the recognition loop to stop."""
        self._running = False


# Simple studio UI support
_last_studio_window: Optional[tk.Toplevel] = None


def studio(destination: str = None, models: str = None, required_gestures: Optional[Iterable[str]] = None, root: Optional[tk.Tk] = None):
    """Create a very small studio window object that the main app can wait on.

    Returns a SimpleNamespace with a `.window` attribute that points to a
    `tk.Toplevel` instance. The UI is intentionally minimal: a label and a
    Close button. This function is safe to call in environments with Tk
    available; if Tk is not usable, it returns a dummy object with a fake
    window implementing `destroy()` so wait_window will not hang indefinitely.
    """
    global _last_studio_window

    try:
        if root is None:
            # create a temporary hidden root if none provided
            root = tk.Tk()
            root.withdraw()

        win = tk.Toplevel(root)
        win.title('Gesture Studio (vendored stub)')
        # Keep the window small and provide a close button
        frame = tk.Frame(win)
        frame.pack(padx=8, pady=8)
        lbl = tk.Label(frame, text='Gesture Studio (stub)')
        lbl.pack()
        btn = tk.Button(frame, text='Close', command=win.destroy)
        btn.pack(pady=(6, 0))

        _last_studio_window = win

        return SimpleNamespace(window=win)
    except Exception:
        # If tkinter is not available or fails (headless), return a dummy object
        class DummyWin:
            def destroy(self):
                return

        return SimpleNamespace(window=DummyWin())


def close_studio():
    """Close the last created studio window if present."""
    global _last_studio_window
    try:
        if _last_studio_window is not None:
            try:
                _last_studio_window.destroy()
            except Exception:
                pass
            _last_studio_window = None
    except Exception:
        pass


__all__ = ['GestureRecognizer', 'studio', 'close_studio']

