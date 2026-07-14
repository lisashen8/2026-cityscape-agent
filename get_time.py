import sys
import os
import requests
import time
from datetime import datetime

def get_city_time(city):
    api_key = os.environ.get("MAPS_API_KEY")
    if not api_key:
        print("Error: MAPS_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    
    # 1. Geocode
    geo_url = f"https://maps.googleapis.com/maps/api/geocode/json?address={city}&key={api_key}"
    geo_res = requests.get(geo_url).json()
    if geo_res.get('status') != 'OK':
        print(f"Geocoding failed: {geo_res.get('status')}", file=sys.stderr)
        sys.exit(1)
        
    lat = geo_res['results'][0]['geometry']['location']['lat']
    lng = geo_res['results'][0]['geometry']['location']['lng']
    
    # 2. Timezone
    timestamp = int(time.time())
    tz_url = f"https://maps.googleapis.com/maps/api/timezone/json?location={lat},{lng}&timestamp={timestamp}&key={api_key}"
    tz_res = requests.get(tz_url).json()
    if tz_res.get('status') != 'OK':
        print(f"Timezone failed: {tz_res.get('status')}", file=sys.stderr)
        sys.exit(1)
        
    # Calculate local time
    # The API returns dstOffset and rawOffset in seconds
    total_offset = tz_res.get('dstOffset', 0) + tz_res.get('rawOffset', 0)
    local_time = timestamp + total_offset
    local_dt = datetime.utcfromtimestamp(local_time)
    
    print(local_dt.strftime("%I:%M %p").lstrip("0"))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_time.py <city>", file=sys.stderr)
        sys.exit(1)
    get_city_time(sys.argv[1])
