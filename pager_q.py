import socket
import struct
import json
import threading
import queue
import sys
import time

# modem73 TCP settings
HOST = "127.0.0.1"
PORT = 8001
CONTROL_PORT = 8073
BUSY_POLL_INTERVAL = 0.1  # seconds between channel-clear polls

FEND = b"\xc0"
FESC = b"\xdb"
TFEND = b"\xdc"
TFESC = b"\xdd"
CMD_DATA = b"\x00"

CALLSIGN = "KO6NOB"


def kiss_escape(data):
    """Escape special bytes in the payload."""
    out = bytearray()
    for b in data:
        if b == 0xC0:
            out += FESC + TFEND
        elif b == 0xDB:
            out += FESC + TFESC
        else:
            out.append(b)
    return bytes(out)


def kiss_unescape(data):
    """Unescape KISS payload bytes."""
    out = bytearray()
    i = 0
    while i < len(data):
        if data[i] == 0xDB and i + 1 < len(data):
            if data[i + 1] == 0xDC:
                out.append(0xC0)
            elif data[i + 1] == 0xDD:
                out.append(0xDB)
            else:
                out.append(data[i + 1])
            i += 2
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def build_kiss_frame(text):
    """Build a KISS data frame from a text string."""
    payload = kiss_escape(text.encode("utf-8"))
    return FEND + CMD_DATA + payload + FEND


def next_msg_id(station_id, counter):
    """Generate the next message-id and return (msg_id, new_counter)."""
    msg_id = f"{station_id}{counter}"
    return msg_id, counter + 1


def format_text_message(msg_id, text):
    """Format a text message with callsign header and message-id."""
    return f"{CALLSIGN}>CQ:[{msg_id}] {text}"


def format_ack_message(msg_id):
    """Format an ACK message with callsign header."""
    return f"{CALLSIGN}>CQ:ACK:{msg_id}"


def is_ack(body):
    """Check if a message body (after callsign prefix) is an ACK."""
    return body.startswith("ACK:")


def parse_msg_id(body):
    """Extract message-id from a text message body (after callsign prefix).

    Expects format like '[A1] Hello'. Returns the id string or None.
    """
    if body.startswith("["):
        end = body.find("]")
        if end != -1:
            return body[1:end]
    return None


def enqueue_message(send_q, message_string):
    """Add a message to the send queue with a timestamp. Returns queue depth."""
    send_q.put((message_string, time.time()))
    return send_q.qsize()


def handle_received_body(body, send_q):
    """Process a received message body. Returns a (type, detail) tuple.

    type is 'ack' or 'text'.
    For 'ack', detail is the acked msg_id.
    For 'text', detail is (msg_id, body, ack_queue_depth) where msg_id may be None.
    """
    if is_ack(body):
        acked_id = body[4:]  # strip 'ACK:'
        return ("ack", acked_id)
    else:
        msg_id = parse_msg_id(body)
        ack_depth = None
        if msg_id:
            ack_msg = format_ack_message(msg_id)
            ack_depth = enqueue_message(send_q, ack_msg)
        return ("text", (msg_id, body, ack_depth))


def send_control_cmd(ctrl_sock, cmd_dict):
    """Send a JSON command over the control port (4-byte big-endian length prefix)."""
    data = json.dumps(cmd_dict).encode("utf-8")
    ctrl_sock.sendall(struct.pack(">I", len(data)) + data)


def recv_control_msg(ctrl_sock):
    """Receive a length-prefixed JSON message from the control port."""
    header = b""
    while len(header) < 4:
        chunk = ctrl_sock.recv(4 - len(header))
        if not chunk:
            raise ConnectionError("control port closed")
        header += chunk
    length = struct.unpack(">I", header)[0]
    body = b""
    while len(body) < length:
        chunk = ctrl_sock.recv(length - len(body))
        if not chunk:
            raise ConnectionError("control port closed")
        body += chunk
    return json.loads(body.decode("utf-8"))


def get_status(ctrl_sock):
    """Query modem73 status. Returns the response dict.

    Skips over any broadcast event messages (rx_frame, config_changed)
    that arrive before the status reply.
    """
    send_control_cmd(ctrl_sock, {"cmd": "get_status"})
    while True:
        msg = recv_control_msg(ctrl_sock)
        if "event" not in msg:
            return msg


def channel_is_clear(status):
    """Check if the channel is clear for transmitting.

    Checks both possible field name conventions from modem73:
    - state/channel_busy/ptt (observed from actual modem73 responses)
    - channel_state/ptt_on (from CONTROL_PORT.md docs)

    Clear means: state is IDLE (not BACKOFF, TX, RX, etc.),
    channel is not busy, and PTT is off.
    """
    # Use actual field names, falling back to doc field names
    state = status.get("state", status.get("channel_state", ""))
    busy = status.get("channel_busy", None)
    ptt = status.get("ptt", status.get("ptt_on", True))

    if busy is not None:
        return not busy and not ptt
    return state.upper() == "IDLE" and not ptt


