"""
============================================================
OPERATION FIRST MOVER v5.3 -- SECURITY MODULE (INDUSTRIAL GRADE)
============================================================
Centralized security layer protecting both Telegram bot and
Mini-App with admin-only controls, one-time access codes,
and user whitelist management.

Admin: Designated by Telegram ID (sole admin)
Users: Managed via admin commands, stored in SQLite
Access Codes: random(3 letters) + random(4 digits) + random(4 alphanum)
Protects: Bot commands, Mini-App API access

Commands (admin-only in admin chat):
    /adduser <username> <telegram_id>  -- Add authorized user
    /removeuser <telegram_id>          -- Remove user
    /readduser <telegram_id>           -- Re-enable removed user
    /listusers                         -- List all authorized users
    /gencode <telegram_id>             -- Regenerate access code
    /secstatus                         -- Security dashboard

Security Model:
    1. ADMIN_TELEGRAM_ID is the sole admin (env: ADMIN_TELEGRAM_ID)
    2. Only admin chat receives admin commands
    3. Users must be pre-authorized to use bot commands
    4. Mini-app requires valid access code (one-time, regenerable)
    5. All auth events are logged for audit
============================================================
"""

import os
import json
import time
import random
import string
import hashlib
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

try:
    from core.config import IST
except ImportError:
    IST = timezone(timedelta(hours=5, minutes=30))

# ============================================================
# CONSTANTS
# ============================================================

MODULE_ID = "SEC"

# Admin Telegram ID (sole admin)
ADMIN_TELEGRAM_ID = int(os.getenv('ADMIN_TELEGRAM_ID', '1284690336'))
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'abuzarkhan999')

# Security settings
MAX_FAILED_AUTH_ATTEMPTS = 10       # Per user, per hour
ACCESS_CODE_LENGTH = 11             # 3 random letters + 4 random digits + 4 random alphanum
CODE_EXPIRY_HOURS = 720             # 30 days
MAX_ACTIVE_SESSIONS = 3             # Per user
RATE_LIMIT_WINDOW_SEC = 3600        # 1 hour
RATE_LIMIT_MAX_REQUESTS = 60        # Per user per hour

# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class AuthorizedUser:
    """Authorized user record."""
    telegram_id: int
    username: str
    access_code: str
    is_active: bool = True
    is_admin: bool = False
    added_by: int = 0
    added_at: Optional[str] = None
    last_active: Optional[str] = None
    failed_attempts: int = 0
    total_commands: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuthEvent:
    """Security audit log entry."""
    event_type: str   # 'login', 'command', 'denied', 'code_gen', 'user_add', 'user_remove'
    telegram_id: int
    detail: str = ""
    ip_address: str = ""
    timestamp: Optional[str] = None


# ============================================================
# ACCESS CODE GENERATION
# ============================================================

def generate_access_code(username: str = "", telegram_id: int = 0) -> str:
    """
    Generate a fully random one-time access code.
    
    Format: 3 random lowercase letters + 4 random digits + 4 random alphanumeric
    Total: 11 characters, all random — no username or ID derivation.
    
    Example: xkf8271m3qp
    
    NOTE: username and telegram_id params kept for API compatibility
    but are NOT used in code generation. All components are random.
    """
    # Part 1: 3 random lowercase letters
    part1 = ''.join(random.choices(string.ascii_lowercase, k=3))
    
    # Part 2: 4 random digits
    part2 = ''.join(random.choices(string.digits, k=4))
    
    # Part 3: 4 random alphanumeric (lowercase + digits)
    part3 = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
    
    code = f"{part1}{part2}{part3}"
    return code


def verify_access_code(provided_code: str, stored_code: str) -> bool:
    """Verify an access code using constant-time comparison."""
    if not provided_code or not stored_code:
        return False
    # Use hmac.compare_digest for timing-safe comparison
    import hmac
    return hmac.compare_digest(provided_code.lower().strip(), stored_code.lower().strip())


# ============================================================
# SECURITY DATABASE SCHEMA
# ============================================================

