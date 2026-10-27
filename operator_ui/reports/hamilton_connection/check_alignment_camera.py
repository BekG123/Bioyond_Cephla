"""Read-only status and camera capture; never moves or recalibrates Hamilton."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from PIL import Image

ROOT = Path(__file__).parent
BASE = 'http://192.168.100.101/NimbusLite/api/v1/'
opener = build_opener(ProxyHandler({}))
result = {'time': datetime.now(timezone.utc).isoformat(), 'read_only': True}
for endpoint in (
    'instruments/connection-info', 'instruments/global-run-state',
    'service-software-api/sensor-status', 'service-software-api/is-parked',
    'service-software-api/has-tips', 'errors/check-for-pending-errors',
    'deck/calibrate', 'camera/true', 'camera/calibration-pattern',
):
    try:
        with opener.open(BASE + endpoint, timeout=12) as response:
            data = response.read()
        if endpoint.startswith('camera/'):
            path = ROOT / ('restored_' + endpoint.replace('/', '_') + '.png')
            path.write_bytes(data)
            with Image.open(path) as frame:
                dimensions = frame.size
                frame.thumbnail((1400, 1100))
                frame.convert('RGB').save(path.with_suffix('.jpg'))
            result[endpoint] = {'file': str(path), 'dimensions': dimensions}
        else:
            result[endpoint] = json.loads(data) if data else None
    except HTTPError as error:
        result[endpoint] = {'status': error.code, 'error': error.read().decode(errors='replace')}
    except Exception as error:
        result[endpoint] = {'error': str(error)}
    print(json.dumps({endpoint: result[endpoint]})[:6000], flush=True)
    (ROOT / 'restored_holder_camera_status.json').write_text(
        json.dumps(result, indent=2), encoding='utf-8')
