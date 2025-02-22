from datetime import datetime
import sqlite3
import bcrypt
import os
import hashlib
from loguru import logger

# Configure logging
logger.add('user_manager.log', format='{time:YYYY-MM-DD at HH:mm:ss!UTC} | {level} | {message}', rotation='1 week', compression='zip')
logger.add(lambda msg: print(msg, end=''), colorize=True, format='{time:YYYY-MM-DD at HH:mm:ss!UTC} | {level} | {message}')

class UserManager:
    def __init__(self, db_path="users.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Create users table with email
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                quota_limit INTEGER DEFAULT 0,
                quota_used INTEGER DEFAULT 0,
                last_reset_date TEXT,
                is_admin BOOLEAN DEFAULT 0
            )
        ''')
        
        # Create API usage log table
        c.execute('''
            CREATE TABLE IF NOT EXISTS api_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                timestamp TEXT,
                model TEXT,
                tokens_used INTEGER,
                FOREIGN KEY (username) REFERENCES users (username)
            )
        ''')
        
        conn.commit()
        conn.close()

    def hash_password(self, password):
        """Hash password using bcrypt"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode(), salt)

    def verify_password(self, password, hashed):
        """Verify password against hash, supporting both bcrypt and old sha256 format"""
        try:
            # Try bcrypt first
            return bcrypt.checkpw(password.encode(), hashed if isinstance(hashed, bytes) else hashed.encode())
        except Exception:
            # Fall back to old sha256 method if bcrypt fails
            old_hash = hashlib.sha256(password.encode()).hexdigest()
            return old_hash == hashed

    def verify_user(self, username, password):
        """Verify user credentials and optionally upgrade password hash"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
        result = c.fetchone()
        
        if not result:
            conn.close()
            return False
        
        stored_hash = result[0]
        if self.verify_password(password, stored_hash):
            # If using old hash format, upgrade to bcrypt
            if len(stored_hash) == 64:  # Length of sha256 hash
                try:
                    new_hash = self.hash_password(password)
                    c.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                            (new_hash, username))
                    conn.commit()
                    logger.info(f"Upgraded password hash for user {username}")
                except Exception as e:
                    logger.error(f"Failed to upgrade password hash for user {username}: {e}")
            conn.close()
            return True
        
        conn.close()
        return False

    def add_user(self, username, password, email, quota_limit=1000, is_admin=False):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute(
                "INSERT INTO users (username, password_hash, email, quota_limit, quota_used, last_reset_date, is_admin) VALUES (?, ?, ?, ?, 0, ?, ?)",
                (username, self.hash_password(password), email, quota_limit, datetime.now().strftime('%Y-%m-%d'), is_admin)
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def check_quota(self, username):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT quota_limit, quota_used FROM users WHERE username = ?", (username,))
        result = c.fetchone()
        conn.close()
        
        if not result:
            return False
        
        quota_limit, quota_used = result
        return quota_used < quota_limit

    def deduct_conversation(self, username, count=1):
        """每次对话扣减次数
        Args:
            username: 用户名
            count: 扣减的次数，默认为1次
        Returns:
            bool: 是否扣减成功
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            # 先检查剩余额度
            c.execute("SELECT quota_limit, quota_used FROM users WHERE username = ?", (username,))
            result = c.fetchone()
            if not result:
                logger.warning(f"用户 {username} 不存在，无法扣减对话次数")
                return False
            
            quota_limit, quota_used = result
            if quota_used + count > quota_limit:
                logger.warning(f"用户 {username} 额度不足 (已用: {quota_used}, 上限: {quota_limit}, 请求: {count})")
                return False
            
            # 扣减次数
            c.execute(
                "UPDATE users SET quota_used = quota_used + ? WHERE username = ?",
                (count, username)
            )
            conn.commit()
            logger.info(f"用户 {username} 成功扣减 {count} 次对话额度 (当前使用: {quota_used + count}/{quota_limit})")
            return True
        except Exception as e:
            logger.error(f"扣减用户 {username} 对话次数时发生错误: {str(e)}")
            return False
        finally:
            conn.close()

    def update_quota(self, username, tokens_used, model):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            # Update user's quota
            c.execute("UPDATE users SET quota_used = quota_used + ? WHERE username = ?", 
                     (tokens_used, username))
            
            # Log API usage
            c.execute(
                "INSERT INTO api_usage (username, timestamp, model, tokens_used) VALUES (?, ?, ?, ?)",
                (username, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), model, tokens_used)
            )
            
            conn.commit()
            logger.info(f"用户 {username} 使用 {model} 模型消耗了 {tokens_used} tokens")
        except Exception as e:
            logger.error(f"更新用户 {username} 额度时发生错误: {str(e)}")
        finally:
            conn.close()

    def reset_quota(self, username):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute(
                "UPDATE users SET quota_used = 0, last_reset_date = ? WHERE username = ?",
                (datetime.now().strftime('%Y-%m-%d'), username)
            )
            conn.commit()
        finally:
            conn.close()

    def get_user_info(self, username):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT quota_limit, quota_used, last_reset_date, is_admin FROM users WHERE username = ?", (username,))
        result = c.fetchone()
        conn.close()
        
        if result:
            return {
                'quota_limit': result[0],
                'quota_used': result[1],
                'last_reset_date': result[2],
                'is_admin': bool(result[3])
            }
        return None

    def is_admin(self, username):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT is_admin FROM users WHERE username = ?", (username,))
        result = c.fetchone()
        conn.close()
        
        return bool(result[0]) if result else False

    def get_user_by_email(self, email):
        """根据邮箱获取用户信息"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT username FROM users WHERE email = ?", (email,))
        result = c.fetchone()
        conn.close()

        if result:
            return result[0]
        return None