def wait_for_clear_channel(ctrl_sock, poll_interval=BUSY_POLL_INTERVAL):
    """Poll get_status until the channel is clear. Returns the final status dict."""
    status = get_status(ctrl_sock)
    waited = False
    while not channel_is_clear(status):
        if not waited:
            state = status.get("state", status.get("channel_state", "?"))
            print(f"\n[~wait]  channel busy (state={state}), waiting...")
            print("pager_q> ", end="", flush=True)
            waited = True
        time.sleep(poll_interval)
        status = get_status(ctrl_sock)
    return status


def sender_loop(sock, send_q, ctrl_sock):
    """Pull messages from the queue, wait for clear channel, then send."""
    try:
        while True:
            message_string, queued_time = send_q.get()
            wait_for_clear_channel(ctrl_sock)
            frame = build_kiss_frame(message_string)
            sock.sendall(frame)
            wait = time.time() - queued_time
            depth = send_q.qsize()

            # extract display text from the message
            prefix = f"{CALLSIGN}>CQ:"
            body = message_string
            if message_string.startswith(prefix):
                body = message_string[len(prefix):]

            if is_ack(body):
                print(f'[>sent]  {body} | queue: {depth} | wait: {wait:.3f}s')
            else:
                # extract short text for display
                display = body
                mid = parse_msg_id(body)
                if mid:
                    # body is like '[A1] Hello'
                    after_bracket = body.find("] ")
                    if after_bracket != -1:
                        display = body[after_bracket + 2:]
                    label = mid
                else:
                    label = "?"
                print(f'[>sent]  {label} "{display}" | queue: {depth} | wait: {wait:.3f}s')
            print("pager_q> ", end="", flush=True)
    except OSError:
        pass


def receive_loop(sock, send_q):
    """Listen for incoming KISS frames and handle them."""
    buf = bytearray()
    try:
        while True:
            chunk = sock.recv(1024)
            if not chunk:
                print("\n[connection closed by modem73]")
                break
            buf += chunk

            while True:
                start = buf.find(0xC0)
                if start == -1:
                    buf.clear()
                    break
                end = buf.find(0xC0, start + 1)
                if end == -1:
                    break
                raw = buf[start + 1 : end]
                del buf[: end + 1]

                if len(raw) < 1:
                    continue
                cmd = raw[0]
                payload = kiss_unescape(raw[1:])
                try:
                    text = payload.decode("utf-8")
                except UnicodeDecodeError:
                    text = payload.hex()

                # strip callsign prefix to get body
                prefix = f"{CALLSIGN}>CQ:"
                if text.startswith(prefix):
                    body = text[len(prefix):]
                else:
                    body = text

                result_type, detail = handle_received_body(body, send_q)

                if result_type == "ack":
                    print(f"\n[<ack]   ACK:{detail}")
                else:
                    msg_id, full_body, ack_depth = detail
                    print(f"\n[<recv]  {full_body}")
                    if msg_id and ack_depth is not None:
                        print(f"[+ack]   ACK:{msg_id} | queue: {ack_depth}")
                print("pager_q> ", end="", flush=True)
    except OSError:
        pass


def main():
    if len(sys.argv) < 2:
        print("Usage: python pager_q.py <station-id>")
        sys.exit(1)

    station_id = sys.argv[1]
    counter = 1

    print(f"Connecting to modem73 KISS port at {HOST}:{PORT}...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((HOST, PORT))
    except ConnectionRefusedError:
        print("Error: could not connect to KISS port. Is modem73 running?")
        sys.exit(1)

    print(f"Connecting to modem73 control port at {HOST}:{CONTROL_PORT}...")
    try:
        ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ctrl_sock.connect((HOST, CONTROL_PORT))
    except ConnectionRefusedError:
        print("Error: could not connect to control port. Is modem73 running?")
        sock.close()
        sys.exit(1)

    print(f"Connected. Station ID: {station_id}")
    print("Type a message and press Enter to send.")
    print("Type 'quit' to exit.\n")

    send_q = queue.Queue()

    tx = threading.Thread(target=sender_loop, args=(sock, send_q, ctrl_sock), daemon=True)
    tx.start()

    rx = threading.Thread(target=receive_loop, args=(sock, send_q), daemon=True)
    rx.start()

    try:
        while True:
            text = input("pager_q> ")
            if text.strip().lower() == "quit":
                break
            if text.strip():
                msg_id, counter = next_msg_id(station_id, counter)
                message = format_text_message(msg_id, text.strip())
                depth = enqueue_message(send_q, message)
                print(f'[+queue] {msg_id} "{text.strip()}" | queue: {depth}')
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        sock.close()
        ctrl_sock.close()
        print("Disconnected.")


if __name__ == "__main__":
    main()
