import unittest
import struct
import json
import queue
import time

from pager_q import (
    kiss_escape,
    kiss_unescape,
    build_kiss_frame,
    next_msg_id,
    format_text_message,
    format_ack_message,
    is_ack,
    parse_msg_id,
    enqueue_message,
    handle_received_body,
    send_control_cmd,
    recv_control_msg,
    get_status,
    channel_is_clear,
    FEND,
    FESC,
    TFEND,
    TFESC,
    CMD_DATA,
    CALLSIGN,
)


class TestKissEscape(unittest.TestCase):
    def test_no_special_bytes(self):
        data = b"hello"
        self.assertEqual(kiss_escape(data), b"hello")

    def test_escape_fend(self):
        data = bytes([0xC0])
        self.assertEqual(kiss_escape(data), FESC + TFEND)

    def test_escape_fesc(self):
        data = bytes([0xDB])
        self.assertEqual(kiss_escape(data), FESC + TFESC)

    def test_escape_both(self):
        data = bytes([0x01, 0xC0, 0x02, 0xDB, 0x03])
        expected = bytes([0x01]) + FESC + TFEND + bytes([0x02]) + FESC + TFESC + bytes([0x03])
        self.assertEqual(kiss_escape(data), expected)

    def test_roundtrip(self):
        original = bytes(range(256))
        self.assertEqual(kiss_unescape(kiss_escape(original)), original)

    def test_roundtrip_fend_fesc_only(self):
        data = bytes([0xC0, 0xDB, 0xC0, 0xDB])
        self.assertEqual(kiss_unescape(kiss_escape(data)), data)


class TestKissUnescape(unittest.TestCase):
    def test_no_escapes(self):
        data = b"hello"
        self.assertEqual(kiss_unescape(data), b"hello")

    def test_unescape_fend(self):
        data = FESC + TFEND
        self.assertEqual(kiss_unescape(data), bytes([0xC0]))

    def test_unescape_fesc(self):
        data = FESC + TFESC
        self.assertEqual(kiss_unescape(data), bytes([0xDB]))

    def test_unknown_escape(self):
        # FESC followed by unknown byte passes through the second byte
        data = FESC + bytes([0x41])
        self.assertEqual(kiss_unescape(data), bytes([0x41]))

    def test_trailing_fesc(self):
        # FESC at end of data with no following byte is treated as literal
        data = bytes([0x41]) + FESC
        result = kiss_unescape(data)
        # last byte 0xDB has no pair, so it's appended as-is
        self.assertEqual(result, bytes([0x41, 0xDB]))

    def test_empty(self):
        self.assertEqual(kiss_unescape(b""), b"")


class TestNextMsgId(unittest.TestCase):
    def test_first_id(self):
        msg_id, counter = next_msg_id("A", 1)
        self.assertEqual(msg_id, "A1")
        self.assertEqual(counter, 2)

    def test_sequential(self):
        counter = 1
        ids = []
        for _ in range(5):
            msg_id, counter = next_msg_id("B", counter)
            ids.append(msg_id)
        self.assertEqual(ids, ["B1", "B2", "B3", "B4", "B5"])

    def test_multi_char_station(self):
        msg_id, counter = next_msg_id("XY", 10)
        self.assertEqual(msg_id, "XY10")
        self.assertEqual(counter, 11)


class TestBuildKissFrame(unittest.TestCase):
    def test_simple_frame(self):
        frame = build_kiss_frame("hello")
        self.assertTrue(frame.startswith(FEND))
        self.assertTrue(frame.endswith(FEND))
        # second byte should be CMD_DATA
        self.assertEqual(frame[1:2], CMD_DATA)
        # payload should be escaped text
        inner = frame[2:-1]
        self.assertEqual(kiss_unescape(inner), b"hello")

    def test_frame_with_special_chars(self):
        # text that when encoded produces 0xC0 bytes
        text = "KO6NOB>CQ:test"
        frame = build_kiss_frame(text)
        self.assertTrue(frame.startswith(FEND))
        self.assertTrue(frame.endswith(FEND))
        inner = frame[2:-1]
        self.assertEqual(kiss_unescape(inner), text.encode("utf-8"))


class TestFormatMessages(unittest.TestCase):
    def test_format_text_message(self):
        result = format_text_message("A1", "Hello world")
        self.assertEqual(result, "KO6NOB>CQ:[A1] Hello world")

    def test_format_ack_message(self):
        result = format_ack_message("B5")
        self.assertEqual(result, "KO6NOB>CQ:ACK:B5")

    def test_format_text_preserves_content(self):
        result = format_text_message("X99", "test 123 !@#")
        self.assertIn("[X99]", result)
        self.assertIn("test 123 !@#", result)
        self.assertTrue(result.startswith(f"{CALLSIGN}>CQ:"))


