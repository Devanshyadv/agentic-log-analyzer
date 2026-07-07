import json
import threading
from typing import Callable, Optional
from loguru import logger

from ingestion.normalizer import NormalizerPipeline, LogEvent


class KafkaLogConsumer:
    def __init__(
        self,
        topic: str,
        bootstrap_servers: str = "localhost:9092",
        group_id: str = "logsentinel",
        callback: Optional[Callable[[LogEvent], None]] = None,
    ):
        self._topic = topic
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._callback = callback
        self._normalizer = NormalizerPipeline()
        self._consumer = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def _build_consumer(self):
        from kafka import KafkaConsumer

        return KafkaConsumer(
            self._topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda m: m.decode("utf-8", errors="replace"),
        )

    def _consume_loop(self):
        try:
            self._consumer = self._build_consumer()
            logger.info(f"Kafka consumer started on topic '{self._topic}'")
            for msg in self._consumer:
                if not self._running:
                    break
                raw_line = msg.value.strip()
                event = self._normalizer.process(raw_line, f"kafka:{self._topic}")
                if event and self._callback:
                    self._callback(event)
        except Exception as e:
            logger.error(f"Kafka consumer error: {e}")
        finally:
            if self._consumer:
                self._consumer.close()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Kafka consumer stopped")
