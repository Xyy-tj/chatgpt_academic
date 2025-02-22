from alibabacloud_dysmsapi20170525.models import SendSmsRequest
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dysmsapi20170525.client import Client
from alibabacloud_tea_util.models import RuntimeOptions
import random
import time
from datetime import datetime, timedelta
import sqlite3
from config import (
    ALIYUN_ACCESS_KEY_ID,
    ALIYUN_ACCESS_KEY_SECRET,
    ALIYUN_SMS_SIGN_NAME,
    ALIYUN_SMS_TEMPLATE_CODE,
)

class SMSVerification:
    def __init__(self, db_path="users.db"):
        self.db_path = db_path
        self.init_db()
        self.client = self._create_client()

    def _create_client(self):
        """
        使用AK&SK初始化账号Client
        @return: Client
        """
        config = open_api_models.Config(
            access_key_id=ALIYUN_ACCESS_KEY_ID,
            access_key_secret=ALIYUN_ACCESS_KEY_SECRET
        )
        # 访问的域名
        config.endpoint = 'dysmsapi.aliyuncs.com'
        return Client(config)

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 创建验证码表
        c.execute('''
            CREATE TABLE IF NOT EXISTS verification_codes (
                phone TEXT PRIMARY KEY,
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

    def send_code(self, phone_number):
        """
        发送验证码
        返回: (bool, str) - (是否成功, 错误信息)
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        try:
            # 检查是否存在未过期的验证码
            c.execute("SELECT created_time, attempts, last_attempt_time FROM verification_codes WHERE phone = ?", 
                     (phone_number,))
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
            
            # 构建请求对象
            runtime = RuntimeOptions()
            send_sms_request = SendSmsRequest(
                phone_numbers=phone_number,
                sign_name=ALIYUN_SMS_SIGN_NAME,
                template_code=ALIYUN_SMS_TEMPLATE_CODE,
                template_param='{"code":"' + code + '"}'
            )
            
            # 发送短信
            response = self.client.send_sms_with_options(send_sms_request, runtime)
            
            if response.body.code == "OK":
                # 保存或更新验证码
                c.execute('''
                    INSERT OR REPLACE INTO verification_codes 
                    (phone, code, created_time, attempts, last_attempt_time)
                    VALUES (?, ?, ?, ?, ?)
                ''', (phone_number, code, current_time.strftime('%Y-%m-%d %H:%M:%S'), 
                      attempts + 1 if result else 1, 
                      current_time.strftime('%Y-%m-%d %H:%M:%S')))
                conn.commit()
                return True, "验证码已发送"
            else:
                return False, f"发送失败: {response.body.message}"
                
        except Exception as e:
            return False, f"发送失败: {str(e)}"
        finally:
            conn.close()

    def verify_code(self, phone_number, code):
        """
        验证验证码
        返回: (bool, str) - (是否验证成功, 错误信息)
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        try:
            c.execute("SELECT code, created_time FROM verification_codes WHERE phone = ?", 
                     (phone_number,))
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
            c.execute("DELETE FROM verification_codes WHERE phone = ?", (phone_number,))
            conn.commit()
            
            return True, "验证成功"
            
        except Exception as e:
            return False, f"验证失败: {str(e)}"
        finally:
            conn.close()

    def is_valid_phone(self, phone_number):
        """验证手机号格式"""
        import re
        pattern = r'^1[3-9]\d{9}$'
        return bool(re.match(pattern, phone_number))
