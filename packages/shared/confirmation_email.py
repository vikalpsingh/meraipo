"""Branded confirmation message with an accessible plain-text alternative."""

from html import escape

from packages.shared.email_preferences import CATEGORY_LABELS


def confirmation_content(origin, action, category=None, reminder=False):
    origin = origin.rstrip("/")
    confirm = origin + "/email-alerts/verify#" + action
    stop = origin + "/email-alerts/unsubscribe#" + action
    preference = CATEGORY_LABELS.get(category, "Your selected IPO preference")
    subject = (
        "Reminder: confirm your MeraIPO alerts"
        if reminder
        else "Welcome to MeraIPO — confirm your IPO alerts"
    )
    text = f"""MeraIPO — Follow the opportunity. Know the risk.
Confirm your IPO alerts
MeraIPO helps you research IPOs, follow opening and listing dates, and understand the latest recorded grey-market premium (GMP).
Your preference: {preference}
After confirmation, receive one combined opening-day email from 9:00 AM IST when IPOs match your subscription category. Explore issue details and important dates on MeraIPO.
We send only IPO alerts matching your subscription category, plus confirmation and subscription-management messages. We do not send unrelated promotions or share your contact details with marketing companies or brands.
Confirm your email within 7 days of this email being created:
{confirm}
Explore MeraIPO: {origin}
GMP is unofficial, may change, and does not guarantee listing gains. These alerts are for information, not investment advice.
If you did not request this subscription, ignore this email. Stop confirmation reminders or unsubscribe: {stop}
"""
    e = escape
    markup = f"""<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;background:#edf3f1;font-family:Arial,sans-serif;color:#193b31">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#fff;border:1px solid #d6e4dd">
<tr><td style="padding:24px"><a href="{e(origin)}"><img src="{e(origin)}/meraipo-logo-market-header.png" width="180" height="60" alt="MeraIPO" style="display:block;object-fit:contain;border:0;max-width:100%"></a></td></tr>
<tr><td style="padding:28px;background:#103f36;color:#fff"><p style="color:#a7ead1;margin:0 0 12px">YOUR IPO WATCH</p><h1 style="font-size:28px;margin:0">Make your next IPO decision better informed.</h1><p style="line-height:1.6">Confirm your email to start following the IPOs that match your interests.</p></td></tr>
<tr><td style="padding:28px;line-height:1.7"><h2 style="font-size:20px">Welcome to MeraIPO</h2><p>Research IPOs, keep track of important dates and understand the latest recorded GMP — all in one place.</p>
<ul><li>Opening-day alerts from 9:00 AM IST.</li><li>One combined email containing matching IPOs.</li><li>Issue details, dates and GMP context, with links to explore more.</li></ul>
<p style="padding:16px;background:#edf8f1"><strong>Your preference:</strong> {e(preference)}</p>
<p><a href="{e(confirm)}" style="display:inline-block;background:#12624b;color:#fff;padding:14px 24px;border-radius:8px;text-decoration:none;font-weight:bold">Confirm my IPO alerts</a></p>
<p>This confirmation link is valid for <strong>7 days</strong> from when this email was created.</p>
<p>We send only IPO alerts based on your subscription category, plus confirmation and subscription-management messages. No unrelated promotions. Your contact details are not shared with marketing companies or brands.</p>
<p><a href="{e(origin)}" style="color:#12624b">Explore MeraIPO →</a></p></td></tr>
<tr><td style="padding:24px;background:#f2f6f4;color:#52665e;font-size:12px;line-height:1.6">GMP is unofficial and may change. It does not guarantee listing gains. For information only, not investment advice.<br>If you did not request this subscription, ignore this email.<br><a href="{e(stop)}">Stop reminders / unsubscribe</a></td></tr>
</table></td></tr></table></body></html>"""
    return subject, text, markup
