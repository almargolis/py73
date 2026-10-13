# py73 — Python tools for exercising modem73

Test and characterization tools for [modem73](https://github.com/RFnexus/modem73), a software modem for HF/VHF/UHF radio. This is **not** a finished application — it's a set of scripts for experimenting with modem73's KISS TCP interface, measuring throughput and latency, and exploring channel contention behavior.

## Prerequisites

- [modem73](https://github.com/RFnexus/modem73) running with KISS port (default 8001) and control port (default 8073)
- Python 3.x (no external dependencies)
- A radio and audio interface (e.g. AIOC) — see [Modem73 Settings for 2-Meter](Modem73_Settings_2Meter.md) for setup notes

## Tools

### pager_q.py — Queued pager with ACKs

A two-station messaging tool with message IDs, automatic ACKs, a send queue, and channel-busy detection via modem73's control port.

```
python3 pager_q.py <station-id>
```

`station-id` is a short string (e.g. `A` or `B`) used as the prefix for message IDs. Run one instance per station.

Features:
- Messages are tagged with IDs (e.g. `A1`, `A2`) for tracking
- Received messages are automatically ACKed
- Send queue with timestamps — status output shows queue depth and wait time
- Polls modem73 control port (`get_status`) before each send to check that the channel is clear (not in TX, RX, or CSMA BACKOFF state)

Example output:
```
[+queue] A3 "Hello" | queue: 1
[~wait]  channel busy (state=rx), waiting...
[>sent]  A3 "Hello" | queue: 0 | wait: 0.312s
[<recv]  [B5] Hello from B
[+ack]   ACK:B5 | queue: 1
[<ack]   ACK:A3
```

### pager.py — Simple pager

A minimal send/receive tool over the KISS TCP interface. No message IDs, no ACKs, no queue — just type and send.

```
python3 pager.py
```

### send1.py — One-shot sender

Sends a single hardcoded message and exits. Useful for quick testing.

## Known issues

CSMA collision avoidance does not work perfectly. If two stations send messages at nearly the same time, transmissions can collide. It is not yet clear whether this is a limitation of modem73's CSMA implementation, a timing issue in this Python code, or an inherent challenge in half-duplex radio communication. The control port busy-check helps in most cases but is not a complete solution.

## Future work

- ACK verification with timeout and automatic retransmission
- Better collision avoidance (longer backoff, jitter)
- Throughput and latency measurement reporting

## Tests

```
python3 -m unittest test_pager_q -v
```

Unit tests cover all non-I/O functions: KISS encoding, message formatting, message-id generation, ACK detection, queue operations, control port protocol, and channel-clear logic.

## License

MIT
