"""What his money is worth in another currency.

"How much is 50 euros in dollars" went to a model (2026-10-07), which
cannot know today's rate and would have answered from memory - a number
that sounds right and is not. The European Central Bank publishes
reference rates every working day, and Frankfurter serves them with NO
KEY and no account, the same standard `weather` holds itself to.

Cached for the day: a reference rate is published once. When the service
cannot be reached she says so, never a remembered rate.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request

from aletheia import stateio

AGENT = "Aletheia personal assistant (local, single user)"
#: Tried in order: the service moved to .dev and kept .app answering.
URLS = ("https://api.frankfurter.dev/v1/latest?base={base}&symbols={to}",
        "https://api.frankfurter.app/latest?from={base}&to={to}")
TIMEOUT_S = 10

#: The words he says for a currency, and its code.
NAMES = {
    "dollar": "USD", "dollars": "USD", "usd": "USD", "bucks": "USD", "us dollars": "USD",
    "euro": "EUR", "euros": "EUR", "eur": "EUR",
    "pound": "GBP", "pounds": "GBP", "gbp": "GBP", "quid": "GBP", "british pounds": "GBP", "sterling": "GBP",
    "yen": "JPY", "jpy": "JPY", "japanese yen": "JPY",
    "canadian dollar": "CAD", "canadian dollars": "CAD", "cad": "CAD",
    "australian dollar": "AUD", "australian dollars": "AUD", "aud": "AUD",
    "peso": "MXN", "pesos": "MXN", "mexican pesos": "MXN", "mxn": "MXN",
    "franc": "CHF", "francs": "CHF", "swiss francs": "CHF", "chf": "CHF",
    "yuan": "CNY", "renminbi": "CNY", "cny": "CNY",
    "rupee": "INR", "rupees": "INR", "inr": "INR",
    "won": "KRW", "krw": "KRW", "krona": "SEK", "kronor": "SEK", "sek": "SEK",
}
SPOKEN = {"USD": ("dollar", "dollars"), "EUR": ("euro", "euros"), "GBP": ("pound", "pounds"),
          "JPY": ("yen", "yen"), "CAD": ("Canadian dollar", "Canadian dollars"),
          "AUD": ("Australian dollar", "Australian dollars"), "MXN": ("peso", "pesos"),
          "CHF": ("Swiss franc", "Swiss francs"), "CNY": ("yuan", "yuan"), "INR": ("rupee", "rupees"),
          "KRW": ("won", "won"), "SEK": ("krona", "kronor")}


class RatesUnavailable(RuntimeError):
    """She could not find out today's rate, and the message says so."""


def code_of(word: str) -> str | None:
    return NAMES.get(" ".join(str(word or "").casefold().split()))


def _cache_path():
    return stateio.private_dir("fx") / "rates.json"


def rate(base: str, to: str) -> tuple[float, str]:
    """(rate, the date it was published). Raises RatesUnavailable."""
    today = dt.date.today().isoformat()
    key = f"{base}->{to}"
    try:
        cached = json.loads(_cache_path().read_text(encoding="utf-8"))
    except Exception:
        cached = {}
    held = cached.get(key)
    if isinstance(held, dict) and held.get("fetched") == today:
        return float(held["rate"]), str(held.get("date") or today)
    last = None
    for url in URLS:
        try:
            request = urllib.request.Request(url.format(base=urllib.parse.quote(base), to=urllib.parse.quote(to)),
                                             headers={"User-Agent": AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                data = json.loads(response.read().decode("utf-8"))
            value = float(data["rates"][to])
            published = str(data.get("date") or today)
            cached[key] = {"rate": value, "date": published, "fetched": today}
            try:
                stateio.write_json_atomic(_cache_path(), cached)
            except Exception:
                pass
            return value, published
        except Exception as exc:  # noqa: BLE001 - every failure is "could not find out"
            last = exc
    raise RatesUnavailable("I couldn't reach the exchange-rate service just now, so I won't guess a rate. "
                           "Ask me again in a bit.") from last


def spoken(amount: float, base: str, to: str) -> str:
    """One sentence, out loud. Never raises."""
    try:
        value, published = rate(base, to)
    except RatesUnavailable as exc:
        return str(exc)
    converted = amount * value
    try:
        published = dt.date.fromisoformat(published).strftime("%A %d %B").replace(" 0", " ") + "'s"
    except ValueError:
        published = "the latest"
    one, many = SPOKEN.get(to, (to, to))
    src_one, src_many = SPOKEN.get(base, (base, base))
    return (f"{amount:,.2f}".rstrip("0").rstrip(".") + f" {src_one if amount == 1 else src_many} is about "
            f"{converted:,.2f} {one if round(converted, 2) == 1 else many}, by {published} European Central Bank rate.")
