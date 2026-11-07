import hashlib
import hmac

from config import API_TOKEN


class TokenVerifier:
    def __init__(self, expected: str = API_TOKEN) -> None:
        self.expected = expected

    def verify(self, supplied: str) -> bool:
        return hmac.compare_digest(self.expected, supplied)

    @staticmethod
    def fingerprint(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def require_token(token: str | None) -> bool:
    if token is None:
        return False
    return TokenVerifier().verify(token)