class TestIsAck(unittest.TestCase):
    def test_ack_message(self):
        self.assertTrue(is_ack("ACK:A1"))

    def test_ack_with_longer_id(self):
        self.assertTrue(is_ack("ACK:XY99"))

    def test_text_message(self):
        self.assertFalse(is_ack("[A1] Hello"))

    def test_empty(self):
        self.assertFalse(is_ack(""))

    def test_ack_prefix_only(self):
        self.assertTrue(is_ack("ACK:"))

    def test_almost_ack(self):
        self.assertFalse(is_ack("ACKNOWLEDGE"))
        self.assertFalse(is_ack("ack:A1"))


class TestParseMsgId(unittest.TestCase):
    def test_standard_message(self):
        self.assertEqual(parse_msg_id("[A1] Hello"), "A1")

    def test_longer_id(self):
        self.assertEqual(parse_msg_id("[XY99] test"), "XY99")

    def test_no_brackets(self):
        self.assertIsNone(parse_msg_id("Hello world"))

    def test_empty(self):
        self.assertIsNone(parse_msg_id(""))

    def test_unclosed_bracket(self):
        self.assertIsNone(parse_msg_id("[A1 Hello"))

    def test_bracket_not_at_start(self):
        self.assertIsNone(parse_msg_id("x[A1] Hello"))

    def test_empty_brackets(self):
        self.assertEqual(parse_msg_id("[] Hello"), "")


class TestEnqueueMessage(unittest.TestCase):
    def test_enqueue_single(self):
        q = queue.Queue()
        depth = enqueue_message(q, "msg1")
        self.assertEqual(depth, 1)
        self.assertEqual(q.qsize(), 1)

    def test_enqueue_multiple(self):
        q = queue.Queue()
        enqueue_message(q, "msg1")
        enqueue_message(q, "msg2")
        depth = enqueue_message(q, "msg3")
        self.assertEqual(depth, 3)

    def test_enqueue_includes_timestamp(self):
        q = queue.Queue()
        before = time.time()
        enqueue_message(q, "msg")
        after = time.time()
        message, ts = q.get()
        self.assertEqual(message, "msg")
        self.assertGreaterEqual(ts, before)
        self.assertLessEqual(ts, after)


class TestHandleReceivedBody(unittest.TestCase):
    def test_ack_message(self):
        q = queue.Queue()
        result_type, detail = handle_received_body("ACK:A3", q)
        self.assertEqual(result_type, "ack")
        self.assertEqual(detail, "A3")
        # ACK should NOT enqueue anything
        self.assertTrue(q.empty())

    def test_text_message_enqueues_ack(self):
        q = queue.Queue()
        result_type, detail = handle_received_body("[B5] Hello from B", q)
        self.assertEqual(result_type, "text")
        msg_id, body, ack_depth = detail
        self.assertEqual(msg_id, "B5")
        self.assertEqual(body, "[B5] Hello from B")
        self.assertEqual(ack_depth, 1)
        # check the queued ACK
        ack_msg, ts = q.get()
        self.assertEqual(ack_msg, f"{CALLSIGN}>CQ:ACK:B5")

    def test_text_without_msg_id(self):
        q = queue.Queue()
        result_type, detail = handle_received_body("plain text", q)
        self.assertEqual(result_type, "text")
        msg_id, body, ack_depth = detail
        self.assertIsNone(msg_id)
        self.assertEqual(body, "plain text")
        self.assertIsNone(ack_depth)
        self.assertTrue(q.empty())

    def test_multiple_texts_queue_multiple_acks(self):
        q = queue.Queue()
        handle_received_body("[C1] first", q)
        handle_received_body("[C2] second", q)
        self.assertEqual(q.qsize(), 2)
        ack1, _ = q.get()
        ack2, _ = q.get()
        self.assertIn("ACK:C1", ack1)
        self.assertIn("ACK:C2", ack2)


