"""Host link: newline-delimited JSON arriving over the USB serial port.

The Mac agent writes one compact JSON object per line. Reads are polled so
the render loop never blocks waiting for the host, and only the most recent
complete object is kept — if the host gets ahead of the panel, the display
jumps to current rather than replaying a backlog.

Bytes are accumulated in a bytearray rather than by string concatenation:
building a ~600 byte line one immutable string at a time was costing more
than the JSON parse.
"""

import json
import select
import sys

MAX_LINE = 4096


class Link:
    def __init__(self):
        self._stdin = sys.stdin.buffer
        self._poll = select.poll()
        self._poll.register(sys.stdin, select.POLLIN)
        self._buf = bytearray()
        self.lines = 0
        self.errors = 0

    def read(self):
        """Return the newest decoded object seen this call, else None."""
        latest = None
        buf = self._buf
        poll = self._poll.poll
        read = self._stdin.read

        while poll(0):
            b = read(1)
            if not b:
                break
            c = b[0]
            if c == 10:            # newline: end of a frame
                if buf:
                    try:
                        obj = json.loads(bytes(buf))
                        if isinstance(obj, dict):
                            latest = obj
                            self.lines += 1
                    except Exception:
                        self.errors += 1
                    buf = bytearray()
            elif c != 13:
                buf.append(c)
                # A line this long means the stream desynced; drop it.
                if len(buf) > MAX_LINE:
                    buf = bytearray()
                    self.errors += 1

        self._buf = buf
        return latest
