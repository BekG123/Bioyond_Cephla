"""Save this inspected placement and its grip binding; no hardware commands."""
import json
import time
import accept_reseated_48well as acceptance
from projected_pickup import ROOT, load


def main():
    folder = ROOT / 'operator_ui/reports/projected_alignment'
    receipt = folder / 'squid_full7_20261027_reference.json'
    if receipt.exists():
        raise RuntimeError('Acceptance receipt already exists; inspect before retry.')
    original_save = acceptance.save
    acceptance.save = lambda name, data: original_save(name.replace('reseated_repeat1', 'full7_reseat'), data)
    acceptance.main()
    profile, digest = load()
    record = dict(at=time.time(), operator_request='yes, continue with gripping',
        source='operator_ui/reports/projected_alignment/full7_reseat_accepted_profile_20261027.json',
        source_sha256=digest, endpoint=profile['candidate_endpoint'], applied=True,
        basis='Operator inspected adjusted open-claw descent: even spacing and correct gripping height. Grip only; no lift.',
        hardware_commands_sent=False)
    with receipt.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, indent=2)
    print(json.dumps(dict(receipt=str(receipt), profile_sha256=digest)))


if __name__ == '__main__':
    main()
