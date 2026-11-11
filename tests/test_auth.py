"""Session tokens (app/auth.py): a token made at login must read back on the next request."""
import base64

from app import auth


def test_session_token_round_trips_for_every_second(monkeypatch):
    # The expiry is a whole second, so 1,000 consecutive seconds give 1,000 different
    # signatures; about one raw HMAC digest in nine contains the byte '|' (ticket 25).
    start = 1_800_000_000
    for offset in range(1000):
        monkeypatch.setattr(auth.time, "time", lambda: start + offset)
        assert auth.read_token(auth.make_token(1, "Tester")) == (1, "Tester"), f"rejected at second {offset}"


def test_tampered_token_is_rejected():
    payload, sig = base64.urlsafe_b64decode(auth.make_token(1, "Tester")).rsplit(b"|", 1)

    def encode(p: bytes, s: bytes) -> str:
        return base64.urlsafe_b64encode(p + b"|" + s).decode()

    other_user = payload.replace(b"1|", b"2|", 1)  # claims user 2 under user 1's signature
    flipped = sig[:-1] + (b"0" if sig[-1:] != b"0" else b"1")
    assert auth.read_token(encode(payload, sig)) == (1, "Tester")
    assert auth.read_token(encode(other_user, sig)) is None
    assert auth.read_token(encode(payload, flipped)) is None
    assert auth.read_token("not-a-token") is None
