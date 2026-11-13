import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diagnose_hamilton_dcg_empty import C,cases,z_command,analyze

class EmptyDiagnosticTests(unittest.TestCase):
    def test_no_low_plate_moves_or_drop_command(self):
        for name,steps in cases():
            for label,cmd in steps:
                cmd.build_parameters().build()
                self.assertNotIsInstance(cmd,C.PrepDropPlate)
                if isinstance(cmd,C.PrepMoveZAbsolute):self.assertTrue(all(150<=p.z_position<=160 for p in cmd.channels))
                if isinstance(cmd,C.PrepMoveToPosition):self.assertTrue(all(p.z_position==150 for p in cmd.move_parameters.axis_parameters))
                if isinstance(cmd,C.PrepPickUpPlate):self.assertEqual(cmd.grip_height,150)
    def test_only_comparison_case_releases_before_lift(self):
        for name,steps in cases():
            labels=[label for label,_ in steps]
            if name=='released_before_lift':self.assertLess(labels.index('release_at_150'),labels.index('slow_lift'))
            else:self.assertNotIn('release_at_150',labels)
    def test_rejects_low_diagnostic_z(self):
        with self.assertRaises(ValueError):z_command(20)
    def test_analysis_locates_first_closure(self):
        samples=[dict(phase='held/safe',spacing_mm=s,y_mm=[s,0],at=i,z_mm=[150+i]*2) for i,s in enumerate((101,101,90,35))]
        a=analyze(samples)[0]
        self.assertEqual(a['first_spacing_change']['at'],2)
        self.assertEqual(a['end_spacing_mm'],35)

if __name__=='__main__':unittest.main()
