"""Background estimates (resulting file size) for the Adjust Size and Export sheets."""

import threading

from gi.repository import GLib


class Estimator:
    """Run fn() off the main thread after a short pause; deliver only the newest result.

    Each schedule() or cancel() invalidates whatever is still running, so a slow estimate for old settings
    never lands after the settings changed.
    """

    def __init__(self, deliver, delay_ms=250):
        self._deliver = deliver
        self._delay_ms = delay_ms
        self._seq = 0
        self._timer = 0

    def schedule(self, fn):
        self.cancel()
        self._timer = GLib.timeout_add(self._delay_ms, self._start, fn)

    def cancel(self):
        self._seq += 1
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _start(self, fn):
        self._timer = 0
        seq = self._seq

        def work():
            try:
                result = fn()
            except Exception:  # an estimate is optional
                result = None
            GLib.idle_add(self._done, seq, result)

        threading.Thread(target=work, daemon=True).start()
        return False

    def _done(self, seq, result):
        if seq == self._seq and result is not None:
            self._deliver(result)
        return False
