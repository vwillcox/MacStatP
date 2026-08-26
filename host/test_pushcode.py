"""Tests for the raw REPL transfer.

    python3 host/test_pushcode.py

No board required: a fake serial port plays the part. Every check here
corresponds to something that actually wedged a Presto during
development, which is the only reason to test protocol plumbing at all.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pushcode

PASSED, FAILED = [], []


def check(label, ok, detail=None):
    (PASSED if ok else FAILED).append(label)
    print("  %-4s %s%s" % ("ok" if ok else "FAIL", label,
                           "" if ok or detail is None else "  -> %r" % (detail,)))


class FakeSerial:
    """Replies the way a board in raw REPL does."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.written = bytearray()
        self.buf = bytearray()

    def write(self, data):
        self.written += data
        if self.replies:
            self.buf += self.replies.pop(0)
        return len(data)

    def flush(self):
        pass

    def read(self, n=1):
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def reset_input_buffer(self):
        self.buf.clear()


def test_reply_parsing():
    print("reply parsing")
    # A whole reply arriving in one chunk is the normal case; anything
    # read past the terminator has to survive for the next command.
    ser = FakeSerial([b"OK2\r\n\x04\x04>"])
    b = pushcode.Board(ser)
    b.raw_paste = False
    check("stdout is returned", b.exec_("print(1+1)").strip() == "2")

    # 1.29 does not always leave the OK in the buffer by the time we look.
    ser = FakeSerial([b"7\r\n\x04\x04>"])
    b = pushcode.Board(ser)
    b.raw_paste = False
    check("a missing OK is tolerated", b.exec_("x").strip() == "7")


def test_errors_surface():
    print("errors")
    ser = FakeSerial([b"OK\x04Traceback: boom\x04>"])
    b = pushcode.Board(ser)
    b.raw_paste = False
    try:
        b.exec_("bad")
        check("a traceback is raised, not swallowed", False)
    except pushcode.PushError as e:
        check("a traceback is raised, not swallowed", "boom" in str(e), e)


def test_leftovers_are_kept():
    print("leftover bytes")
    # Two replies in one read: losing the tail of the first stalled every
    # command after it.
    ser = FakeSerial([b"OK1\r\n\x04\x04>OK2\r\n\x04\x04>"])
    b = pushcode.Board(ser)
    b.raw_paste = False
    first = b.exec_("a").strip()
    second = b.exec_("b").strip()
    check("first reply parsed", first == "1", first)
    check("second reply came from the leftovers", second == "2", second)


def test_missing_files_are_caught():
    print("missing device files")
    try:
        pushcode.push("/dev/null", "/nonexistent")
        check("a missing bundle is reported", False)
    except pushcode.PushError as e:
        check("a missing bundle is reported", "missing" in str(e), e)
    except Exception as e:
        check("a missing bundle is reported", False, e)


def test_soft_reset_is_part_of_entering_raw():
    print("entering raw mode")
    src = open(os.path.join(HERE, "pushcode.py")).read()
    body = src[src.index("def enter_raw"):src.index("def exit_raw")]
    # Without this the desk pet's Bluetooth tasks keep running and the
    # first file write blocks forever.
    check("a soft reset follows the raw prompt", 'b"\\x04"' in body)
    check("raw mode is left first, in case we are already in it",
          'b"\\r\\x02"' in body)


for t in (test_reply_parsing, test_errors_surface, test_leftovers_are_kept,
          test_missing_files_are_caught,
          test_soft_reset_is_part_of_entering_raw):
    t()

print("\n%d passed, %d failed" % (len(PASSED), len(FAILED)))
sys.exit(1 if FAILED else 0)
