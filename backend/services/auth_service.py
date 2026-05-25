"""
services/auth_service.py
------------------------
Authentication service: registration, OTP verification, login, JWT management.

OTP delivery:
  - If SMTP_HOST + SMTP_USER are set in .env → sends real email.
  - Otherwise → prints OTP to console (DEV MODE, zero config needed).

JWT:
  - HS256 signed, configurable expiry (default 24 h).
  - Decoded via FastAPI dependency `get_current_user`.
  - Expired token → 401 with clear "please log in again" message.
"""

import logging
import random
import smtplib
import string
from contextlib import contextmanager
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt
import bcrypt

from config import settings
from database import get_connection
from models.schemas import new_uuid

logger = logging.getLogger(__name__)

# ── Crypto primitives ─────────────────────────────────────────────────────────


security = HTTPBearer()

ALGORITHM = "HS256"
OTP_EXPIRE_MINUTES = 10


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, email: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": user_id, "email": email, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── OTP helpers ───────────────────────────────────────────────────────────────

def _generate_otp(length: int = 6) -> str:
    return "".join(random.choices(string.digits, k=length))


def _send_otp_email(email: str, otp: str) -> None:
    """Send OTP via SMTP TLS. Falls back to console print if SMTP not configured."""
    if not settings.smtp_host or not settings.smtp_user:
        # ── DEV MODE ──────────────────────────────────────────────────────
        banner = "=" * 55
        print(f"\n{banner}")
        print(f"  DEV MODE — OTP EMAIL (not sent, SMTP not configured)")
        print(f"  To      : {email}")
        print(f"  OTP Code: {otp}  (valid {OTP_EXPIRE_MINUTES} min)")
        print(f"{banner}\n")
        logger.warning("DEV MODE: OTP for %s is %s", email, otp)
        return

    sender = settings.smtp_from or settings.smtp_user

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Medical RAG Verification Code"
    msg["From"] = sender
    msg["To"] = email

    html_body = f"""
    <html>
    <body style="font-family:Arial,sans-serif;max-width:480px;margin:auto;padding:24px;">
      <h2 style="color:#1e40af;">Email Verification</h2>
      <p>Use the code below to verify your Medical RAG account:</p>
      <div style="background:#f0f4ff;border-radius:8px;padding:24px;text-align:center;margin:24px 0;">
        <span style="font-size:36px;font-weight:bold;letter-spacing:12px;color:#1d4ed8;">{otp}</span>
      </div>
      <p style="color:#6b7280;font-size:14px;">
        This code expires in <strong>{OTP_EXPIRE_MINUTES} minutes</strong>.<br>
        If you did not request this, you can safely ignore this email.
      </p>
    </body>
    </html>
    """
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(settings.smtp_user, settings.smtp_password or "")
            srv.sendmail(sender, [email], msg.as_string())
        logger.info("OTP email dispatched to %s", email)
    except Exception as exc:
        logger.error("SMTP failure for %s: %s", email, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not send verification email. Check SMTP configuration.",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AuthService
# ═══════════════════════════════════════════════════════════════════════════════

class AuthService:
    """Stateless auth logic — all state lives in SQLite."""

    # ── Registration ──────────────────────────────────────────────────────

    def register(self, email: str, password: str) -> dict:
        email = email.lower().strip()

        with get_connection() as conn:
            existing = conn.execute(
                "SELECT id, is_verified FROM users WHERE email = ?", (email,)
            ).fetchone()

        if existing:
            if existing["is_verified"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An account with this email already exists.",
                )
            # Account exists but not verified — resend OTP
            self._create_and_send_otp(email)
            return {
                "message": (
                    "Account already exists but is unverified. "
                    "A new verification code has been sent to your email."
                )
            }

        # Create new unverified user
        user_id = new_uuid()
        now = datetime.now().isoformat()
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO users (id, email, password_hash, is_verified, created_at)
                   VALUES (?, ?, ?, 0, ?)""",
                (user_id, email, hash_password(password), now),
            )
            conn.commit()

        self._create_and_send_otp(email)
        logger.info("New user registered (unverified): %s", email)
        return {
            "message": (
                "Registration successful! "
                "Please check your email for the 6-digit verification code."
            )
        }

    # ── OTP management ────────────────────────────────────────────────────

    def _create_and_send_otp(self, email: str) -> None:
        otp = _generate_otp()
        now = datetime.now()
        expires_at = (now + timedelta(minutes=OTP_EXPIRE_MINUTES)).isoformat()

        with get_connection() as conn:
            # Invalidate any previous active OTPs for this email
            conn.execute(
                "UPDATE otp_codes SET used = 1 WHERE email = ? AND used = 0",
                (email,),
            )
            conn.execute(
                """INSERT INTO otp_codes (id, email, otp_code, created_at, expires_at, used)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (new_uuid(), email, otp, now.isoformat(), expires_at),
            )
            conn.commit()

        _send_otp_email(email, otp)

    def verify_otp(self, email: str, otp: str) -> dict:
        email = email.lower().strip()
        now = datetime.now().isoformat()

        with get_connection() as conn:
            record = conn.execute(
                """SELECT id FROM otp_codes
                   WHERE email = ? AND otp_code = ? AND used = 0 AND expires_at > ?
                   ORDER BY created_at DESC LIMIT 1""",
                (email, otp, now),
            ).fetchone()

            if record is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired OTP. Please request a new code.",
                )

            conn.execute(
                "UPDATE otp_codes SET used = 1 WHERE id = ?", (record["id"],)
            )
            conn.execute(
                "UPDATE users SET is_verified = 1 WHERE email = ?", (email,)
            )
            conn.commit()

        logger.info("Email verified: %s", email)
        return {"message": "Email verified successfully. You can now log in."}

    def resend_otp(self, email: str) -> dict:
        email = email.lower().strip()

        with get_connection() as conn:
            user = conn.execute(
                "SELECT id, is_verified FROM users WHERE email = ?", (email,)
            ).fetchone()

        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account found with this email address.",
            )
        if user["is_verified"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This account is already verified. Please log in.",
            )

        self._create_and_send_otp(email)
        return {"message": "A new verification code has been sent to your email."}

    # ── Login ─────────────────────────────────────────────────────────────

    def login(self, email: str, password: str) -> dict:
        email = email.lower().strip()

        with get_connection() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()

        # Use a single error for both "not found" and "wrong password" to
        # prevent email enumeration attacks.
        if user is None or not verify_password(password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        if not user["is_verified"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Email not verified. "
                    "Please verify your account before logging in."
                ),
            )

        token = create_access_token(user_id=user["id"], email=user["email"])
        logger.info("User logged in: %s", email)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user["id"],
            "email": user["email"],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI JWT dependency
# ═══════════════════════════════════════════════════════════════════════════════

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Dependency injected into every protected route.

    Validates the Bearer JWT and returns {"user_id": str, "email": str}.
    Raises HTTP 401 if the token is missing, invalid, or expired.
    """
    payload = _decode_token(credentials.credentials)
    user_id: Optional[str] = payload.get("sub")
    email: Optional[str] = payload.get("email")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token payload.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Confirm the user still exists and is verified in the DB
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE id = ? AND is_verified = 1", (user_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account not verified.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"user_id": user_id, "email": email}