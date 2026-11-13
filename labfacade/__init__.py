"""One interface for the Bioyond arm, the Hamilton Prep and the Squid microscope.

The agent gets a Facade: status, describe, run_step / run_operation, abort.
A person gets a HumanConsole: approve a plan, attest presence, confirm, resume.
The two are separate objects on purpose. See README.md and DESIGN.md.
"""
from .approval import HumanConsole, Signer, plan_hash
from .events import EventLog, RunFolder
from .facade import Facade
from .manifest import Manifest, Refusal, load_manifests

__version__ = '0.2.0'
__all__ = ['Facade', 'HumanConsole', 'Signer', 'RunFolder', 'EventLog', 'Manifest', 'Refusal',
           'load_manifests', 'plan_hash']
