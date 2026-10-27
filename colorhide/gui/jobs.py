"""Run blocking work off the UI thread and report back through Qt signals."""
import traceback

from PySide6.QtCore import QObject, QRunnable, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(float)


class Job(QRunnable):
    live = set()  # Python must hold each job (and its signal object) until it has reported back

    def __init__(self, fn, *args, progress=False, quiet=False):
        super().__init__()
        self.quiet = quiet
        self.setAutoDelete(False)
        self.fn, self.args, self.sig, self.want_progress = fn, args, _Signals(), progress
        Job.live.add(self)
        self.sig.done.connect(lambda _: Job.live.discard(self))
        self.sig.failed.connect(lambda _: Job.live.discard(self))

    def run(self):
        try:
            kw = {"progress": self.sig.progress.emit} if self.want_progress else {}
            result = self.fn(*self.args, **kw)
        except Exception as ex:
            if not self.quiet:
                traceback.print_exc()
            self._emit(self.sig.failed, str(ex) or type(ex).__name__)
            return
        self._emit(self.sig.done, result)

    def _emit(self, signal, value):
        try:
            signal.emit(value)
        except RuntimeError:  # whoever asked (a closed dialog, a finished app) is gone: drop the result
            Job.live.discard(self)
