"""Email service for sending emails."""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app, url_for
import logging
import requests

logger = logging.getLogger(__name__)


def send_email(to_email, subject, html_body, text_body=None):
    """
    Send an email using a configured provider.

    Provider selection:
    - If `RESEND_API_KEY` is set, send via Resend HTTP API (recommended for Render; no Gmail needed)
    - Else, fall back to SMTP settings (`MAIL_*`)
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_body: HTML content of the email
        text_body: Plain text content (optional)
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        resend_api_key = (current_app.config.get('RESEND_API_KEY') or '').strip()
        if resend_api_key:
            return _send_email_resend(
                to_email=to_email,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
            )

        # Get email configuration
        mail_server = current_app.config.get('MAIL_SERVER', 'smtp.gmail.com')
        mail_port = current_app.config.get('MAIL_PORT', 587)
        mail_use_tls = current_app.config.get('MAIL_USE_TLS', True)
        mail_use_ssl = current_app.config.get('MAIL_USE_SSL', False)
        mail_username = current_app.config.get('MAIL_USERNAME', '')
        mail_password = current_app.config.get('MAIL_PASSWORD', '')
        mail_default_sender = current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@edumindai.com')
        
        # Check if email is configured
        if not mail_username or not mail_password:
            logger.warning("Email not configured. Skipping email send.")
            return False
        
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = mail_default_sender
        msg['To'] = to_email
        
        # Add text part if provided
        if text_body:
            text_part = MIMEText(text_body, 'plain')
            msg.attach(text_part)
        
        # Add HTML part
        html_part = MIMEText(html_body, 'html')
        msg.attach(html_part)
        
        # Send email
        if mail_use_ssl:
            with smtplib.SMTP_SSL(mail_server, mail_port) as server:
                server.login(mail_username, mail_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(mail_server, mail_port) as server:
                if mail_use_tls:
                    server.starttls()
                server.login(mail_username, mail_password)
                server.send_message(msg)
        
        logger.info(f"Email sent successfully to {to_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False


def _send_email_resend(to_email, subject, html_body, text_body=None):
    """
    Send an email using the Resend API.

    Requires:
    - RESEND_API_KEY
    - RESEND_FROM (recommended). If missing, falls back to MAIL_DEFAULT_SENDER.
    """
    try:
        api_key = (current_app.config.get('RESEND_API_KEY') or '').strip()
        if not api_key:
            return False

        from_email = (
            (current_app.config.get('RESEND_FROM') or '').strip()
            or (current_app.config.get('MAIL_DEFAULT_SENDER') or '').strip()
            or 'noreply@edumindai.com'
        )

        payload = {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }
        if text_body:
            payload["text"] = text_body

        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )

        if 200 <= resp.status_code < 300:
            logger.info("Resend email sent successfully to %s", to_email)
            return True

        logger.error(
            "Resend email failed (%s): %s",
            resp.status_code,
            (resp.text or "").strip()[:2000],
        )
        return False
    except Exception as e:
        logger.error("Failed to send Resend email to %s: %s", to_email, str(e))
        return False


def send_verification_email(user):
    """
    Send email verification email to user.
    
    Args:
        user: User object
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Generate verification token
        token = user.generate_email_verification_token()
        
        # Create verification URL
        verification_url = url_for('auth.verify_email', token=token, _external=True)
        
        # Email subject
        subject = "Verify Your Email - EduMind AI"
        
        # HTML email body
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #0f172a;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .card {{
                    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
                    border-radius: 16px;
                    padding: 40px;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .logo {{
                    width: 60px;
                    height: 60px;
                    background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 50%, #ec4899 100%);
                    border-radius: 12px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    margin-bottom: 15px;
                }}
                .logo-text {{
                    color: white;
                    font-size: 24px;
                    font-weight: bold;
                }}
                .title {{
                    color: #f8fafc;
                    font-size: 24px;
                    font-weight: 600;
                    margin-bottom: 10px;
                }}
                .subtitle {{
                    color: #94a3b8;
                    font-size: 14px;
                }}
                .content {{
                    color: #cbd5e1;
                    line-height: 1.6;
                    margin-bottom: 30px;
                }}
                .button {{
                    display: inline-block;
                    background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
                    color: white;
                    text-decoration: none;
                    padding: 14px 32px;
                    border-radius: 12px;
                    font-weight: 600;
                    font-size: 16px;
                    text-align: center;
                    transition: all 0.2s;
                }}
                .button:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 10px 20px rgba(59, 130, 246, 0.3);
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid rgba(255, 255, 255, 0.1);
                }}
                .footer-text {{
                    color: #64748b;
                    font-size: 12px;
                }}
                .link {{
                    color: #3b82f6;
                    word-break: break-all;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <div class="header">
                        <div class="logo">
                            <span class="logo-text">E</span>
                        </div>
                        <h1 class="title">Verify Your Email</h1>
                        <p class="subtitle">EduMind AI - Learning Reimagined</p>
                    </div>
                    
                    <div class="content">
                        <p>Hello {user.first_name},</p>
                        <p>Thank you for registering with EduMind AI! Please verify your email address by clicking the button below:</p>
                        
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{verification_url}" class="button">Verify Email Address</a>
                        </div>
                        
                        <p>Or copy and paste this link into your browser:</p>
                        <p class="link">{verification_url}</p>
                        
                        <p>This link will expire in 24 hours.</p>
                        
                        <p>If you didn't create an account, you can safely ignore this email.</p>
                    </div>
                    
                    <div class="footer">
                        <p class="footer-text">
                            &copy; 2024 EduMind AI. All rights reserved.<br>
                            This is an automated message, please do not reply.
                        </p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        text_body = f"""
        Verify Your Email - EduMind AI
        
        Hello {user.first_name},
        
        Thank you for registering with EduMind AI! Please verify your email address by clicking the link below:
        
        {verification_url}
        
        This link will expire in 24 hours.
        
        If you didn't create an account, you can safely ignore this email.
        
        Best regards,
        EduMind AI Team
        """
        
        # Send email
        return send_email(user.email, subject, html_body, text_body)
        
    except Exception as e:
        logger.error(f"Failed to send verification email to {user.email}: {str(e)}")
        return False


def send_otp_email(email, otp_code, purpose):
    """
    Send OTP email to user.
    
    Args:
        email: Recipient email address
        otp_code: 6-digit OTP code
        purpose: Purpose of OTP ('registration' or 'password_reset')
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Determine subject and message based on purpose
        if purpose == 'registration':
            subject = "Your Registration OTP - EduMind AI"
            purpose_text = "complete your registration"
        else:  # password_reset
            subject = "Your Password Reset OTP - EduMind AI"
            purpose_text = "reset your password"
        
        # HTML email body
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #0f172a;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .card {{
                    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
                    border-radius: 16px;
                    padding: 40px;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .logo {{
                    width: 60px;
                    height: 60px;
                    background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 50%, #ec4899 100%);
                    border-radius: 12px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    margin-bottom: 15px;
                }}
                .logo-text {{
                    color: white;
                    font-size: 24px;
                    font-weight: bold;
                }}
                .title {{
                    color: #f8fafc;
                    font-size: 24px;
                    font-weight: 600;
                    margin-bottom: 10px;
                }}
                .subtitle {{
                    color: #94a3b8;
                    font-size: 14px;
                }}
                .content {{
                    color: #cbd5e1;
                    line-height: 1.6;
                    margin-bottom: 30px;
                }}
                .otp-code {{
                    background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
                    color: white;
                    font-size: 32px;
                    font-weight: bold;
                    padding: 20px 40px;
                    border-radius: 12px;
                    text-align: center;
                    letter-spacing: 8px;
                    margin: 30px 0;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid rgba(255, 255, 255, 0.1);
                }}
                .footer-text {{
                    color: #64748b;
                    font-size: 12px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <div class="header">
                        <div class="logo">
                            <span class="logo-text">E</span>
                        </div>
                        <h1 class="title">Your Verification Code</h1>
                        <p class="subtitle">EduMind AI - Learning Reimagined</p>
                    </div>
                    
                    <div class="content">
                        <p>Hello,</p>
                        <p>Use the following OTP code to {purpose_text}:</p>
                        
                        <div class="otp-code">
                            {otp_code}
                        </div>
                        
                        <p>This code will expire in 5 minutes.</p>
                        
                        <p>If you didn't request this code, you can safely ignore this email.</p>
                    </div>
                    
                    <div class="footer">
                        <p class="footer-text">
                            &copy; 2024 EduMind AI. All rights reserved.<br>
                            This is an automated message, please do not reply.
                        </p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        text_body = f"""
        Your Verification Code - EduMind AI
        
        Hello,
        
        Use the following OTP code to {purpose_text}:
        
        {otp_code}
        
        This code will expire in 5 minutes.
        
        If you didn't request this code, you can safely ignore this email.
        
        Best regards,
        EduMind AI Team
        """
        
        # Send email
        return send_email(email, subject, html_body, text_body)
        
    except Exception as e:
        logger.error(f"Failed to send OTP email to {email}: {str(e)}")
        return False


def send_password_reset_email(user, token):
    """
    Send password reset email to user.
    
    Args:
        user: User object
        token: Password reset token
    
    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        # Create reset URL
        reset_url = url_for('auth.reset_password', token=token, _external=True)
        
        # Email subject
        subject = "Reset Your Password - EduMind AI"
        
        # HTML email body
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background-color: #0f172a;
                    margin: 0;
                    padding: 0;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .card {{
                    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
                    border-radius: 16px;
                    padding: 40px;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                }}
                .header {{
                    text-align: center;
                    margin-bottom: 30px;
                }}
                .logo {{
                    width: 60px;
                    height: 60px;
                    background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 50%, #ec4899 100%);
                    border-radius: 12px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    margin-bottom: 15px;
                }}
                .logo-text {{
                    color: white;
                    font-size: 24px;
                    font-weight: bold;
                }}
                .title {{
                    color: #f8fafc;
                    font-size: 24px;
                    font-weight: 600;
                    margin-bottom: 10px;
                }}
                .subtitle {{
                    color: #94a3b8;
                    font-size: 14px;
                }}
                .content {{
                    color: #cbd5e1;
                    line-height: 1.6;
                    margin-bottom: 30px;
                }}
                .button {{
                    display: inline-block;
                    background: linear-gradient(135deg, #22c55e 0%, #10b981 100%);
                    color: white;
                    text-decoration: none;
                    padding: 14px 32px;
                    border-radius: 12px;
                    font-weight: 600;
                    font-size: 16px;
                    text-align: center;
                    transition: all 0.2s;
                }}
                .button:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 10px 20px rgba(34, 197, 94, 0.3);
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    padding-top: 20px;
                    border-top: 1px solid rgba(255, 255, 255, 0.1);
                }}
                .footer-text {{
                    color: #64748b;
                    font-size: 12px;
                }}
                .link {{
                    color: #22c55e;
                    word-break: break-all;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="card">
                    <div class="header">
                        <div class="logo">
                            <span class="logo-text">E</span>
                        </div>
                        <h1 class="title">Reset Your Password</h1>
                        <p class="subtitle">EduMind AI - Learning Reimagined</p>
                    </div>
                    
                    <div class="content">
                        <p>Hello {user.first_name},</p>
                        <p>We received a request to reset your password. Click the button below to create a new password:</p>
                        
                        <div style="text-align: center; margin: 30px 0;">
                            <a href="{reset_url}" class="button">Reset Password</a>
                        </div>
                        
                        <p>Or copy and paste this link into your browser:</p>
                        <p class="link">{reset_url}</p>
                        
                        <p>This link will expire in 1 hour.</p>
                        
                        <p>If you didn't request a password reset, you can safely ignore this email. Your password will remain unchanged.</p>
                    </div>
                    
                    <div class="footer">
                        <p class="footer-text">
                            &copy; 2024 EduMind AI. All rights reserved.<br>
                            This is an automated message, please do not reply.
                        </p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        text_body = f"""
        Reset Your Password - EduMind AI
        
        Hello {user.first_name},
        
        We received a request to reset your password. Click the link below to create a new password:
        
        {reset_url}
        
        This link will expire in 1 hour.
        
        If you didn't request a password reset, you can safely ignore this email. Your password will remain unchanged.
        
        Best regards,
        EduMind AI Team
        """
        
        # Send email
        return send_email(user.email, subject, html_body, text_body)
        
    except Exception as e:
        logger.error(f"Failed to send password reset email to {user.email}: {str(e)}")
        return False
