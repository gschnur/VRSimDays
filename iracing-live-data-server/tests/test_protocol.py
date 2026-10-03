from __future__ import annotations

import json
import pytest
from irlds import protocol


class TestProtocolEncodeDecode:
    def test_round_trip(self) -> None:
        msg = protocol.encode("hello", {"server_version": "0.1"}, seq=None)
        obj = protocol.decode(msg)
        assert obj["type"] == "hello"
        assert obj["data"]["server_version"] == "0.1"
        assert obj["seq"] is None

    def test_broadcast_seq_round_trip(self) -> None:
        obj = protocol.decode(protocol.encode("lap_update", {}, seq=7))
        assert obj["seq"] == 7

    def test_timestamp_present(self) -> None:
        msg = protocol.encode("status", {}, seq=None)
        obj = protocol.decode(msg)
        assert "ts" in obj
        assert isinstance(obj["ts"], float)

    def test_request_id_echo(self) -> None:
        msg = protocol.encode("reset_ack", {"ok": True}, seq=None, request_id="abc")
        obj = protocol.decode(msg)
        assert obj["request_id"] == "abc"


class TestProtocolDecodeValidation:
    def test_reject_non_string(self) -> None:
        with pytest.raises(ValueError):
            protocol.decode(123)  # type: ignore

    def test_reject_non_object(self) -> None:
        with pytest.raises(ValueError):
            protocol.decode('"hello"')

    def test_reject_missing_type(self) -> None:
        with pytest.raises(ValueError):
            protocol.decode(json.dumps({"data": {}}))

    def test_reject_invalid_json(self) -> None:
        with pytest.raises(ValueError):
            protocol.decode("not json at all")
