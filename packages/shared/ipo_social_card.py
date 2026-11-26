"""Public, labelled PNG reused by opening-day email and X; no subscriber data."""

from io import BytesIO
from textwrap import wrap

from PIL import Image, ImageDraw, ImageFont


def render(name, price, premium, stamp, opening_date, closing=False, current=False):
    image = Image.new("RGB", (1200, 630), "#103c3d")
    draw = ImageDraw.Draw(image)

    def label(x, y, text, size=28, color="#ffffff"):
        draw.text((x, y), text, font=ImageFont.load_default(size=size), fill=color)

    label(
        54,
        34,
        "MERAIPO  /  OPEN FOR SUBSCRIPTION"
        if current
        else "MERAIPO  /  LAST APPLICATION DAY"
        if closing
        else "MERAIPO  /  OPENING DAY",
        26,
        "#77e1bb",
    )
    for i, line in enumerate(wrap(name, width=43)[:2]):
        label(54, 94 + i * 46, line, 38)
    label(
        54,
        202,
        ("Opened " if current else "Closes " if closing else "Opens ")
        + str(opening_date)
        + "  |  meraipo.com",
        25,
    )
    draw.rounded_rectangle((44, 254, 1156, 480), radius=18, fill="#1c5050")
    label(70, 278, "IPO upper band", 24, "#b4d8d0")
    label(70, 318, f"INR {price:,.2f}" if price else "Not available", 39)
    label(630, 278, "Unofficial GMP", 24, "#b4d8d0")
    label(
        630,
        318,
        f"INR {premium:+,.2f} ({premium / price * 100:+.1f}%)"
        if premium is not None and price
        else "No fresh quote",
        34,
        "#77e1bb",
    )
    label(
        70,
        406,
        "GMP-implied price: "
        + (f"INR {price + premium:,.2f}" if price and premium is not None else "Unavailable"),
        27,
    )
    label(54, 506, "Snapshot: " + stamp, 21, "#b4d8d0")
    label(54, 548, "GMP is unofficial, not a guaranteed listing price or return.", 23)
    label(54, 582, "IPO investing involves loss risk. Research before applying.", 22, "#b4d8d0")
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()
