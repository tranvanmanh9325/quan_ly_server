import sys
import os
import subprocess
import requests
import json

# Compile or import AppleWLoc_pb2
try:
    import AppleWLoc_pb2
except ImportError:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    sys.path.insert(0, '/tmp')
    try:
        import AppleWLoc_pb2
    except ImportError:
        AppleWLoc_pb2 = None


def get_connected_bssid():
    """
    Auto-detects BSSID of the currently connected Wi-Fi router or scans visible APs.
    """
    # 1. Fast path: check current Wi-Fi link status
    try:
        out = subprocess.check_output('iw dev wlp2s0 link 2>/dev/null', shell=True).decode('utf-8', errors='ignore')
        for line in out.splitlines():
            if 'Connected to' in line:
                parts = line.split()
                if len(parts) >= 3:
                    return parts[2].lower().strip()
    except Exception:
        pass

    # 2. Scanning path: scan nearby BSSIDs
    try:
        out = subprocess.check_output('echo 09032005 | sudo -S iw dev wlp2s0 scan 2>/dev/null', shell=True).decode('utf-8', errors='ignore')
        for line in out.splitlines():
            line = line.strip()
            if line.startswith('BSS '):
                b = line.split()[1].split('(')[0].lower().strip()
                if len(b.replace(':', '')) == 12:
                    return b
    except Exception:
        pass

    return None


def locate_via_apple_wps(bssid):
    """
    Queries Apple Location Services (WPS) using Wi-Fi BSSID to retrieve precise GPS coordinates.
    No API key required; relies on crowdsourced global Wi-Fi positioning system.
    """
    if not AppleWLoc_pb2 or not bssid:
        return None

    try:
        apple_wloc = AppleWLoc_pb2.AppleWLoc()
        dev = apple_wloc.wifi_devices.add()
        dev.bssid = bssid
        apple_wloc.unknown_value1 = 0
        apple_wloc.return_single_result = 1

        ser = apple_wloc.SerializeToString()
        headers = {'User-Agent': 'locationd/1753.17 CFNetwork/889.9 Darwin/17.2.0'}
        data = (
            b"\x00\x01\x00\x05en_US\x00\x13com.apple.locationd\x00\x0a8.1.12B411\x00\x00\x00\x01\x00\x00\x00"
            + bytes((len(ser),))
            + ser
        )

        r = requests.post('https://gs-loc.apple.com/clls/wloc', headers=headers, data=data, timeout=5)
        if r.status_code != 200 or len(r.content) <= 10:
            return None

        resp_obj = AppleWLoc_pb2.AppleWLoc()
        resp_obj.ParseFromString(r.content[10:])

        for d in resp_obj.wifi_devices:
            if d.HasField('location'):
                lat = d.location.latitude * 1e-8
                lon = d.location.longitude * 1e-8
                if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != -180.0 and lon != -180.0):
                    return (lat, lon)
    except Exception:
        pass

    return None


def reverse_geocode(lat, lon):
    """
    Reverse-geocodes GPS coordinates into accurate administrative locality (Ward, District, City, Country).
    """
    try:
        url = f'https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat:.6f}&longitude={lon:.6f}&localityLanguage=en'
        res = requests.get(url, timeout=5).json()

        locality = res.get('locality', '').strip()
        subdivision = res.get('principalSubdivision', '').strip()
        city = res.get('city', '').strip()
        country = res.get('countryName', 'Vietnam').strip()
        country_code = res.get('countryCode', 'VN').strip()

        # Format clean display city (e.g. Phuong Dinh Cong, Ha Noi)
        if locality and locality.lower() != subdivision.lower():
            display_city = f"{locality}, {subdivision}"
        elif city and city.lower() != subdivision.lower():
            display_city = f"{city}, {subdivision}"
        elif subdivision:
            display_city = subdivision
        else:
            display_city = city or 'Unknown'

        return {
            'lat': lat,
            'lon': lon,
            'city': display_city,
            'country': country,
            'countryCode': country_code,
            'source': 'wifi_wps'
        }
    except Exception:
        return {
            'lat': lat,
            'lon': lon,
            'city': 'Unknown',
            'country': 'Vietnam',
            'countryCode': 'VN',
            'source': 'wifi_wps'
        }


def main():
    bssid = get_connected_bssid()
    if not bssid:
        print(json.dumps({'error': 'no_bssid_detected'}))
        return

    coords = locate_via_apple_wps(bssid)
    if not coords:
        print(json.dumps({'error': 'bssid_not_found_in_wps'}))
        return

    lat, lon = coords
    result = reverse_geocode(lat, lon)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
