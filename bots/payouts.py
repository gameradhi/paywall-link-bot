# bots/payouts.py
import os
import logging
from typing import Tuple, Optional

import requests

logger = logging.getLogger(__name__)

# ====== CONFIG ======
# For TEST (Gamma) environment:
CF_PAYOUT_BASE_URL = os.getenv("CF_PAYOUT_BASE_URL", "https://payout-gamma.cashfree.com/payout/v1")
CF_PAYOUT_CLIENT_ID = os.getenv("CF_PAYOUT_CLIENT_ID", "YOUR_TEST_PAYOUT_CLIENT_ID")
CF_PAYOUT_CLIENT_SECRET = os.getenv("CF_PAYOUT_CLIENT_SECRET", "YOUR_TEST_PAYOUT_SECRET")

# When you go LIVE:
# CF_PAYOUT_BASE_URL = "https://payout-api.cashfree.com/payout/v1"
# and set LIVE client id/secret in Railway env vars.


# ====== INTERNAL: AUTH TOKEN ======

def _get_auth_token() -> Optional[str]:
    """
    Get auth token from Cashfree Payouts. Uses client_id + client_secret.
    """
    url = f"{CF_PAYOUT_BASE_URL}/authorize"
    headers = {
        "Content-Type": "application/json",
        "x-client-id": CF_PAYOUT_CLIENT_ID,
        "x-client-secret": CF_PAYOUT_CLIENT_SECRET,
    }

    try:
        resp = requests.post(url, json={}, headers=headers, timeout=15)
        logger.info("Cashfree Payout authorize resp [%s]: %s", resp.status_code, resp.text)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("data", {}).get("token") or data.get("token")
    except Exception as e:  # noqa: BLE001
        logger.error("Error getting Cashfree Payout auth token: %s", e)
        return None


# ====== PUBLIC: SEND PAYOUT ======

def send_payout(
    *,
    amount: float,
    method: str,
    account: str,
    name: str,
    withdrawal_id: int,
) -> Tuple[bool, str, str]:
    """
    Send a payout via Cashfree Payouts.

    method: "upi" or "bank"
    account:
        - if method == "upi": UPI ID, e.g. "user@upi"
        - if method == "bank": "IFSC|ACCOUNTNO" (e.g. "HDFC0001234|1234567890")

    Returns: (success, external_ref, message)
    """
    token = _get_auth_token()
    if not token:
        return False, "", "Failed to authorize with payout API."

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    if method == "upi":
        transfer_mode = "upi"
        upi = account
        bank_data = {
            "transferMode": transfer_mode,
            "beneficiary": {
                "name": name or "Tele Link User",
                "upi": upi,
            },
        }
    else:
        transfer_mode = "banktransfer"
        try:
            ifsc, acc_no = account.split("|", 1)
        except ValueError:
            return False, "", "Invalid bank account format. Expected 'IFSC|ACCOUNT'."
        bank_data = {
            "transferMode": transfer_mode,
            "beneficiary": {
                "name": name or "Tele Link User",
                "bankAccount": acc_no,
                "ifsc": ifsc,
            },
        }

    payload = {
        "amount": float(amount),
        "transferId": f"TLW_{withdrawal_id}",
        **bank_data,
    }

    url = f"{CF_PAYOUT_BASE_URL}/requestTransfer"

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        logger.info("Cashfree Payout transfer resp [%s]: %s", resp.status_code, resp.text)

        if resp.status_code not in (200, 202):
            return False, "", f"Payout API error: {resp.status_code} {resp.text}"

        data = resp.json()
        status = (
            data.get("status")
            or data.get("subCode")
            or ""
        )

        reference_id = (
            data.get("data", {}).get("referenceId")
            or data.get("referenceId", "")
        )

        if status.lower() in ("success", "accepted", "queued"):
            msg = "Payout initiated successfully."
            return True, reference_id, msg

        return False, reference_id, f"Payout not successful yet. Status: {status}"

    except Exception as e:  # noqa: BLE001
        logger.error("Error sending payout: %s", e)
        return False, "", f"Error sending payout: {e}"
