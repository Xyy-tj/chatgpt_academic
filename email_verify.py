import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
import sqlite3
from datetime import datetime, timedelta
import re
from config import (
    SMTP_SERVER,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    SMTP_FROM_EMAIL,
)

class EmailVerification:
    def __init__(self, db_path="users.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 创建验证码表
        c.execute('''
            CREATE TABLE IF NOT EXISTS verification_codes (
                email TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                created_time TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                last_attempt_time TEXT
            )
        ''')
        
        conn.commit()
        conn.close()

    def generate_code(self):
        """生成6位数字验证码"""
        return ''.join(random.choices('0123456789', k=6))

    def send_code(self, email):
        """
        发送验证码
        返回: (bool, str) - (是否成功, 错误信息)
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        try:
            # 检查是否存在未过期的验证码
            c.execute("SELECT created_time, attempts, last_attempt_time FROM verification_codes WHERE email = ?", 
                     (email,))
            result = c.fetchone()
            
            current_time = datetime.now()
            
            if result:
                created_time = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
                attempts = result[1]
                last_attempt = datetime.strptime(result[2], '%Y-%m-%d %H:%M:%S') if result[2] else None
                
                # 检查是否在60秒内重复发送
                if last_attempt and (current_time - last_attempt).total_seconds() < 60:
                    return False, "请等待60秒后再次获取验证码"
                
                # 检查24小时内的尝试次数
                if attempts >= 5:
                    if (current_time - created_time).total_seconds() < 24 * 3600:
                        return False, "24小时内验证码获取次数已达上限"
                    else:
                        # 重置计数
                        attempts = 0
            
            # 生成新验证码
            code = self.generate_code()
            
            # 创建邮件内容
            msg = MIMEMultipart()
            msg['From'] = SMTP_FROM_EMAIL
            msg['To'] = email
            msg['Subject'] = "GPT Academic 验证码"
            
            body = f"""
            <html>
            <body>
                <p>您好，</p>
                <p>您的验证码是：<strong style="font-size: 18px; color: #1a73e8;">{code}</strong></p>
                <p>此验证码15分钟内有效，请勿泄露给他人。</p>
                <p>如果这不是您的操作，请忽略此邮件。</p>
                <br>
                <p>GPT Academic 团队</p>
            </body>
            </html>
            """
            msg.attach(MIMEText(body, 'html'))
            
            # 连接SMTP服务器并发送
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()  # 启用TLS
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
            
            # 保存或更新验证码
            c.execute('''
                INSERT OR REPLACE INTO verification_codes 
                (email, code, created_time, attempts, last_attempt_time)
                VALUES (?, ?, ?, ?, ?)
            ''', (email, code, current_time.strftime('%Y-%m-%d %H:%M:%S'), 
                  attempts + 1 if result else 1, 
                  current_time.strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            return True, "验证码已发送到您的邮箱"
                
        except Exception as e:
            return False, f"发送失败: {str(e)}"
        finally:
            conn.close()

    def verify_code(self, email, code):
        """
        验证验证码
        返回: (bool, str) - (是否验证成功, 错误信息)
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        try:
            c.execute("SELECT code, created_time FROM verification_codes WHERE email = ?", 
                     (email,))
            result = c.fetchone()
            
            if not result:
                return False, "验证码不存在"
            
            stored_code, created_time = result
            created_time = datetime.strptime(created_time, '%Y-%m-%d %H:%M:%S')
            
            # 验证码15分钟内有效
            if (datetime.now() - created_time).total_seconds() > 15 * 60:
                return False, "验证码已过期"
            
            if code != stored_code:
                return False, "验证码错误"
            
            # 验证成功后删除验证码
            c.execute("DELETE FROM verification_codes WHERE email = ?", (email,))
            conn.commit()
            
            return True, "验证成功"
            
        except Exception as e:
            return False, f"验证失败: {str(e)}"
        finally:
            conn.close()

    def is_valid_email(self, email):
        """验证邮箱格式"""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