class TestControlPortProtocol(unittest.TestCase):
    """Test the length-prefixed JSON wire protocol using socket pairs."""

    def _make_pair(self):
        """Create a connected pair of sockets for testing."""
        import socket
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        peer, _ = server.accept()
        server.close()
        return client, peer

    def test_send_and_recv_roundtrip(self):
        client, peer = self._make_pair()
        try:
            cmd = {"cmd": "get_status"}
            send_control_cmd(client, cmd)
            # read from the peer side manually
            header = peer.recv(4)
            length = struct.unpack(">I", header)[0]
            body = peer.recv(length)
            received = json.loads(body.decode("utf-8"))
            self.assertEqual(received, cmd)
        finally:
            client.close()
            peer.close()

    def test_recv_control_msg(self):
        client, peer = self._make_pair()
        try:
            response = {"ok": True, "channel_state": "idle", "ptt_on": False}
            data = json.dumps(response).encode("utf-8")
            peer.sendall(struct.pack(">I", len(data)) + data)
            received = recv_control_msg(client)
            self.assertEqual(received, response)
        finally:
            client.close()
            peer.close()

    def test_recv_large_message(self):
        client, peer = self._make_pair()
        try:
            response = {"data": "x" * 10000}
            data = json.dumps(response).encode("utf-8")
            peer.sendall(struct.pack(">I", len(data)) + data)
            received = recv_control_msg(client)
            self.assertEqual(received, response)
        finally:
            client.close()
            peer.close()

    def test_recv_closed_connection_raises(self):
        client, peer = self._make_pair()
        peer.close()
        with self.assertRaises(ConnectionError):
            recv_control_msg(client)
        client.close()

    def test_get_status_skips_events(self):
        """get_status should skip broadcast event messages and return the status reply."""
        client, peer = self._make_pair()
        try:
            import threading

            rx_frame_event = {
                "event": "rx_frame",
                "seq": 6,
                "snr": 13.7,
                "size": 21,
            }
            status_reply = {
                "channel_state": "idle",
                "ptt_on": False,
                "ok": True,
            }

            def respond():
                # read the get_status command
                header = peer.recv(4)
                length = struct.unpack(">I", header)[0]
                peer.recv(length)
                # send an rx_frame event first, then the real reply
                for msg in [rx_frame_event, status_reply]:
                    data = json.dumps(msg).encode("utf-8")
                    peer.sendall(struct.pack(">I", len(data)) + data)

            t = threading.Thread(target=respond)
            t.start()
            result = get_status(client)
            t.join()
            self.assertEqual(result, status_reply)
            self.assertNotIn("event", result)
        finally:
            client.close()
            peer.close()

    def test_get_status_skips_multiple_events(self):
        """get_status should skip any number of events before the reply."""
        client, peer = self._make_pair()
        try:
            import threading

            events = [
                {"event": "rx_frame", "seq": 1},
                {"event": "config_changed", "modem_type": "ofdm"},
                {"event": "rx_frame", "seq": 2},
            ]
            status_reply = {"channel_state": "rx", "ptt_on": False, "ok": True}

            def respond():
                header = peer.recv(4)
                length = struct.unpack(">I", header)[0]
                peer.recv(length)
                for msg in events + [status_reply]:
                    data = json.dumps(msg).encode("utf-8")
                    peer.sendall(struct.pack(">I", len(data)) + data)

            t = threading.Thread(target=respond)
            t.start()
            result = get_status(client)
            t.join()
            self.assertEqual(result, status_reply)
        finally:
            client.close()
            peer.close()


class TestChannelIsClear(unittest.TestCase):
    # --- actual modem73 field names (state/channel_busy/ptt) ---
    def test_actual_idle_clear(self):
        status = {"state": "IDLE", "channel_busy": False, "ptt": False}
        self.assertTrue(channel_is_clear(status))

    def test_actual_backoff(self):
        status = {"state": "BACKOFF", "channel_busy": True, "ptt": False}
        self.assertFalse(channel_is_clear(status))

    def test_actual_rx(self):
        status = {"state": "RX", "channel_busy": True, "ptt": False}
        self.assertFalse(channel_is_clear(status))

    def test_actual_tx(self):
        status = {"state": "TX", "channel_busy": False, "ptt": True}
        self.assertFalse(channel_is_clear(status))

    def test_actual_idle_but_ptt(self):
        status = {"state": "IDLE", "channel_busy": False, "ptt": True}
        self.assertFalse(channel_is_clear(status))

    def test_actual_idle_but_channel_busy(self):
        status = {"state": "IDLE", "channel_busy": True, "ptt": False}
        self.assertFalse(channel_is_clear(status))

    # --- doc field names (channel_state/ptt_on) fallback ---
    def test_doc_idle_not_transmitting(self):
        self.assertTrue(channel_is_clear({"channel_state": "idle", "ptt_on": False}))

    def test_doc_idle_but_ptt_on(self):
        self.assertFalse(channel_is_clear({"channel_state": "idle", "ptt_on": True}))

    def test_doc_rx_state(self):
        self.assertFalse(channel_is_clear({"channel_state": "rx", "ptt_on": False}))

    def test_doc_tx_state(self):
        self.assertFalse(channel_is_clear({"channel_state": "tx", "ptt_on": True}))

    # --- edge cases ---
    def test_missing_all_fields(self):
        self.assertFalse(channel_is_clear({}))

    def test_missing_ptt_defaults_busy(self):
        self.assertFalse(channel_is_clear({"channel_state": "idle"}))

    def test_extra_fields_ignored(self):
        status = {
            "state": "IDLE",
            "channel_busy": False,
            "ptt": False,
            "occupancy_pct": 42,
            "population": 3,
        }
        self.assertTrue(channel_is_clear(status))


if __name__ == "__main__":
    unittest.main()
