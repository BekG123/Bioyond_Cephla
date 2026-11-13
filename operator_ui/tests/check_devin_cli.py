"""Explicit live CLI smoke check. Uses Devin allowance; no project or hardware tools."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from devin_review import POLICY, find_cli, cli_environment
from developer_diagnostics import scrub


def main():
    executable = find_cli()
    if not executable:
        raise SystemExit('Devin executable not found.')
    folder = Path(os.environ['LOCALAPPDATA']) / 'Cephla' / 'DevinReview'
    folder.mkdir(parents=True, exist_ok=True)
    config = folder / 'review-config.json'
    config.write_text(json.dumps(POLICY, indent=2), encoding='utf-8')
    prompt = folder / 'connection-check.txt'
    prompt.write_text('Reply with exactly DEVIN_READY. Do not use any tools or access files.', encoding='utf-8')
    try:
        result = subprocess.run([executable, '--config', str(config), '--permission-mode', 'auto',
            '--respect-workspace-trust', 'true', '--prompt-file', str(prompt), '-p'],
            cwd=folder, stdin=subprocess.DEVNULL, capture_output=True, timeout=60, env=cli_environment(),
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        text = scrub((result.stdout + result.stderr).decode('utf-8', errors='replace'))
        passed = result.returncode == 0 and 'DEVIN_READY' in text
        print(json.dumps(dict(ok=passed, exit_code=result.returncode, output=text)))
        raise SystemExit(0 if passed else 1)
    finally:
        prompt.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
