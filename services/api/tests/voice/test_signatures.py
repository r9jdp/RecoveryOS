from services.api.app.integrations.voice.signatures import (
    elevenlabs_signature,
    twilio_signature,
    verify_elevenlabs_signature,
    verify_twilio_signature,
)


def test_twilio_signature_is_order_independent_and_rejects_tampering() -> None:
    supplied = twilio_signature(
        auth_token="secret",
        url="https://voice.example/v1/voice/status",
        parameters={"CallStatus": "completed", "CallSid": "CA123"},
    )
    assert verify_twilio_signature(
        auth_token="secret",
        url="https://voice.example/v1/voice/status",
        parameters={"CallSid": "CA123", "CallStatus": "completed"},
        supplied=supplied,
    )
    assert not verify_twilio_signature(
        auth_token="secret",
        url="https://voice.example/v1/voice/status",
        parameters={"CallSid": "CA999", "CallStatus": "completed"},
        supplied=supplied,
    )


def test_elevenlabs_signature_binds_timestamp_and_raw_body() -> None:
    body = b'{"event_id":"evt_1"}'
    supplied = elevenlabs_signature(secret="hook-secret", body=body, timestamp="1720000000")
    assert verify_elevenlabs_signature(
        secret="hook-secret", body=body, supplied=supplied, now=1720000000
    )
    assert not verify_elevenlabs_signature(
        secret="hook-secret", body=body + b" ", supplied=supplied, now=1720000000
    )
    assert not verify_elevenlabs_signature(
        secret="hook-secret", body=body, supplied=supplied, now=1720001801
    )
    assert not verify_elevenlabs_signature(
        secret="hook-secret",
        body=body,
        supplied=supplied.replace("t=1720000000", "t=not-a-time"),
        now=1720000000,
    )
