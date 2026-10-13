import socket

# modem73 default KISS TCP port
HOST = "127.0.0.1"
PORT = 8001


def send_kiss_message(data_bytes):
  # Standard KISS Data Frame structure: [FEND (0xC0), CMD (0x00), payload..., FEND (0xC0)]
  FEND = b"\xc0"
  CMD_DATA = b"\x00"

  # Escape special characters if necessary in a full implementation,
  # but simple payload can be wrapped:
  frame = FEND + CMD_DATA + data_bytes + FEND

  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))
    s.sendall(frame)
    print(f"Sent {len(data_bytes)} bytes to modem73.")


if __name__ == "__main__":
  msg = b"Hello from Python to modem73!"
  send_kiss_message(msg)

