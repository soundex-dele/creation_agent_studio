"""Bounded public model output, separate from validated task results."""
import time


class GenerationPreview:
    def __init__(self, persist, cancelled):
        self.persist = persist
        self.cancelled = cancelled
        self.text = ''
        self.last_write = None
        self.persist({'text': '', 'state': 'waiting'})

    def on_event(self, event_type, event):
        # Reasoning, tool arguments and provider diagnostics are not public output.
        if event_type not in ('output.delta', 'output.snapshot') or not isinstance(event, dict):
            return
        text = event.get('text')
        if not isinstance(text, str):
            return
        if self.cancelled():
            raise InterruptedError('任务已取消。')
        updated = (text if event_type == 'output.snapshot' else self.text + text)[:200000]
        if updated == self.text:
            return
        self.text = updated
        now = time.monotonic()
        if self.last_write is None or now - self.last_write >= 1:
            self.persist({'text': self.text, 'state': 'receiving'})
            self.last_write = now

    def finish(self):
        if not self.cancelled():
            self.persist({'text': self.text, 'state': 'received'})
