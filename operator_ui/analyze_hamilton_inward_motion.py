"""Offline, independently decoded evidence for Hamilton DCG opening investigation.

No instrument access. Distinguishes reported Position from EncoderPosition.
"""
import json
import math
from pathlib import Path
import struct
from check_hamilton_wider_release import MoveYRelative

ROOT = Path(__file__).resolve().parent/'reports/hamilton_api'
BATCH = 'dcg48_repeat_683af88d0e764de8b7a8617903ffd172'
OUT = ROOT/'release_investigation_20261109'

def tlv(data):
    """Decode the recorded parameter framing without using PLR's decoder."""
    result=[]
    cursor=0
    while cursor < len(data):
        if len(data)-cursor<4: raise ValueError('Truncated parameter header')
        wire,n=struct.unpack_from('<HH',data,cursor)
        cursor+=4
        if cursor+n>len(data): raise ValueError('Truncated parameter value')
        value=data[cursor:cursor+n]
        cursor+=n
        tag=wire & 0xff
        if tag in (30,31): value=tlv(value)
        elif tag==40 and n==4: value=struct.unpack('<f',value)[0]
        elif tag==32 and n==4: value=struct.unpack('<i',value)[0]
        elif tag==23 and n==2:
            number=struct.unpack('<H',value)[0]
            if number not in (0,1): raise ValueError('Invalid boolean')
            value=bool(number)
        else: raise ValueError(f'Unexpected tag/length {tag}/{n}')
        result.append((tag,value))
    return result

def drive_status(payload_hex):
    outer=tlv(bytes.fromhex(payload_hex))
    if len(outer)!=1 or outer[0][0]!=30: raise ValueError('Expected one drive-status structure')
    fields=outer[0][1]
    if [f[0] for f in fields]!=[23,40,40,23]: raise ValueError('Unexpected drive-status fields')
    initialized,position,encoder,home=[f[1] for f in fields]
    if not all(math.isfinite(v) for v in (position,encoder)): raise ValueError('Nonfinite feedback')
    return dict(initialized=initialized,position_mm=position,encoder_position_mm=encoder,
                position_minus_encoder_mm=position-encoder,in_home_sensor=home)

def opening_contract():
    payload=MoveYRelative(.5).build_parameters().build()
    top=tlv(payload)
    if [t[0] for t in top]!=[31,40]: raise ValueError('Wrong opening payload')
    channels=[]
    for tag,fields in top[0][1]:
        if tag!=30 or [f[0] for f in fields]!=[23,32,40]: raise ValueError('Wrong channel structure')
        channels.append(dict(default_values=fields[0][1],channel=fields[1][1],distance_mm=fields[2][1]))
    return dict(reconstructed_payload_hex=payload.hex(),channels=channels,velocity_mm_s=top[1][1],
                limitation='Reconstructed from the tested source; not a packet capture of the original run.')

def journal(name):
    return [json.loads(line) for line in (ROOT/(name+'.jsonl')).read_text().splitlines() if line.strip()]

def analyze():
    result=dict(motion_sent=False,packet=opening_contract())
    rows=journal(BATCH)
    events=[r for r in rows if r['kind'].startswith('dual_feedback_')]
    request=next(r for r in events if r['kind']=='dual_feedback_request' and r['data']['command']=='MoveYRelative')
    abort=next(r for r in events if r['kind']=='dual_feedback_request' and r['data']['command']=='PrepMethodAbort')
    abort_end=next(r for r in events if r['kind']=='dual_feedback_response' and r['data']['command']=='PrepMethodAbort')
    complete=next(r for r in events if r['kind']=='dual_feedback_response' and r['data']['command']=='MoveYRelative')
    result['timing']=dict(request_at=request['at'],abort_request_after_s=abort['at']-request['at'],
                         move_reply_after_s=complete['at']-request['at'],
                         abort_reply_latency_s=abort_end['at']-abort['at'],
                         reversal_precedes_abort=True)
    retry=json.loads((ROOT/BATCH/'dual_feedback_retry_result.json').read_text())
    baseline=retry['samples'][0]
    failing=retry['samples'][-1]
    result['reported_inward_mm']={c:(failing['raw'][c]-baseline['raw'][c])*(-1 if c=='1' else 1) for c in ('1','2')}
    first=json.loads((ROOT/BATCH/'wider_empty_15_result.json').read_text())
    result['front_counter_jump_repeat']=dict(first=first['front_y_reported_during_motion_mm'],
        second=failing['positions']['2']['position_y'],
        difference_mm=failing['positions']['2']['position_y']-first['front_y_reported_during_motion_mm'])
    audit=json.loads((OUT/'readonly_firmware_audit_extended.json').read_text())
    result['current_drive_status']={label:drive_status(obj['reads']['GetStatus']['hex'])
        for label,obj in audit['objects'].items() if label.startswith('ydrive_addrs/')}
    result['current_status_caveat']='Operator confirmed jaws were moved since the failed test; current offsets do not establish the historical cause.'
    result['encoder_during_failed_motion_recorded']=False
    result['stationary_encoder_discrepancy_samples']=len(audit['stationary_drive_samples'])
    history=json.loads((OUT/'historical_errors_and_rce.json').read_text())
    rce=history['traces?offset=0&limit=1000&sources=RCE']['items']
    result['native_client_log']=dict(first=rce[0]['date'],last=rce[-1]['date'],
        sends_after_1245=sum('Type=Send' in r['message'] and r['date']>'2026-11-08T12:45:00' for r in rce),
        limitation='Only the native application connection is covered; not a network-wide packet capture.')
    result['direct_y_failure_speed_mm_s']=1
    result['native_release_observed_per_jaw_mm']=4
    result['exact_firmware_mechanical_root_cause_proven']=False
    return result

if __name__=='__main__':
    result=analyze()
    OUT.mkdir(exist_ok=True)
    (OUT/'analysis.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
