import secrets
import string

_FB_ALPHABET = string.ascii_uppercase + string.digits


def new_feedback_id() -> str:
    """Generate a public feedback ID like FB-A3F2K9."""
    suffix = "".join(secrets.choice(_FB_ALPHABET) for _ in range(6))
    return f"FB-{suffix}"


def new_api_key(env: str = "live") -> tuple[str, str]:
    """Return (full_key, prefix). The prefix is safe to store/display; the full key is shown once.

    Format: fbk_<env>_<32-byte urlsafe secret>.
    Prefix stored = fbk_<env>_<first 8 chars of secret> (used for fast lookup).
    """
    secret = secrets.token_urlsafe(32)
    full = f"fbk_{env}_{secret}"
    prefix = f"fbk_{env}_{secret[:8]}"
    return full, prefix
