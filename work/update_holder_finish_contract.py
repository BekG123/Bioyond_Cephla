"""Update current workflow descriptions; leave trial evidence untouched."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
old='''session -> IDLE holding the plate -> HOME seated -> verify support -> release
-> lift 5 mm at speed 5 -> open E1 to 28 mm -> verify the full holder/plate/jaw
sweep -> orient -> verify three fresh E2 readings -> re-grip -> proof lift
-> accepted destination route.'''
new='''session -> grip -> lift 5 mm at speed 5 -> lower the same 5 mm at speed 5
into the unchanged HOME holder -> open E1 to 28 mm while seated -> raise the
EMPTY arm 30 mm at speed 137. Full calibration ends here, with no final IDLE
travel. Separately verify the full sweep -> orient -> verify three fresh E2
readings -> re-grip -> proof lift -> accepted destination route. The revised
calibration finish is implemented and offline-tested; its exact physical
trial is pending. Earlier 5 mm empty-clearance evidence is not that trial.'''
paths=[root/p for p in ('README.md','docs/DESIGN.md','docs/HANDOVER_OPERATOR_UI.md','operator_ui/lacry_prompt.txt')]
names=['full-calibration-skill-48-well-plate-v1','return-home-skill-v1','hamilton-squid-roundtrip-v1',
       'squid-closed-claw-transfer-v1','squid-dropoff-pickup-v1','two-station-plate-handling-v1','trajectory-deblur']
for name in names:
    paths.extend([root/'Codex SKILLS'/name/'SKILL.md',Path.home()/'.codex/skills'/name/'SKILL.md'])
for p in paths:
    if not p.exists(): continue
    text=p.read_text(encoding='utf-8')
    if old not in text: continue
    text=text.replace(old,new)
    if p.parent.name=='full-calibration-skill-48-well-plate-v1':
        text=text.replace('7. Check the grip and proof-lift results before loaded Home with `preserve_gripper=true`.',
            '7. Current full-calibration finish supersedes the historical loaded-Home wrappers: after the 5 mm proof lift, lower 5 mm at speed 5, verify the original holder seating pose and orientation, open E1 to 28 mm, and raise the EMPTY arm 30 mm at speed 137 using `PickupHolder`. No final IDLE travel or holder rotation. Keep historical trial wrappers unchanged and do not replay them as the new full-calibration finish.')
    p.write_text(text,encoding='utf-8')
    print(p)
p=root/'operator_ui/lacry_agent.py'
text=p.read_text(encoding='utf-8')
text=text.replace('Arm full calibration includes pickup and return Home and may occur once.',
    'Arm full calibration includes proof lift, reseating/release at HOME and empty 30 mm rise, and may occur once.')
text=text.replace('The arm routine includes pickup, slow lift and Home;',
    'The arm routine ends with the plate released at HOME and the empty arm raised 30 mm;')
text=text.replace('Preview the new once-per-session calibration, IDLE to HOME holder placement, release, 5 mm clearance, destination-specific orientation and re-grip.',
    'Preview once-per-session calibration ending with a 5 mm proof lift, reseating, release to 28 mm and empty 30 mm rise, followed by destination-specific orientation and re-grip.')
p.write_text(text,encoding='utf-8')
print(p)
