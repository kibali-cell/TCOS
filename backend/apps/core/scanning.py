"""Virus-scanning hook for uploaded files.

STATUS: a real scanner is **not installed** in this release. Unless ``TCOS_CLAMAV_HOST`` points
at a running ClamAV daemon (clamd), every file comes back ``NOT_SCANNED`` and is recorded as
such. With ``TCOS_REQUIRE_VIRUS_SCAN=true`` an upload is refused unless the scanner says CLEAN.
The clamd client below follows the INSTREAM protocol but has not been run against a real
ClamAV (none available when it was written); treat it as untested until it is (docs/STATUS.md).
"""

import socket
import struct

from django.conf import settings

NOT_SCANNED = "NOT_SCANNED"
CLEAN = "CLEAN"
INFECTED = "INFECTED"


class ScannerError(Exception):
    pass


def scan_file(path) -> str:
    host = settings.TCOS_CLAMAV_HOST
    if not host:
        return NOT_SCANNED
    try:
        with socket.create_connection((host, settings.TCOS_CLAMAV_PORT), timeout=15) as conn:
            conn.sendall(b"zINSTREAM\0")
            with open(path, "rb") as handle:
                while chunk := handle.read(64 * 1024):
                    conn.sendall(struct.pack(">I", len(chunk)) + chunk)
            conn.sendall(struct.pack(">I", 0))
            reply = b""
            while data := conn.recv(4096):
                reply += data
                if reply.endswith(b"\0"):
                    break
    except OSError as exc:
        raise ScannerError("The virus scanner could not be reached.") from exc
    text = reply.strip(b"\0").decode(errors="replace")
    if text.endswith("OK"):
        return CLEAN
    if "FOUND" in text:
        return INFECTED
    raise ScannerError("The virus scanner gave an unexpected answer.")
