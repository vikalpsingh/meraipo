"""Allowlisted official broker destinations; never accepts user-supplied URLs."""

from html import escape

BROKERS = {
    "zerodha": ("Zerodha — Bids → IPO", "https://kite.zerodha.com/"),
    "groww": ("Groww", "https://groww.in/ipo"),
    "angel_one": ("Angel One", "https://www.angelone.in/upcoming-ipo"),
    "upstox": ("Upstox", "https://upstox.com/ipo/"),
}


def broker_content(broker):
    if broker not in BROKERS:
        return "", ""
    name, url = BROKERS[broker]
    text = f"\nApply through your broker: {name}\n{url}\nOpens your broker’s website. Login may be required. Opening this link does not submit an IPO application.\n"
    html = f'<div style="padding:20px;background:#edf8f1"><h2 style="font-size:18px">Apply through your broker</h2><a href="{escape(url)}" target="_blank" rel="noopener noreferrer">{escape(name)} →</a><p>Opens your broker’s website. Login may be required. Opening this link does not submit an IPO application.</p></div>'
    return text, html