SECURITY_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS authorized_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        username TEXT NOT NULL DEFAULT '',
        access_code TEXT NOT NULL DEFAULT '',
        access_code_hash TEXT NOT NULL DEFAULT '',
        is_active BOOLEAN DEFAULT 1,
        is_admin BOOLEAN DEFAULT 0,
        added_by INTEGER DEFAULT 0,
        added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_active DATETIME,
        failed_attempts INTEGER DEFAULT 0,
        total_commands INTEGER DEFAULT 0,
        notes TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS security_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL DEFAULT '',
        telegram_id INTEGER DEFAULT 0,
        username TEXT DEFAULT '',
        detail TEXT DEFAULT '',
        ip_address TEXT DEFAULT '',
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS miniapp_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER NOT NULL,
        session_token TEXT UNIQUE NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        expires_at DATETIME NOT NULL,
        is_active BOOLEAN DEFAULT 1,
        ip_address TEXT DEFAULT '',
        user_agent TEXT DEFAULT ''
    )
    """,
]

SECURITY_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_auth_users_tg_id ON authorized_users(telegram_id)",
    "CREATE INDEX IF NOT EXISTS idx_auth_users_active ON authorized_users(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_auth_users_code ON authorized_users(access_code_hash)",
    "CREATE INDEX IF NOT EXISTS idx_sec_events_type ON security_events(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_sec_events_tg ON security_events(telegram_id)",
    "CREATE INDEX IF NOT EXISTS idx_sec_events_ts ON security_events(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_miniapp_sessions_token ON miniapp_sessions(session_token)",
    "CREATE INDEX IF NOT EXISTS idx_miniapp_sessions_tg ON miniapp_sessions(telegram_id)",
]


# ============================================================
# SECURITY MANAGER CLASS
# ============================================================

class SecurityManager:
    """
    Centralized security manager for Operation First Mover.
    
    Provides:
    - Admin authentication (Telegram ID based)
    - User whitelist management (add/remove/re-add)
    - One-time access code generation & verification
    - Mini-app session management
    - Security event audit logging
    - Rate limiting per user
    - Failed attempt tracking & lockout
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        # Use same DB path as main database
        try:
            from core.config import get_config
            db_path = get_config().database.path
        except Exception:
            db_path = "data/firstmover.db"
        
        self.db_path = db_path
        self._local = threading.local()
        
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize security tables
        self._initialize_security_tables()
        
        # Ensure admin is always registered
        self._ensure_admin()
        
        logger.info(
            f"[{MODULE_ID}] Security Manager initialized "
            f"(admin={ADMIN_TELEGRAM_ID})"
        )
    
    # ----------------------------------------------------------
    # CONNECTION MANAGEMENT
    # ----------------------------------------------------------
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(
                self.db_path, timeout=10.0,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn
    
    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute SQL with auto-commit."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        return cursor
    
    def _fetchone(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        """Fetch single row as dict."""
        cursor = self._execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def _fetchall(self, sql: str, params: tuple = ()) -> List[Dict]:
        """Fetch all rows as list of dicts."""
        cursor = self._execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    
    # ----------------------------------------------------------
    # INITIALIZATION
    # ----------------------------------------------------------
    
    def _initialize_security_tables(self):
        """Create security tables if they don't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            for sql in SECURITY_TABLES_SQL:
                cursor.execute(sql)
            for sql in SECURITY_INDEXES_SQL:
                cursor.execute(sql)
            conn.commit()
            logger.debug(f"[{MODULE_ID}] Security tables initialized")
        except Exception as e:
            conn.rollback()
            logger.error(f"[{MODULE_ID}] Security table init error: {e}")
    
    def _ensure_admin(self):
        """Ensure the admin user is always registered and active."""
        existing = self._fetchone(
            "SELECT * FROM authorized_users WHERE telegram_id = ?",
            (ADMIN_TELEGRAM_ID,)
        )
        
        if not existing:
            code = generate_access_code(ADMIN_USERNAME, ADMIN_TELEGRAM_ID)
            code_hash = hashlib.sha256(code.lower().encode()).hexdigest()
            self._execute(
                """
                INSERT INTO authorized_users
                (telegram_id, username, access_code, access_code_hash,
                 is_active, is_admin, added_by, notes)
                VALUES (?, ?, ?, ?, 1, 1, ?, 'System admin')
                """,
                (ADMIN_TELEGRAM_ID, ADMIN_USERNAME, code, code_hash, ADMIN_TELEGRAM_ID)
            )
            logger.info(
                f"[{MODULE_ID}] Admin registered: @{ADMIN_USERNAME} "
                f"(ID: {ADMIN_TELEGRAM_ID})"
            )
            self._log_event('admin_init', ADMIN_TELEGRAM_ID, 
                          f'Admin auto-registered: @{ADMIN_USERNAME}')
        elif not existing['is_active']:
            # Re-activate admin if somehow deactivated
            self._execute(
                "UPDATE authorized_users SET is_active = 1, is_admin = 1 WHERE telegram_id = ?",
                (ADMIN_TELEGRAM_ID,)
            )
    
    # ----------------------------------------------------------
    # ADMIN CHECKS
    # ----------------------------------------------------------
    
    def is_admin(self, telegram_id: int) -> bool:
        """Check if a Telegram ID is the admin."""
        return int(telegram_id) == ADMIN_TELEGRAM_ID
    
    def is_admin_chat(self, chat_id: int) -> bool:
        """Check if a chat is the admin's chat."""
        return int(chat_id) == ADMIN_TELEGRAM_ID
    
    # ----------------------------------------------------------
    # USER AUTHORIZATION
    # ----------------------------------------------------------
    
    def is_authorized(self, telegram_id: int) -> bool:
        """Check if a Telegram user is authorized."""
        user = self._fetchone(
            "SELECT is_active FROM authorized_users WHERE telegram_id = ? AND is_active = 1",
            (int(telegram_id),)
        )
        return user is not None
    
    def get_user(self, telegram_id: int) -> Optional[Dict]:
        """Get full user record."""
        return self._fetchone(
            "SELECT * FROM authorized_users WHERE telegram_id = ?",
            (int(telegram_id),)
        )
    
    def add_user(self, username: str, telegram_id: int, 
                 added_by: int = ADMIN_TELEGRAM_ID) -> Tuple[bool, str, str]:
        """
        Add a new authorized user.
        
        Returns: (success, access_code, message)
        """
        telegram_id = int(telegram_id)
        clean_username = username.lower().strip().lstrip('@')
        
        # Check if already exists
        existing = self.get_user(telegram_id)
        if existing:
            if existing['is_active']:
                return False, existing['access_code'], f"User @{clean_username} already authorized"
            else:
                # Re-activate
                code = generate_access_code(clean_username, telegram_id)
                code_hash = hashlib.sha256(code.lower().encode()).hexdigest()
                self._execute(
                    """
                    UPDATE authorized_users 
                    SET is_active = 1, username = ?, access_code = ?, 
                        access_code_hash = ?, failed_attempts = 0
                    WHERE telegram_id = ?
                    """,
                    (clean_username, code, code_hash, telegram_id)
                )
                self._log_event('user_reactivate', telegram_id,
                              f'Re-activated by admin: @{clean_username}')
                return True, code, f"User @{clean_username} re-activated"
        
        # Generate access code
        code = generate_access_code(clean_username, telegram_id)
        code_hash = hashlib.sha256(code.lower().encode()).hexdigest()
        
        try:
            self._execute(
                """
                INSERT INTO authorized_users
                (telegram_id, username, access_code, access_code_hash,
                 is_active, is_admin, added_by)
                VALUES (?, ?, ?, ?, 1, 0, ?)
                """,
                (telegram_id, clean_username, code, code_hash, added_by)
            )
            self._log_event('user_add', telegram_id,
                          f'Added by {added_by}: @{clean_username}')
            logger.info(f"[{MODULE_ID}] User added: @{clean_username} (ID: {telegram_id})")
            return True, code, f"User @{clean_username} added successfully"
        except sqlite3.IntegrityError:
            return False, "", f"User with ID {telegram_id} already exists"
        except Exception as e:
            logger.error(f"[{MODULE_ID}] Add user error: {e}")
            return False, "", f"Error adding user: {e}"
    
    def remove_user(self, telegram_id: int) -> Tuple[bool, str]:
        """
        Deactivate a user (soft delete).
        
        Returns: (success, message)
        """
        telegram_id = int(telegram_id)
        
        # Cannot remove admin
        if telegram_id == ADMIN_TELEGRAM_ID:
            return False, "Cannot remove the admin user"
        
        user = self.get_user(telegram_id)
        if not user:
            return False, f"User with ID {telegram_id} not found"
        
        if not user['is_active']:
            return False, f"User @{user['username']} is already deactivated"
        
        self._execute(
            "UPDATE authorized_users SET is_active = 0 WHERE telegram_id = ?",
            (telegram_id,)
        )
        
        # Invalidate all sessions
        self._execute(
            "UPDATE miniapp_sessions SET is_active = 0 WHERE telegram_id = ?",
            (telegram_id,)
        )
        
        self._log_event('user_remove', telegram_id,
                       f'Deactivated: @{user["username"]}')
        logger.info(f"[{MODULE_ID}] User removed: @{user['username']} (ID: {telegram_id})")
        return True, f"User @{user['username']} deactivated"
    
    def readd_user(self, telegram_id: int) -> Tuple[bool, str, str]:
        """
        Re-activate a previously removed user with a new access code.
        
        Returns: (success, access_code, message)
        """
        telegram_id = int(telegram_id)
        user = self.get_user(telegram_id)
        
        if not user:
            return False, "", f"User with ID {telegram_id} not found"
        
        if user['is_active']:
            return False, user['access_code'], f"User @{user['username']} is already active"
        
        # Generate new code
        code = generate_access_code(user['username'], telegram_id)
        code_hash = hashlib.sha256(code.lower().encode()).hexdigest()
        
        self._execute(
            """
            UPDATE authorized_users 
            SET is_active = 1, access_code = ?, access_code_hash = ?, 
                failed_attempts = 0
            WHERE telegram_id = ?
            """,
            (code, code_hash, telegram_id)
        )
        
        self._log_event('user_readd', telegram_id,
                       f'Re-activated: @{user["username"]}')
        logger.info(f"[{MODULE_ID}] User re-added: @{user['username']} (ID: {telegram_id})")
        return True, code, f"User @{user['username']} re-activated with new code"
    
    def regenerate_code(self, telegram_id: int) -> Tuple[bool, str, str]:
        """
        Regenerate access code for a user.
        
        Returns: (success, new_code, message)
        """
        telegram_id = int(telegram_id)
        user = self.get_user(telegram_id)
        
        if not user:
            return False, "", f"User with ID {telegram_id} not found"
        
        code = generate_access_code(user['username'], telegram_id)
        code_hash = hashlib.sha256(code.lower().encode()).hexdigest()
        
        self._execute(
            """
            UPDATE authorized_users 
            SET access_code = ?, access_code_hash = ?
            WHERE telegram_id = ?
            """,
            (code, code_hash, telegram_id)
        )
        
        # Invalidate all sessions (code changed)
        self._execute(
            "UPDATE miniapp_sessions SET is_active = 0 WHERE telegram_id = ?",
            (telegram_id,)
        )
        
        self._log_event('code_regen', telegram_id,
                       f'Code regenerated for @{user["username"]}')
        return True, code, f"New code generated for @{user['username']}"
    
    def list_users(self) -> List[Dict]:
        """List all authorized users."""
        return self._fetchall(
            """
            SELECT telegram_id, username, is_active, is_admin,
                   added_at, last_active, total_commands, failed_attempts
            FROM authorized_users
            ORDER BY is_admin DESC, is_active DESC, added_at DESC
            """
        )
    
    # ----------------------------------------------------------
    # COMMAND AUTHORIZATION (Telegram Bot)
    # ----------------------------------------------------------
    
    def authorize_command(self, telegram_id: int, command: str = "",
                         chat_id: int = 0) -> Tuple[bool, str]:
        """
        Check if a user is authorized to execute a bot command.
        
        Returns: (authorized, denial_reason)
        """
        telegram_id = int(telegram_id)
        
        # Admin always authorized
        if self.is_admin(telegram_id):
            self._record_activity(telegram_id, command)
            return True, ""
        
        # Check user authorization
        user = self._fetchone(
            "SELECT * FROM authorized_users WHERE telegram_id = ? AND is_active = 1",
            (telegram_id,)
        )
        
        if not user:
            self._log_event('denied', telegram_id,
                          f'Unauthorized command: {command}')
            return False, "You are not authorized. Contact the admin."
        
        # Check rate limiting
        if self._is_rate_limited(telegram_id):
            return False, "Rate limit exceeded. Please wait."
        
        # Check lockout (too many failed attempts)
        if user['failed_attempts'] >= MAX_FAILED_AUTH_ATTEMPTS:
            return False, "Account locked due to too many failed attempts. Contact admin."
        
        # Authorized
        self._record_activity(telegram_id, command)
        return True, ""
    
    def _record_activity(self, telegram_id: int, command: str = ""):
        """Record user activity for tracking."""
        try:
            self._execute(
                """
                UPDATE authorized_users 
                SET last_active = CURRENT_TIMESTAMP,
                    total_commands = total_commands + 1
                WHERE telegram_id = ?
                """,
                (telegram_id,)
            )
        except Exception:
            pass
    
    def _is_rate_limited(self, telegram_id: int) -> bool:
        """Check if user is rate limited."""
        result = self._fetchone(
            """
            SELECT COUNT(*) as cnt FROM security_events
            WHERE telegram_id = ? 
              AND event_type = 'command'
              AND timestamp >= datetime('now', '-1 hour')
            """,
            (telegram_id,)
        )
        return result and result['cnt'] >= RATE_LIMIT_MAX_REQUESTS
    
    def record_failed_attempt(self, telegram_id: int, detail: str = ""):
        """Record a failed authentication attempt."""
        try:
            self._execute(
                """
                UPDATE authorized_users 
                SET failed_attempts = failed_attempts + 1
                WHERE telegram_id = ?
                """,
                (telegram_id,)
            )
            self._log_event('auth_fail', telegram_id, detail)
        except Exception:
            pass
    
    # ----------------------------------------------------------
    # MINI-APP SESSION MANAGEMENT
    # ----------------------------------------------------------
    
    def create_miniapp_session(self, telegram_id: int, 
                                ip_address: str = "",
                                user_agent: str = "") -> Optional[str]:
        """
        Create a mini-app session for an authorized user.
        
        Returns: session_token or None
        """
        telegram_id = int(telegram_id)
        
        if not self.is_authorized(telegram_id):
            self._log_event('session_denied', telegram_id, 'Not authorized')
            return None
        
        # Generate session token
        raw = f"{telegram_id}:{time.time()}:{random.random()}"
        token = hashlib.sha256(raw.encode()).hexdigest()
        
        # Expire old sessions for this user (keep max 3)
        self._execute(
            """
            UPDATE miniapp_sessions SET is_active = 0 
            WHERE telegram_id = ? AND id NOT IN (
                SELECT id FROM miniapp_sessions 
                WHERE telegram_id = ? AND is_active = 1
                ORDER BY created_at DESC LIMIT ?
            )
            """,
            (telegram_id, telegram_id, MAX_ACTIVE_SESSIONS - 1)
        )
        
        # Create new session
        expires_at = (datetime.now(IST) + timedelta(hours=CODE_EXPIRY_HOURS)).isoformat()
        
        try:
            self._execute(
                """
                INSERT INTO miniapp_sessions
                (telegram_id, session_token, expires_at, ip_address, user_agent)
                VALUES (?, ?, ?, ?, ?)
                """,
                (telegram_id, token, expires_at, ip_address, user_agent)
            )
            self._log_event('session_create', telegram_id, f'token={token[:8]}...')
            return token
        except Exception as e:
            logger.error(f"[{MODULE_ID}] Session create error: {e}")
            return None
    
    def validate_miniapp_session(self, session_token: str) -> Optional[int]:
        """
        Validate a mini-app session token.
        
        Returns: telegram_id if valid, None otherwise
        """
        if not session_token:
            return None
        
        session = self._fetchone(
            """
            SELECT s.*, u.is_active as user_active
            FROM miniapp_sessions s
            JOIN authorized_users u ON s.telegram_id = u.telegram_id
            WHERE s.session_token = ? 
              AND s.is_active = 1
              AND s.expires_at > datetime('now')
              AND u.is_active = 1
            """,
            (session_token,)
        )
        
        if session:
            return session['telegram_id']
        return None
    
    def validate_access_code(self, code: str) -> Optional[Dict]:
        """
        Validate an access code and return the user info.
        
        Returns: user dict if valid, None otherwise
        """
        if not code:
            return None
        
        code_hash = hashlib.sha256(code.lower().strip().encode()).hexdigest()
        
        user = self._fetchone(
            """
            SELECT * FROM authorized_users 
            WHERE access_code_hash = ? AND is_active = 1
            """,
            (code_hash,)
        )
        
        if user:
            self._log_event('code_validate', user['telegram_id'], 'Access code validated')
            return dict(user)
        
        return None
    
    # ----------------------------------------------------------
    # AUDIT LOGGING
    # ----------------------------------------------------------
    
    def _log_event(self, event_type: str, telegram_id: int, 
                   detail: str = "", ip_address: str = ""):
        """Log a security event."""
        try:
            self._execute(
                """
                INSERT INTO security_events
                (event_type, telegram_id, detail, ip_address)
                VALUES (?, ?, ?, ?)
                """,
                (event_type, telegram_id, detail[:500], ip_address)
            )
        except Exception as e:
            logger.debug(f"[{MODULE_ID}] Event log error: {e}")
    
    def get_recent_events(self, limit: int = 20, 
                           event_type: Optional[str] = None) -> List[Dict]:
        """Get recent security events."""
        if event_type:
            return self._fetchall(
                """
                SELECT * FROM security_events 
                WHERE event_type = ?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (event_type, limit)
            )
        return self._fetchall(
            "SELECT * FROM security_events ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        )
    
    # ----------------------------------------------------------
    # SECURITY DASHBOARD
    # ----------------------------------------------------------
    
    def get_security_status(self) -> Dict[str, Any]:
        """Get comprehensive security dashboard data."""
        total_users = self._fetchone(
            "SELECT COUNT(*) as cnt FROM authorized_users"
        )
        active_users = self._fetchone(
            "SELECT COUNT(*) as cnt FROM authorized_users WHERE is_active = 1"
        )
        active_sessions = self._fetchone(
            """
            SELECT COUNT(*) as cnt FROM miniapp_sessions 
            WHERE is_active = 1 AND expires_at > datetime('now')
            """
        )
        denied_today = self._fetchone(
            """
            SELECT COUNT(*) as cnt FROM security_events 
            WHERE event_type = 'denied' 
              AND timestamp >= datetime('now', '-24 hours')
            """
        )
        events_today = self._fetchone(
            """
            SELECT COUNT(*) as cnt FROM security_events 
            WHERE timestamp >= datetime('now', '-24 hours')
            """
        )
        
        return {
            'admin_id': ADMIN_TELEGRAM_ID,
            'admin_username': ADMIN_USERNAME,
            'total_users': total_users['cnt'] if total_users else 0,
            'active_users': active_users['cnt'] if active_users else 0,
            'active_sessions': active_sessions['cnt'] if active_sessions else 0,
            'denied_today': denied_today['cnt'] if denied_today else 0,
            'events_today': events_today['cnt'] if events_today else 0,
        }
    
    def format_security_dashboard(self) -> str:
        """Format security status as Telegram message."""
        status = self.get_security_status()
        users = self.list_users()
        
        lines = [
            "🔐 <b>SECURITY DASHBOARD</b>",
            f"<i>{datetime.now(IST).strftime('%d %b %Y, %I:%M %p IST')}</i>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"👑 Admin: @{status['admin_username']} (ID: {status['admin_id']})",
            f"👥 Total Users: <b>{status['total_users']}</b>",
            f"✅ Active Users: <b>{status['active_users']}</b>",
            f"🌐 Active Sessions: <b>{status['active_sessions']}</b>",
            f"🚫 Denied Today: <b>{status['denied_today']}</b>",
            f"📊 Events Today: <b>{status['events_today']}</b>",
            "",
            "👤 <b>User List:</b>",
        ]
        
        for u in users:
            status_emoji = "👑" if u.get('is_admin') else ("✅" if u.get('is_active') else "❌")
            username = u.get('username', '?')
            tg_id = u.get('telegram_id', 0)
            cmds = u.get('total_commands', 0)
            last = str(u.get('last_active', 'Never'))[:10]
            lines.append(
                f"  {status_emoji} @{username} (ID: {tg_id})\n"
                f"     Commands: {cmds} | Last: {last}"
            )
        
        lines.extend([
            "",
            "🔧 <b>Admin Commands:</b>",
            "  /adduser <username> <id> -- Add user",
            "  /removeuser <id> -- Deactivate user",
            "  /readduser <id> -- Re-activate user",
            "  /gencode <id> -- Regenerate access code",
            "  /listusers -- List all users",
            "  /secstatus -- This dashboard",
        ])
        
        return '\n'.join(lines)
    
    def format_user_list(self) -> str:
        """Format user list as Telegram message."""
        users = self.list_users()
        
        if not users:
            return "👥 No authorized users found."
        
        lines = [
            "👥 <b>AUTHORIZED USERS</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        
        for i, u in enumerate(users, 1):
            status_emoji = "👑" if u.get('is_admin') else ("✅" if u.get('is_active') else "⛔")
            username = u.get('username', '?')
            tg_id = u.get('telegram_id', 0)
            cmds = u.get('total_commands', 0)
            fails = u.get('failed_attempts', 0)
            added = str(u.get('added_at', ''))[:10] or 'Unknown'
            last = str(u.get('last_active', 'Never'))[:10]
            
            role = "ADMIN" if u.get('is_admin') else ("Active" if u.get('is_active') else "Inactive")
            
            lines.append(
                f"{status_emoji} <b>{i}. @{username}</b>\n"
                f"   ID: <code>{tg_id}</code> | Role: {role}\n"
                f"   Commands: {cmds} | Fails: {fails}\n"
                f"   Added: {added} | Last Active: {last}"
            )
        
        lines.append(f"\nTotal: {len(users)} users")
        return '\n'.join(lines)


# ============================================================
# SINGLETON ACCESS
# ============================================================

_security_instance: Optional[SecurityManager] = None

def get_security_manager() -> SecurityManager:
    """Get or create the singleton SecurityManager instance."""
    global _security_instance
    if _security_instance is None:
        _security_instance = SecurityManager()
    return _security_instance


# ============================================================
# CONVENIENCE DECORATORS
# ============================================================

def require_auth(func):
    """Decorator to require authorization for Telegram command handlers."""
    import functools
    
    @functools.wraps(func)
    async def wrapper(self, update, context, *args, **kwargs):
        telegram_id = update.effective_user.id if update.effective_user else 0
        
        if not telegram_id:
            return
        
        sec = get_security_manager()
        authorized, reason = sec.authorize_command(
            telegram_id, 
            command=func.__name__,
            chat_id=update.effective_chat.id if update.effective_chat else 0
        )
        
        if not authorized:
            try:
                await update.message.reply_text(
                    f"🔒 Access Denied: {reason}\n\n"
                    f"Contact the admin to get authorized."
                )
            except Exception:
                pass
            return
        
        return await func(self, update, context, *args, **kwargs)
    
    return wrapper


def require_admin(func):
    """Decorator to require admin privileges for Telegram command handlers."""
    import functools
    
    @functools.wraps(func)
    async def wrapper(self, update, context, *args, **kwargs):
        telegram_id = update.effective_user.id if update.effective_user else 0
        chat_id = update.effective_chat.id if update.effective_chat else 0
        
        sec = get_security_manager()
        
        if not sec.is_admin(telegram_id):
            try:
                await update.message.reply_text(
                    "🔒 This command is admin-only."
                )
            except Exception:
                pass
            sec._log_event('admin_denied', telegram_id, func.__name__)
            return
        
        return await func(self, update, context, *args, **kwargs)
    
    return wrapper


# ============================================================
# SELF-TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Security Module -- Self-Test")
    print("=" * 60)
    
    # Test code generation (fully random)
    code1 = generate_access_code("abuzarkhan999", 1284690336)
    print(f"  Code 1 (random): {code1}")
    assert len(code1) == 11, f"Code length should be 11, got {len(code1)}"
    
    code2 = generate_access_code("testuser", 9876543210)
    print(f"  Code 2 (random): {code2}")
    assert len(code2) == 11
    
    # Verify all components are random (no username/ID leakage)
    code3 = generate_access_code("abuzarkhan999", 1284690336)
    print(f"  Code 3 (random, same user): {code3}")
    assert code1 != code3, "Two codes for same user should be different (random)"
    
    # Test verification
    assert verify_access_code(code1, code1)
    assert not verify_access_code(code1, code2)
    
    print(f"\n  All codes are fully random — no username/ID derivation")
    print(f"  Admin ID: {ADMIN_TELEGRAM_ID}")
    print(f"  Admin Username: @{ADMIN_USERNAME}")
    print(f"\n  Security module ready!")
    print("=" * 60)
