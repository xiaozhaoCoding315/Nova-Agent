"""SMTP 邮件发送：注册验证码 / 找回密码验证码。

使用标准库 smtplib（无新增依赖），QQ 邮箱、163、企业邮箱、阿里云邮件推送
（DirectMail）等标准 SMTP 服务均可直接配置使用。发送在线程池中执行，避免
阻塞事件循环。
"""
import asyncio
import random
import smtplib
from email.message import EmailMessage

import structlog

from app.config import settings

logger = structlog.get_logger()

_CODE_ALPHABET = "23456789"  # 去掉易混淆的 0/1


def generate_email_code() -> str:
    return "".join(random.SystemRandom().choice(_CODE_ALPHABET) for _ in range(6))


def _send_sync(to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    if settings.smtp_ssl:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)


async def send_email(to: str, subject: str, body: str) -> None:
    await asyncio.to_thread(_send_sync, to, subject, body)


async def send_verification_code(email: str, code: str, purpose: str) -> None:
    action = "注册" if purpose == "register" else "重置密码"
    subject = f"Nova Agent {action}验证码：{code}"
    body = (
        f"你的 Nova Agent {action}验证码是：{code}\n\n"
        f"{settings.email_code_ttl_minutes} 分钟内有效。如果不是你本人的操作，请忽略这封邮件。"
    )
    await send_email(email, subject, body)


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    if len(name) <= 2:
        shown = name[:1] + "*"
    else:
        shown = name[:2] + "***"
    return f"{shown}@{domain}"
