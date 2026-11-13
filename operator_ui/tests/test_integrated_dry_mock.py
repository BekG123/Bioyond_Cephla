import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import integrated_dry_mock_20261110 as m

class DryMockTests(unittest.TestCase):
    def setUp(self):m.configure_tip_site(7)
    def tearDown(self):m.configure_tip_site(7)
    def fixture(self):
        p=json.loads((m.OLD/'protocol.json').read_bytes())
        p['name']='DRY MOCK 48 WELL fixture'
        for row in p['deck']['positions']:
            if row['position']==3:row['position']=4
            elif row['position']==4:row['position']=3
            if row['position'] in m.LABWARE:
                lid,name,nr,nc=m.LABWARE[row['position']]
                row['labwareGroup']['labware'].update(id=lid,name=name,rows=nr,columns=nc)
        group=next(r['labwareGroup']['id'] for r in p['deck']['positions'] if r['position']==7)
        p['steps']=m.steps(p,group)
        return p

    def test_six_distinct_wells_correct_plate_and_tip_mapping(self):
        p=self.fixture();m.check(p)
        self.assertEqual([r['destinations'][0]['addresses'][0]['column'] for r in p['steps']],list(range(1,7)))

    def test_wrong_plate_site_or_liquid_detection_refused(self):
        for change in ('plate','site','detection','tipreuse','height'):
            p=self.fixture()
            if change=='plate':next(r for r in p['deck']['positions'] if r['position']==4)['labwareGroup']['labware']['rows']=4
            elif change=='site':p['steps'][0]['destinations'][0]['position']=3
            elif change=='detection':p['steps'][0]['aspirateSettings']['enableMad']=True
            elif change=='tipreuse':p['steps'][0]['newTipsEachTransfer']=False
            else:p['steps'][0]['dispenseSettings']['pipettingHeight']=-1
            with self.subTest(change=change),self.assertRaises(AssertionError):m.check(p)

    def test_unrelated_success_cannot_complete_this_simulation(self):
        result=json.loads((m.OLD/'result.json').read_bytes())
        with self.assertRaises(AssertionError):m.verify_result(result,'different-job',self.fixture())

    def test_site_six_uses_fresh_tip_group_and_distinct_evidence(self):
        p=self.fixture();old_out=m.OUT;m.configure_tip_site(6)
        for row in p['deck']['positions']:
            if row['position']==7:row['position']=6
            elif row['position']==6:row['position']=7
        m.check(p)
        self.assertNotEqual(m.OUT,old_out)
        self.assertEqual(m.TIP_SITE,6)

    def test_offsets_require_exact_per_well_binding_and_leave_source_unchanged(self):
        p=self.fixture()
        offsets=[dict(x=-8.4+i*.02,y=-2+i*.15) for i in range(6)]
        for row,offset in zip(p['steps'],offsets):
            row['dispenseSettings'].update(useOffset=True,offset=offset.copy())
        with self.assertRaises(AssertionError):m.check(p)
        m.check(p,dispense_offsets=offsets)
        p['steps'][0]['dispenseSettings']['offset']=offsets[1]
        with self.assertRaises(AssertionError):m.check(p,dispense_offsets=offsets)
        p['steps'][0]['dispenseSettings']['offset']=offsets[0]
        p['steps'][0]['aspirateSettings']['useOffset']=True
        with self.assertRaises(AssertionError):m.check(p,dispense_offsets=offsets)

    def test_vendor_invalid_protocol_never_passes_even_with_matching_offsets(self):
        p=self.fixture();p['isValid']=False
        offsets=[dict(x=-8,y=-1) for _ in range(6)]
        for row,offset in zip(p['steps'],offsets):
            row['dispenseSettings'].update(useOffset=True,offset=offset)
        with self.assertRaises(AssertionError):m.check(p,dispense_offsets=offsets)

if __name__=='__main__':unittest.main()
