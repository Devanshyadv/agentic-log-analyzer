import time
from pathlib import Path
from typing import Callable, Dict
from loguru import logger
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

from ingestion.normalizer import NormalizerPipeline, LogEvent


class _LogFileHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[LogEvent], None]):
        super().__init__()
        self._callback = callback
        self._normalizer = NormalizerPipeline()
        self._positions: Dict[str, int] = {}

    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent) and not event.is_directory:
            path = event.src_path
            if path.endswith(".log"):
                self._tail(path)

    def _tail(self, filepath: str):
        try:
            pos = self._positions.get(filepath, 0)
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                lines = f.readlines()
                self._positions[filepath] = f.tell()
            for line in lines:
                event = self._normalizer.process(line.strip(), Path(filepath).stem)
                if event:
                    self._callback(event)
        except OSError as e:
            logger.warning(f"Could not read {filepath}: {e}")

    def seed_position(self, filepath: str):
        try:
            self._positions[filepath] = Path(filepath).stat().st_size
        except OSError:
            self._positions[filepath] = 0


class FileWatcher:
    def __init__(self, watch_dir: str, callback: Callable[[LogEvent], None]):
        self._watch_dir = Path(watch_dir)
        self._callback = callback
        self._handler = _LogFileHandler(callback)
        self._observer = Observer()

    def start(self, tail_existing: bool = False):
        if not self._watch_dir.exists():
            self._watch_dir.mkdir(parents=True, exist_ok=True)

        for log_file in self._watch_dir.glob("*.log"):
            if tail_existing:
                self._handler.seed_position(str(log_file))
            else:
                self._handler._positions[str(log_file)] = 0

        self._observer.schedule(self._handler, str(self._watch_dir), recursive=False)
        self._observer.start()
        logger.info(f"Watching {self._watch_dir} for .log files")

    def stop(self):
        self._observer.stop()
        self._observer.join()

    def run_forever(self):
        self.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()


if __name__ == "__main__":
    import sys

    watch_path = sys.argv[1] if len(sys.argv) > 1 else "./data/sample_logs"

    def on_event(event: LogEvent):
        print(f"[{event.level}] {event.service} | {event.message[:100]}")

    watcher = FileWatcher(watch_path, on_event)
    watcher.run_forever()
