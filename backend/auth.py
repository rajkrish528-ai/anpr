"""Authentication and session management for the admin panel."""
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from .database import get_connection

# We'll use a simple token bearer scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

SALT = "smart-parking-salt"

def hash_password(password: str) -> str:
    """Generate SHA-256 hash for the given password."""
    return hashlib.sha256((SALT + password).encode("utf-8")).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check if the plain password matches the hashed password."""
    return hash_password(plain_password) == hashed_password

def create_session_token(admin_id: int) -> str:
    """Create a new session token and store it in the database."""
    token = secrets.token_hex(32)
    expires_at = (datetime.utcnow() + timedelta(days=7)).isoformat()
    
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO admin_sessions (token, admin_id, expires_at) VALUES (?, ?, ?)",
            (token, admin_id, expires_at)
        )
    return token

def get_current_admin(token: Annotated[str, Depends(oauth2_scheme)]):
    """Dependency to retrieve the current logged-in admin from the token."""
    with get_connection() as conn:
        session = conn.execute(
            "SELECT admin_id, expires_at FROM admin_sessions WHERE token = ?",
            (token,)
        ).fetchone()
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        expires_at = datetime.fromisoformat(session["expires_at"])
        if datetime.utcnow() > expires_at:
            # Clean up expired token
            conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        admin = conn.execute(
            "SELECT id, email FROM admins WHERE id = ?",
            (session["admin_id"],)
        ).fetchone()
        
        if not admin:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Admin user not found",
            )
            
        return {"id": admin["id"], "email": admin["email"]}
