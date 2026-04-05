"""Weather function calling tools for LiveKit agent."""

import logging

import httpx
from livekit.agents import llm

logger = logging.getLogger(__name__)


@llm.function_tool(
    description=(
        "Get the current weather for a US zipcode. "
        "Call this when the user asks about weather, temperature, or conditions for a location."
    )
)
async def get_weather(zipcode: str) -> str:
    """Get weather for a US zipcode like 90210 or 10001."""
    logger.info(f"get_weather called with zipcode={zipcode}")

    # Open-Meteo geocoding works best with just the city name
    clean_location = zipcode.split(",")[0].strip()

    async with httpx.AsyncClient(timeout=10) as client:
        # Step 1: Geocode using Open-Meteo's free geocoding
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={clean_location}&count=1"
        try:
            geo_resp = await client.get(geo_url)
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()
            results = geo_data.get("results", [])
            if not results:
                return f"Could not find location for zipcode {zipcode}."
            lat = float(results[0]["latitude"])
            lon = float(results[0]["longitude"])
            display_name = results[0].get("name", zipcode)
        except Exception as e:
            logger.error(f"Geocoding failed: {e}")
            return f"Sorry, I couldn't look up zipcode {zipcode}."

        # Step 2: Fetch weather from Open-Meteo
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
            f"&temperature_unit=fahrenheit"
            f"&wind_speed_unit=mph"
        )
        try:
            weather_resp = await client.get(weather_url)
            weather_resp.raise_for_status()
            weather_data = weather_resp.json()
            current = weather_data["current"]
        except Exception as e:
            logger.error(f"Weather fetch failed: {e}")
            return f"Sorry, I couldn't get the weather for {zipcode}."

    temp = current["temperature_2m"]
    humidity = current["relative_humidity_2m"]
    wind = current["wind_speed_10m"]
    code = current["weather_code"]
    condition = _weather_code_to_text(code)

    result = _format_weather_utterance(display_name, zipcode, temp, humidity, wind, condition)
    logger.info(f"Weather result: {result}")
    return result


def _speak_number(value: float) -> str:
    """Format a number for natural TTS output.

    Whole numbers render without decimals.  Fractional numbers use 'point'
    instead of a dot so TTS engines don't say 'dot'.
    """
    if value == int(value):
        return str(int(value))
    text = f"{value:.1f}"
    whole, frac = text.split(".")
    return f"{whole} point {frac}"


def _format_weather_utterance(
    place: str, zipcode: str, temp: float, humidity: float, wind: float, condition: str
) -> str:
    """Build a voice-friendly weather summary.

    Rules:
    - Numbers use 'point' not 'dot' for decimals
    - 'miles per hour' not 'mph'
    - 'percent' not '%'
    - 'degrees Fahrenheit' spelled out
    - Natural conversational phrasing
    """
    temp_str = _speak_number(temp)
    wind_str = _speak_number(wind)
    humidity_str = _speak_number(humidity)

    return (
        f"Right now in {place}, zipcode {zipcode}, "
        f"it's {temp_str} degrees Fahrenheit with {condition}. "
        f"Winds are {wind_str} miles per hour "
        f"and humidity is at {humidity_str} percent."
    )


def _weather_code_to_text(code: int) -> str:
    """Convert WMO weather code to human-readable text."""
    codes = {
        0: "clear sky",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "foggy",
        48: "depositing rime fog",
        51: "light drizzle",
        53: "moderate drizzle",
        55: "dense drizzle",
        61: "slight rain",
        63: "moderate rain",
        65: "heavy rain",
        71: "slight snow",
        73: "moderate snow",
        75: "heavy snow",
        80: "slight rain showers",
        81: "moderate rain showers",
        82: "violent rain showers",
        95: "thunderstorm",
        96: "thunderstorm with slight hail",
        99: "thunderstorm with heavy hail",
    }
    return codes.get(code, "unknown conditions")
