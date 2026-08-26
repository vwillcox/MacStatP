"""Copy the dashboard onto a Presto over USB, without mpremote.

The installed app has no command line tools to lean on, so this speaks
MicroPython's raw REPL directly: interrupt whatever is running, drop into
raw mode, write the files, then reset the board.

    \\r\\x03\\x03   interrupt a running program
    \\x01         enter raw REPL      -> "raw REPL; CTRL-B to exit\\r\\n>"
    <code>\\x04   run it              -> "OK" <stdout> \\x04 <stderr> \\x04 ">"
    \\x02         back to the normal REPL

Globals persist between submissions in raw mode, which is what lets a file
be opened once and written in chunks.
"""

import base64
import glob
import os
import time

DEVICE_DIR = None       # set by the caller; where the .py files live
CHUNK = 4096            # bytes per write; raw-paste handles the flow
READ_TIMEOUT = 0.05     # a long serial timeout dominated the transfer

CORE_FILES = ("font_data.py", "font.py", "theme.py", "widgets.py",
              "dashboard.py", "pages.py", "link.py", "storage.py",
              "main.py")


class PushError(Exception):
    pass


def find_ports():
    found = []
    for pattern in ("/dev/cu.usbmodem*", "/dev/cu.usbserial*"):
        found.extend(sorted(glob.glob(pattern)))
    return found


class Board:
    """A Presto at the other end of a serial port, in raw REPL mode."""

    def __init__(self, ser, log=None):
        self.ser = ser
        self._log = log or (lambda _m: None)
        # Anything read past a terminator belongs to the next reply, so it
        # is kept rather than dropped. Losing it stalled every exec after
        # the first, because the reply arrived in one chunk.
        self._buf = bytearray()
        self.raw_paste = True

    # ── plumbing ──────────────────────────────────────────────────────
    def _read_until(self, token, timeout=10.0):
        deadline = time.time() + timeout
        while True:
            at = self._buf.find(token)
            if at >= 0:
                end = at + len(token)
                out = bytes(self._buf[:end])
                del self._buf[:end]
                return out
            if time.time() > deadline:
                raise PushError(
                    "board did not answer (waiting for %r, saw %r)"
                    % (token, bytes(self._buf[-120:])))
            chunk = self.ser.read(256)
            if chunk:
                self._buf += chunk
            else:
                time.sleep(0.01)

    def enter_raw(self, attempts=3):
        """Get to a raw REPL prompt from whatever state the board is in.

        A previous attempt may have died mid-transfer and left it in raw
        or raw-paste mode, so this backs out first rather than assuming a
        friendly REPL.
        """
        last = None
        for attempt in range(attempts):
            self.ser.reset_input_buffer()
            self._buf.clear()
            # Ctrl-B leaves raw mode; two Ctrl-Cs break a running program
            # (the first may only interrupt a sleep).
            self.ser.write(b"\r\x02")
            self.ser.flush()
            time.sleep(0.1)
            self.ser.write(b"\r\x03\x03")
            self.ser.flush()
            time.sleep(0.25)
            self.ser.reset_input_buffer()
            self._buf.clear()
            self.ser.write(b"\r\x01")
            self.ser.flush()
            try:
                self._read_until(b"raw REPL; CTRL-B to exit\r\n>", timeout=4)
                # Soft reset before touching the filesystem. Ctrl-C stops
                # the main program but leaves asyncio tasks scheduled, and
                # the desk pet's Bluetooth tasks kept running: opening a
                # file for writing then blocked and took the board with
                # it. A soft reset from raw mode clears everything and
                # does not re-run main.py.
                self.ser.write(b"\x04")
                self.ser.flush()
                self._read_until(b"raw REPL; CTRL-B to exit\r\n>", timeout=8)
                self.raw_paste = True
                return
            except PushError as e:
                last = e
                self._log("board did not answer, retrying (%d/%d)"
                          % (attempt + 1, attempts))
                time.sleep(0.5)
        raise PushError("could not reach the board's REPL. Unplug it, plug "
                        "it back in and try again. (%s)" % last)

    def exit_raw(self):
        self.ser.write(b"\r\x02")
        self.ser.flush()
        time.sleep(0.1)

    def _raw_paste_write(self, code):
        """Send code under the board's flow control.

        The device's USB receive buffer is only a couple of hundred bytes.
        Writing a whole command at once overflows it and the board simply
        stops answering, so raw-paste mode is used: the board advertises a
        window and asks for more as it consumes what it has.

        Returns False if the firmware has no raw-paste support.
        """
        self.ser.write(b"\x05A\x01")
        self.ser.flush()
        # Expect b"R\x01" then a 2-byte window, or b"R\x00" for no support.
        deadline = time.time() + 3
        while len(self._buf) < 2 and time.time() < deadline:
            chunk = self.ser.read(64)
            if chunk:
                self._buf += chunk
            else:
                time.sleep(0.005)
        if len(self._buf) < 2 or self._buf[0:1] != b"R":
            return False
        if self._buf[1:2] != b"\x01":
            del self._buf[:2]
            return False
        del self._buf[:2]
        while len(self._buf) < 2:
            chunk = self.ser.read(64)
            if chunk:
                self._buf += chunk
            else:
                time.sleep(0.005)
        window = self._buf[0] | (self._buf[1] << 8)
        del self._buf[:2]

        remaining = window
        i = 0
        while i < len(code):
            while remaining == 0:
                b = self.ser.read(1)
                if not b:
                    time.sleep(0.005)
                    continue
                if b == b"\x01":
                    remaining += window
                elif b == b"\x04":     # board gave up early
                    self.ser.write(b"\x04")
                    self.ser.flush()
                    return True
                else:
                    self._buf += b
            n = min(remaining, len(code) - i, window)
            self.ser.write(code[i:i + n])
            self.ser.flush()
            i += n
            remaining -= n
        self.ser.write(b"\x04")        # end of data
        self.ser.flush()
        self._read_until(b"\x04", timeout=10)
        return True

    def exec_(self, code, timeout=15.0):
        """Run code in raw mode and return its stdout."""
        if isinstance(code, str):
            code = code.encode()
        if self.raw_paste:
            if not self._raw_paste_write(code):
                self.raw_paste = False
                self.ser.write(code + b"\x04")
                self.ser.flush()
        else:
            self.ser.write(code + b"\x04")
            self.ser.flush()
        # Reply is [OK] stdout \x04 stderr \x04 ">". The OK is not always
        # still in the buffer by the time we parse, so treat it as optional
        # rather than a precondition.
        reply = self._read_until(b"\x04>", timeout=timeout)
        body = reply[:-2]
        if body.startswith(b"OK"):
            body = body[2:]
        out, _, err = body.partition(b"\x04")
        if err.strip():
            raise PushError(err.decode("utf-8", "replace").strip())
        return out.decode("utf-8", "replace")

    # ── files ─────────────────────────────────────────────────────────
    def put_file(self, name, data):
        self.exec_("f=open(%r,'wb')\nimport ubinascii as _u" % name)
        for i in range(0, len(data), CHUNK):
            blob = base64.b64encode(data[i:i + CHUNK]).decode()
            self.exec_("f.write(_u.a2b_base64('%s'))" % blob)
        self.exec_("f.close()\ndel f")

    def mkdir(self, name):
        self.exec_("import os\ntry: os.mkdir(%r)\nexcept OSError: pass" % name)

    def listdir(self, path="/"):
        out = self.exec_("import os\nprint(sorted(os.listdir(%r)))" % path)
        return out.strip()

    def info(self):
        return self.exec_(
            "import os,sys\n"
            "print(os.uname().machine + '|' + os.uname().release)").strip()

    def reset(self):
        # Leave raw mode first, or the reset is swallowed.
        self.exit_raw()
        self.ser.write(b"\r\x03")
        self.ser.flush()
        time.sleep(0.1)
        self.ser.write(b"import machine\rmachine.reset()\r")
        self.ser.flush()


