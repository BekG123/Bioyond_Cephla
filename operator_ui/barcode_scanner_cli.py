"""Terminal tester for the scanner's TCP start/stop protocol (no robot motion).

Run with --help for examples. Uses only the Python standard library.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import socket
import time
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return number


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def scan_once(host, port, source_ip, timeout, log_dir):
    """Send one trigger; receive one EOT-framed result; always attempt stop.

    Never resends start. A timeout or incomplete frame is not a successful read.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / (
        "scan_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "_" + uuid4().hex[:8] + ".json"
    )
    record = dict(at=utc_now(), host=host, port=port, source=source_ip,
                  timeout_s=timeout, events=[], robot_motion_commands=False,
                  automatic_retries=False, result="pending", barcode=None)

    def save():
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    def event(**data):
        record["events"].append(dict(at=utc_now(), mono_ns=time.monotonic_ns(), **data))
        save()

    save()  # Verify receipt storage before sending anything.
    raw = bytearray()
    connected = False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        if source_ip:
            sock.bind((source_ip, 0))
        sock.connect((host, port))
        connected = True
        record["connected"] = True
        record["local_address"] = list(sock.getsockname())
        event(tx_attempt="start")
        sock.sendall(b"start")
        event(tx="start")
        deadline = time.monotonic() + timeout
        while b"\x04" not in raw:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                record["result"] = "timeout"
                break
            sock.settimeout(remaining)
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                record["result"] = "timeout"
                break
            if not chunk:
                record["result"] = "incomplete"
                break
            raw.extend(chunk)
            event(rx_hex=chunk.hex(), rx_text=chunk.decode("utf-8", errors="replace"))
            if len(raw) > 65536:
                raise ValueError("Response exceeds 64 KiB")

        if b"\x04" in raw:
            payload = bytes(raw).split(b"\x04", 1)[0]
            # Preserve payload whitespace; remove only the protocol terminator.
            text = payload.decode("utf-8", errors="strict")
            record["result"] = "no_read" if payload == b"NG" else (
                "decoded" if payload else "empty_response")
            if record["result"] == "decoded":
                record["barcode"] = text
    except KeyboardInterrupt:
        record["result"] = "interrupted"
    except (OSError, ValueError) as error:
        record.update(result="error", error=str(error))
    finally:
        if connected:
            try:
                sock.settimeout(min(timeout, 1.0))
                sock.sendall(b"stop")
                record["events"].append(dict(at=utc_now(), mono_ns=time.monotonic_ns(), tx="stop"))
            except OSError as error:
                record["stop_error"] = str(error)
        sock.close()
        record.update(response_hex=raw.hex(),
                      response_text=raw.decode("utf-8", errors="replace"),
                      framed=b"\x04" in raw, finished_at=utc_now())
        save()
    if record['result'] == 'decoded':
        try:
            from plate_registry import PlateRegistry
            plate = PlateRegistry().record_scan(record, str(path.resolve()))
            record['plate_registry'] = dict(saved=True, plate_id=plate['plate_id'], revision=plate['revision'])
        except Exception as error:
            # The scan receipt survives a database failure; the CLI must surface it.
            record['plate_registry'] = dict(saved=False, error=str(error))
        save()
    return record, path


def parser():
    result = argparse.ArgumentParser(
        description="Trigger the barcode/QR reader and print decoded text. No robot motion.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples (from the repository root):
  py operator_ui/barcode_scanner_cli.py
  py operator_ui/barcode_scanner_cli.py --interactive
  py operator_ui/barcode_scanner_cli.py --continuous --interval 1
  py operator_ui/barcode_scanner_cli.py --count 10 --timeout 5

NG means no read. Timeout is the maximum wait, not the scanner's exposure setting.
Ctrl+C stops testing. Repeated modes stop on transport errors or incomplete replies.
Receipts include raw bytes; a decoded reply does not identify the symbology.
Exit codes: 0=last scan decoded, 1=last scan NG, 2=error/incomplete, 130=interrupted.
""")
    result.add_argument("--host", default="192.168.1.10", help="scanner IP (default: %(default)s)")
    result.add_argument("--port", type=positive_int, default=1024, help="TCP port (default: %(default)s)")
    result.add_argument("--source-ip", default="192.168.1.15",
                        help="local adapter IP; use 'auto' for OS routing (default: %(default)s)")
    result.add_argument("--timeout", type=positive_seconds, default=5.0,
                        help="connect/read timeout in seconds (default: %(default)s)")
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--count", type=positive_int, default=1, help="number of scans (default: 1)")
    modes.add_argument("--continuous", action="store_true", help="scan repeatedly until Ctrl+C")
    modes.add_argument("--interactive", action="store_true", help="press Enter to scan, q to quit")
    result.add_argument("--interval", type=positive_seconds, default=1.0,
                        help="seconds between repeated scans (default: %(default)s)")
    result.add_argument("--log-dir", type=Path,
                        default=Path(__file__).resolve().parent / "reports" / "barcode_scanner",
                        help="directory for per-scan JSON receipts")
    return result


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.port > 65535:
        cli.error("--port must be between 1 and 65535")
    source = None if args.source_ip.lower() == "auto" else args.source_ip
    print(f"Scanner {args.host}:{args.port}; source {source or 'auto'}", flush=True)
    last_code = 0
    index = 0
    try:
        while args.continuous or args.interactive or index < args.count:
            if args.interactive:
                answer = input("Position the code. Enter=scan, q=quit: ").strip().lower()
                if answer in ("q", "quit", "exit"):
                    break
                if answer:
                    continue
            index += 1
            print(f"Scan {index}: triggering...", flush=True)
            record, receipt = scan_once(args.host, args.port, source, args.timeout, args.log_dir)
            status = record["result"]
            value = json.dumps(record["barcode"], ensure_ascii=True) if status == "decoded" else ""
            print(f"{status.upper()} {value}", flush=True)
            print(f"Receipt: {receipt}", flush=True)
            if record.get('plate_registry', {}).get('saved') is False:
                print('PLATE MEMORY ERROR: '+record['plate_registry']['error'], flush=True)
                return 2
            for key in ("error", "stop_error"):
                if key in record:
                    print(f"{key}: {record[key]}", flush=True)
            last_code = {"decoded": 0, "no_read": 1, "interrupted": 130}.get(status, 2)
            if record.get("stop_error"):
                return 2
            if status not in ("decoded", "no_read"):
                return last_code
            if not args.interactive and (args.continuous or index < args.count):
                time.sleep(args.interval)
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.", flush=True)
        return 130
    except OSError as error:
        print(f"ERROR: {error}", flush=True)
        return 2
    return last_code


if __name__ == "__main__":
    raise SystemExit(main())
