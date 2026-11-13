"""The production Cellvis motion must match the physically accepted run."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cellvis24_calibration as c
from autonomy import TransferError


class AcceptedSequenceTests(unittest.TestCase):
    def test_exact_successful_sequence_and_grip_preserved(self):
        steps=c.compile_steps()
        profile=json.loads(c.ACCEPTED_SEQUENCE.read_bytes())
        source=c.ROOT/profile['source_run']['path']
        if source.exists():self.assertEqual(steps,json.loads(source.read_bytes())['plan']['steps'])
        align=next(s for s in steps if s['kind']=='align')
        self.assertEqual(align['target'],dict(x=312.5,y=-66.3,rz=89.84,z_calibrated=75.72))
        self.assertEqual(align['translation_speed'],15)
        queues={s['label']:s for s in steps if s['kind']=='queue'}
        self.assertEqual(queues['Fast open-jaw approach']['speed'],137)
        self.assertEqual(queues['Fast open-jaw approach']['points'][-1]['Z'],95.72)
        self.assertEqual(queues['Final open-jaw descent']['speed'],5)
        self.assertEqual(queues['Final open-jaw descent']['points'][-1]['Z'],75.72)
        self.assertEqual([(s['target'],s['speed']) for s in steps if s['kind']=='jaws'],[(4.9,10),(3.9,5),(28,5)])
        self.assertEqual(queues['Proof lift 5 mm at speed 5']['points'][-1]['Z'],80.72)
        self.assertFalse(profile['camera_target_adaptation'])

    def test_caller_cannot_mutate_next_plan(self):
        first=c.compile_steps();first[2]['target']['x']=999
        self.assertEqual(c.compile_steps()[2]['target']['x'],312.5)

    def test_changed_profile_and_handling_geometry_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            changed=Path(tmp)/'profile.json';changed.write_bytes(c.ACCEPTED_SEQUENCE.read_bytes()+b' ')
            with patch.object(c,'ACCEPTED_SEQUENCE',changed),self.assertRaises(TransferError):c.compile_steps()
        from cellvis24_squid_route import geometry
        g=geometry();g['seat']['X']+=1
        with patch('cellvis24_squid_route.geometry',return_value=g),self.assertRaises(TransferError):c.compile_steps()


if __name__=='__main__':unittest.main()
