"""Read-only connection check for the operator-confirmed Microlab Prep."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

BASE_URL = 'http://192.168.100.101/NimbusLite/api/v1'
ENDPOINTS = (
    'software-versions',
    'instruments/connection-status',
    'instruments/connection-info',
    'instruments/get-active-system',
    'instruments/global-run-state',
    'system-ready',
    'protocols/names',
)


def main():
    opener = build_opener(ProxyHandler({}))
    result = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'model': 'Hamilton Microlab Prep 2 Channel',
        'reference': '6600200-02',
        'internal_pc': '192.168.100.101',
        'controller_board': '192.168.100.102',
        'base_url': BASE_URL,
        'read_only': True,
        'responses': {},
    }
    for endpoint in ENDPOINTS:
        request = Request(BASE_URL + '/' + endpoint,
                          headers={'Accept': 'application/json'}, method='GET')
        try:
            with opener.open(request, timeout=5) as response:
                body = response.read().decode('utf-8')
                try:
                    value = json.loads(body)
                except ValueError:
                    value = body
                result['responses'][endpoint] = {'status': response.status, 'data': value}
        except HTTPError as error:
            result['responses'][endpoint] = {'status': error.code, 'error': error.reason}
        except (URLError, TimeoutError, OSError) as error:
            result['responses'][endpoint] = {'error': str(error)}
    output = Path(__file__).with_name('live_status.json')
    output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
