"""MCP Weather Server using FastMCP.

Exposes get_weather as an MCP tool via SSE transport.
The LiveKit agent discovers and calls this tool via MCP protocol.
"""

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Weather MCP Server")


@mcp.tool()
def get_weather(location: str) -> str:
    """Get the current weather for a city name or US zipcode.

    Args:
        location: A city name (e.g. 'Beverly Hills') or US zipcode (e.g. '90210')

    Returns:
        Human-readable weather summary
    """
    # Open-Meteo geocoding works best with just the city name
    clean_location = location.split(",")[0].strip()

    with httpx.Client(timeout=10) as client:
        # Geocode using Open-Meteo's free API
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={clean_location}&count=1"
        try:
            geo_resp = client.get(geo_url)
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()
            results = geo_data.get("results", [])
            if not results:
                return f"Could not find location: {location}"
            lat = float(results[0]["latitude"])
            lon = float(results[0]["longitude"])
            place_name = results[0].get("name", location)
        except Exception as e:
            return f"Geocoding failed for {location}: {e}"

        # Fetch weather from Open-Meteo
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
            f"&temperature_unit=fahrenheit"
            f"&wind_speed_unit=mph"
        )
        try:
            weather_resp = client.get(weather_url)
            weather_resp.raise_for_status()
            weather_data = weather_resp.json()
            current = weather_data["current"]
        except Exception as e:
            return f"Weather fetch failed for {location}: {e}"

    temp = current["temperature_2m"]
    humidity = current["relative_humidity_2m"]
    wind = current["wind_speed_10m"]
    code = current["weather_code"]
    condition = _weather_code_to_text(code)

    return _format_weather_utterance(place_name, temp, humidity, wind, condition)


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
    place: str, temp: float, humidity: float, wind: float, condition: str
) -> str:
    """Build a voice-friendly weather summary.

    Rules:
    - Numbers use 'point' not 'dot' for decimals
    - 'miles per hour' not 'mph'
    - 'percent' not '%'
    - 'degrees Fahrenheit' spelled out
    - Wind described with natural phrasing
    - Humidity described with natural phrasing
    """
    temp_str = _speak_number(temp)
    wind_str = _speak_number(wind)
    humidity_str = _speak_number(humidity)

    parts = [
        f"Right now in {place} it's {temp_str} degrees Fahrenheit with {condition}.",
        f"Winds are {wind_str} miles per hour",
        f"and humidity is at {humidity_str} percent.",
    ]
    return " ".join(parts)


def _weather_code_to_text(code: int) -> str:
    codes = {
        0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
        45: "foggy", 48: "depositing rime fog",
        51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
        61: "slight rain", 63: "moderate rain", 65: "heavy rain",
        71: "slight snow", 73: "moderate snow", 75: "heavy snow",
        80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
        95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
    }
    return codes.get(code, "unknown conditions")


if __name__ == "__main__":
    mcp.run(transport="sse")
