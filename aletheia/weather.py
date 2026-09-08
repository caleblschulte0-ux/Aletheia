"""What the weather is doing where he actually is.

One of the most ordinary things anybody asks an assistant, and it was a
25-80 second planner round trip ending in nothing. Registered NOT_BUILT
this morning; the ticket said it was "a source decision rather than a
build", and it was.

NO API KEY, ANYWHERE. The United States National Weather Service serves
forecasts to anyone who sends a User-Agent, and `api.zippopotam.us`
turns a postal code into a point. Both are free and neither wants an
account, which matters for the reason `doctext` gives about itself: a
feature that needs a key somebody has to remember to obtain is a
capability that says AVAILABLE on one machine.

HIS LOCATION IS ALREADY ON FILE. `profile` holds Hartford, SD, 57033 —
parsed out of what her memory already knew about him. So the answer to
"what's the weather" needs nothing from him at all, which is the whole
point: he asked a three-word question and should get a sentence back.

WHAT IT REFUSES TO DO. The NWS covers the United States. Somewhere else,
or a postal code that resolves to nothing, and she says exactly that and
names what would fix it — rather than reaching for a second provider she
has not been given and cannot verify. A confident forecast for the wrong
Hartford is worse than no forecast: there are at least four.

CACHED, because a forecast does not change in the ninety seconds between
him asking twice, and because two network calls for a repeated question
is the round trip this file exists to remove.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from aletheia import stateio

ACTOR = "weather"

# The NWS asks for a User-Agent that identifies the caller. It is in
# their terms rather than a nicety, and a bare urllib default is refused.
AGENT = "Aletheia personal assistant (local, single user)"

POINT_URL = "https://api.zippopotam.us/us/{zip}"
GRID_URL = "https://api.weather.gov/points/{lat},{lon}"

# A forecast is issued hourly and does not move in between. Long enough
# that asking twice costs one call, short enough to still be today's.
CACHE_SECONDS = 1800
TIMEOUT_S = 15


class WeatherUnavailable(RuntimeError):
    """She could not find out, and the message says why and what would fix it."""


def _cache_path():
    return stateio.private_dir("weather") / "forecast.json"


def _get(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": AGENT, "Accept": "application/geo+json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def where_he_is() -> tuple[str, str]:
    """(postal code, a name for it) out of what she already knows.

    Never invents a location: without a postal code on file there is no
    guess worth making, because there are four Hartfords and the wrong
    one is worse than nothing.
    """
    try:
        from aletheia import profile
        code = str(profile.answer("postal_code") or "").strip()
        city = str(profile.answer("city") or "").strip()
        state = str(profile.answer("state") or "").strip()
    except Exception:
        code, city, state = "", "", ""
    name = ", ".join([p for p in (city, state) if p]) or "where you live"
    return code, name


def _point(code: str) -> tuple[float, float, str]:
    try:
        data = _get(POINT_URL.format(zip=urllib.parse.quote(code)))
        place = (data.get("places") or [])[0]
        return (float(place["latitude"]), float(place["longitude"]),
                f"{place['place name']}, {place['state abbreviation']}")
    except Exception as exc:
        raise WeatherUnavailable(
            f"I couldn't turn {code} into a place ({type(exc).__name__}). "
            "The postal code on file may be wrong — tell me where you live "
            "and I'll remember it.") from None


def _periods(lat: float, lon: float) -> list[dict]:
    try:
        grid = _get(GRID_URL.format(lat=round(lat, 4), lon=round(lon, 4)))
        forecast = _get(grid["properties"]["forecast"])
        return list(forecast["properties"]["periods"])
    except Exception as exc:
        raise WeatherUnavailable(
            "I couldn't reach the weather service just now "
            f"({type(exc).__name__}). It covers the United States only — if "
            "you are somewhere else I have no source for it yet."
        ) from None


def forecast(*, fresh: bool = False) -> dict:
    """Today and the next few periods, cached for half an hour."""
    if not fresh:
        try:
            cached = stateio.read_json(_cache_path())
            age = stateio.seconds_since(cached.get("at")) \
                if hasattr(stateio, "seconds_since") else None
            if age is None:
                import datetime as dt
                at = dt.datetime.fromisoformat(str(cached["at"]).replace("Z", "+00:00"))
                age = (dt.datetime.now(dt.timezone.utc) - at).total_seconds()
            if age < CACHE_SECONDS and cached.get("periods"):
                return cached
        except Exception:
            pass

    code, name = where_he_is()
    if not code:
        raise WeatherUnavailable(
            "I don't know where you are. Tell me your postcode and I'll "
            "remember it, and then I can just answer this.")
    lat, lon, resolved = _point(code)
    periods = _periods(lat, lon)
    value = {"at": stateio.utcnow(), "place": resolved or name,
             "periods": periods[:6]}
    try:
        stateio.write_json_atomic(_cache_path(), value)
    except Exception:
        pass                      # a cache that cannot be written is not a failure
    return value


def spoken(when: str = "") -> str:
    """One sentence, out loud. Never raises — it says what went wrong.

    `when` is his word: nothing for now, or "tomorrow"/"tonight". A
    period whose name he did not ask for is not an answer to his
    question, so an unmatched word falls back to the current period
    rather than picking something and sounding certain.
    """
    try:
        data = forecast()
    except WeatherUnavailable as exc:
        return str(exc)
    except Exception as exc:
        return (f"I couldn't check the weather ({type(exc).__name__}). "
                "Everything else still works.")

    periods = data.get("periods") or []
    if not periods:
        return "The weather service gave me nothing back just now."

    wanted = " ".join(str(when or "").split()).casefold()
    chosen = periods[0]
    if wanted:
        # TOMORROW IS NOT ONE OF THEIR WORDS. The service names
        # periods Today / Tonight / Wednesday / Wednesday Night, so
        # "tomorrow" matched nothing and the fallback answered with
        # TODAY's forecast under today's label — a different
        # question than the one he asked, answered confidently,
        # which is the kind he cannot catch. It is the first period
        # after tonight: arithmetic on the list, not a guess.
        if wanted.startswith("tomorrow"):
            later = [p for p in periods
                     if str(p.get("name", "")).casefold()
                     not in ("today", "tonight", "this afternoon",
                             "this morning", "overnight")]
            if not later:
                return ("I only have today's forecast just now — "
                        "ask me again later and I'll have tomorrow's.")
            chosen = later[0]
        else:
            for period in periods:
                if wanted in str(period.get("name", "")).casefold():
                    chosen = period
                    break

    name = str(chosen.get("name") or "").strip()
    temp = chosen.get("temperature")
    unit = chosen.get("temperatureUnit") or "F"
    short = str(chosen.get("shortForecast") or "").strip().rstrip(".")
    lead = "Right now" if chosen is periods[0] and not wanted else name
    return f"{lead} in {data['place']}: {short}, {temp} degrees."
