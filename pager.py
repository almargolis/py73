import socket
import threading
import sys

# modem73 KISS TCP settings
HOST = "127.0.0.1"
PORT = 8001

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


def send_message(sock, text):
    """Send a text message as a KISS data frame."""
    tagged = f"{CALLSIGN}>CQ:{text}"
    payload = kiss_escape(tagged.encode("utf-8"))
    frame = FEND + CMD_DATA + payload + FEND
    sock.sendall(frame)
    print(f">> Sent: {tagged}")


def receive_loop(sock):
    """Listen for incoming KISS frames and print decoded text."""
    buf = bytearray()
    try:
        while True:
            chunk = sock.recv(1024)
            if not chunk:
                print("\n[connection closed by modem73]")
                break
            buf += chunk

            # extract complete KISS frames from buffer
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
                # first byte is the command/port byte
                cmd = raw[0]
                payload = kiss_unescape(raw[1:])
                try:
                    text = payload.decode("utf-8")
                except UnicodeDecodeError:
                    text = payload.hex()
                print(f"\n<< Received: {text}")
                print("pager> ", end="", flush=True)
    except OSError:
        pass


def main():
    print(f"Connecting to modem73 at {HOST}:{PORT}...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((HOST, PORT))
    except ConnectionRefusedError:
        print("Error: could not connect. Is modem73 running?")
        sys.exit(1)

    print("Connected. Type a message and press Enter to send.")
    print("Type 'quit' to exit.\n")

    # start background receiver thread
    rx = threading.Thread(target=receive_loop, args=(sock,), daemon=True)
    rx.start()

    try:
        while True:
            text = input("pager> ")
            if text.strip().lower() == "quit":
                break
            if text.strip():
                send_message(sock, text)
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        sock.close()
        print("Disconnected.")


if __name__ == "__main__":
    main()
