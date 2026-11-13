"""A simple arm service: one plate between hotel slot 1 and the Squid microscope, held by the arm all the way.

It owns the robot connection while it runs (the controller accepts one client: the Lacry console must be closed).
The routes are the accepted taught routes, read from their files and checked against their acceptance pins; this
package only joins them and runs them. See routes.py for the two legs, motion.py for one move, service.py for a run.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATOR_UI = ROOT / "operator_ui"
if str(OPERATOR_UI) not in sys.path:
    sys.path.insert(0, str(OPERATOR_UI))  # the console's modules are used as a library; the console does not run
