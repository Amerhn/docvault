"""Sends the password reset code.

SmtpMailer    - real email through any SMTP server (for example Gmail with an app password).
ConsoleMailer - demo mode: prints the email in the backend window. Use it only for local demos.
"""
import smtplib
from email.message import EmailMessage


class MailError(Exception):
    pass


class ConsoleMailer:
    name = "console"

    def send(self, to: str, subject: str, body: str) -> None:
        print("\n" + "=" * 60)
        print("EMAIL (demo mode: SMTP is not configured, so nothing was sent)")
        print("To: %s\nSubject: %s\n\n%s" % (to, subject, body))
        print("=" * 60 + "\n", flush=True)


class SmtpMailer:
    name = "smtp"

    def __init__(self, host, port, user, password, sender):
        self.host, self.port, self.user, self.password, self.sender = host, port, user, password, sender

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender or self.user
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                smtp.starttls()
                if self.user:
                    smtp.login(self.user, self.password or "")
                smtp.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailError("Could not send the email: %s" % exc) from exc


def make_mailer(settings):
    if settings.smtp_host:
        return SmtpMailer(settings.smtp_host, settings.smtp_port, settings.smtp_user,
                          settings.smtp_password, settings.smtp_from)
    return ConsoleMailer()