def push(port, device_dir, extra=None, log=None, reset=True):
    """Write the dashboard to the board. `extra` is {dest: source_dir}."""
    import serial

    log = log or (lambda _m: None)
    files = []
    for name in CORE_FILES:
        path = os.path.join(device_dir, name)
        if not os.path.exists(path):
            raise PushError("missing %s — is the app bundle complete?" % name)
        files.append((name, path))

    for dest, src_dir in (extra or {}).items():
        for src in sorted(glob.glob(os.path.join(src_dir, "*.py"))):
            files.append(("%s/%s" % (dest, os.path.basename(src)), src))

    total = len(files)
    log("Opening %s" % port)
    with serial.Serial(port, 115200, timeout=READ_TIMEOUT,
                       write_timeout=10) as ser:
        board = Board(ser, log)
        log("Interrupting whatever is running")
        board.enter_raw()
        log("Board: %s" % board.info())

        made = set()
        for i, (name, path) in enumerate(files, 1):
            folder = os.path.dirname(name)
            if folder and folder not in made:
                board.mkdir(folder)
                made.add(folder)
            with open(path, "rb") as f:
                data = f.read()
            log("[%d/%d] %s  (%d bytes)" % (i, total, name, len(data)))
            board.put_file(name, data)

        log("Files on the board: %s" % board.listdir())
        if reset:
            log("Resetting")
            board.reset()
        else:
            board.exit_raw()
    log("Done — %d files written." % total)
    return total
