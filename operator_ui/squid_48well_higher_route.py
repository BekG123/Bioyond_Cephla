"""Exact raised-clearance candidate; original route evidence remains immutable."""
import hashlib,json
from projected_pickup import ROOT
from autonomy import TransferError
from scope_step_trial import near

SOURCE=ROOT/'operator_ui/reports/projected_alignment/squid_higher_retreat_20261027_queue_candidate.json'
SHA='017c7d1f8d110304aa54fc377534635849d1da07c2d130431b7515d90d1c734d'

def reference():
    raw=SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SHA:raise TransferError('Raised Squid route changed.')
    plan=json.loads(raw)
    return plan,plan['routes']['forward']

def validate_route(start,points,phase):
    plan,path=reference();recovery=plan['routes']['recovery_return']
    lifted={**path[-1],'Z':275.0}
    phases={'raised_recovery':(recovery[0],recovery[1:]),
            'raised_transit':(path[0],path[1:-1]),
            'raised_descent':(path[-2],path[-1:]),
            'raised_departure':(path[-1],[lifted]),
            'raised_return':(lifted,list(reversed(path[:-1])))}
    if phase not in phases:raise TransferError('Unknown raised Squid phase.')
    origin,targets=phases[phase]
    if points!=targets:raise TransferError('Exact raised Squid targets required.')
    near(start,origin,.05)
    return plan
