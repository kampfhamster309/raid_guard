import hashlib
import logging
import xml.etree.ElementTree as ET

import requests

logger = logging.getLogger(__name__)

UNAUTHENTICATED_SID = "0000000000000000"


def _parse_session_info(xml_text: str) -> tuple[str, str]:
    """Return (sid, challenge) from a Fritzbox SessionInfo XML response."""
    root = ET.fromstring(xml_text)
    sid = root.findtext("SID", default=UNAUTHENTICATED_SID)
    challenge = root.findtext("Challenge", default="")
    return sid, challenge


def compute_response(challenge: str, password: str) -> str:
    """
    Compute the Fritzbox challenge-response string.

    The Fritzbox protocol requires MD5 of the UTF-16LE-encoded concatenation
    of challenge + "-" + password.  The result is returned as:
        "<challenge>-<md5hex>"
    """
    hash_input = f"{challenge}-{password}".encode("utf-16-le")
    md5_hex = hashlib.md5(hash_input).hexdigest()  # noqa: S324 — mandated by Fritzbox protocol
    return f"{challenge}-{md5_hex}"


def get_sid(
    fritz_host: str,
    username: str,
    password: str,
    timeout: int = 10,
) -> str:
    """
    Authenticate with the Fritzbox and return a valid session ID (SID).

    Raises:
        ValueError: if credentials are rejected.
        requests.RequestException: on network errors.
    """
    base_url = f"http://{fritz_host}"

    # Step 1 — fetch challenge (or reuse existing session)
    resp = requests.get(f"{base_url}/login_sid.lua", timeout=timeout)
    resp.raise_for_status()
    sid, challenge = _parse_session_info(resp.text)

    if sid != UNAUTHENTICATED_SID:
        logger.info("Fritzbox: reusing existing session %s", sid)
        return sid

    # Step 2 — respond to challenge
    response_str = compute_response(challenge, password)
    resp = requests.post(
        f"{base_url}/login_sid.lua",
        data={"username": username, "response": response_str},
        timeout=timeout,
    )
    resp.raise_for_status()
    sid, _ = _parse_session_info(resp.text)

    if sid == UNAUTHENTICATED_SID:
        raise ValueError(
            "Fritzbox authentication failed — check FRITZ_USER and FRITZ_PASSWORD"
        )

    logger.info("Fritzbox: authenticated, SID=%s", sid)
    return sid
