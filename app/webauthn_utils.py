"""Face ID = WebAuthn (platform authenticator).

Nega WebAuthn?
  * Qurilmaning haqiqiy Face ID / Touch ID / barmoq izidan foydalanadi.
  * Yaratilgan maxfiy kalit qurilmadan CHIQMAYDI (non-extractable).
  * Har kirishda biometrik tasdiq (userVerification=required) talab qilinadi.
  => Do'stга telefon/akkauntni berib davomat belgilatib bo'lmaydi: boshqa
     qurilmada bu kalit yo'q, va biometrika egasiniki bo'lishi shart.

Agar Telegram ichki brauzeri WebAuthn ni qo'llab-quvvatlamasa — tizim
qurilmaga bog'langan zaxira kalit + 4-xonali kod ga tushadi (README ga qarang).
"""
from __future__ import annotations

import base64

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import settings


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


# --------------------------------------------------------------------------- #
#  Ro'yxatdan o'tish (birinchi marta Face ID yaratish)
# --------------------------------------------------------------------------- #
def registration_options(user_id: int, user_name: str) -> str:
    opts = generate_registration_options(
        rp_id=settings.rp_id,
        rp_name=settings.rp_name,
        user_id=str(user_id).encode(),
        user_name=user_name or f"user{user_id}",
        user_display_name=user_name or f"user{user_id}",
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Faqat shu qurilmaning ichki biometrikasi (tashqi kalit emas)
            authenticator_attachment="platform",
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,  # Face ID MAJBURIY
        ),
    )
    # challenge ni sessiyada saqlash uchun qaytaramiz
    return options_to_json(opts)


def verify_registration(credential_json: str, expected_challenge: bytes):
    """Natija: VerifiedRegistration (credential_id, public_key, sign_count)."""
    return verify_registration_response(
        credential=credential_json,
        expected_challenge=expected_challenge,
        expected_rp_id=settings.rp_id,
        expected_origin=settings.origin,
        require_user_verification=True,
    )


# --------------------------------------------------------------------------- #
#  Autentifikatsiya (har davomatda Face ID so'rash)
# --------------------------------------------------------------------------- #
def authentication_options(allowed_credential_ids: list[bytes]) -> str:
    opts = generate_authentication_options(
        rp_id=settings.rp_id,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=cid) for cid in allowed_credential_ids
        ],
        user_verification=UserVerificationRequirement.REQUIRED,  # Face ID MAJBURIY
    )
    return options_to_json(opts)


def verify_authentication(
    credential_json: str,
    expected_challenge: bytes,
    public_key: bytes,
    sign_count: int,
):
    """Natija: VerifiedAuthentication (new_sign_count, ...)."""
    return verify_authentication_response(
        credential=credential_json,
        expected_challenge=expected_challenge,
        expected_rp_id=settings.rp_id,
        expected_origin=settings.origin,
        credential_public_key=public_key,
        credential_current_sign_count=sign_count,
        require_user_verification=True,
    )


def credential_id_from_response(credential_json: str) -> bytes:
    import json

    obj = json.loads(credential_json)
    return base64url_to_bytes(obj["id"])
