"""User-dimensioned workcell layout. Offline only; no robot connection."""
import math
from pathlib import Path

from contact_sim import default_scene, read_json

DIMENSIONS = Path(__file__).with_name('workcell_dimensions.json')
MM_PER_INCH = 25.4


def measured_scene(path=DIMENSIONS):
    dimensions = read_json(path)
    if dimensions['units'] != 'inches':
        raise ValueError('Workcell measurements must be explicitly in inches')
    scene = default_scene()
    r, p = scene['rack'], scene['plate']
    measured, assumed = dimensions['rack'], dimensions['assumptions_mm']
    for key in ('outer_height', 'outer_width', 'outer_depth', 'shelf_width', 'shelf_depth', 'shelf_pitch'):
        value = measured[key]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid rack dimension: '+key)
        r['height_mm' if key == 'outer_height' else key+'_mm'] = value*MM_PER_INCH
    r.update(assumed['rack_pose'])
    r['shelf_count'] = assumed['shelf_count']
    for key in ('first_shelf_top','shelf_thickness','post_width','base_thickness','lip_height','lip_thickness'):
        r[key+'_mm'] = assumed[key]
    r['notes'] = 'User-measured exterior, shelves and spacing; unmeasured structural details: workcell_dimensions.json'
    p.update(length_mm=dimensions['calibration_plate']['length']*MM_PER_INCH,
             width_mm=dimensions['calibration_plate']['width']*MM_PER_INCH,
             height_mm=assumed['calibration_plate_thickness'], support_top_mm=assumed['calibration_plate_support_top'])
    placement = dimensions['calibration_plate_placement']
    if placement['long_edge'] != 'rack_width':
        raise ValueError('Specify the horizontal long edge relative to the rack width')
    if placement['side'] not in ('left', 'right'):
        raise ValueError('Plate side must be left or right when facing the rack')
    lateral = placement['lateral_gap']*MM_PER_INCH
    toward = placement['toward_arm']*MM_PER_INCH
    if placement['offset_reference'] == 'nearest_edges':
        # Independent clear gaps along the rack's width/depth axes.
        lateral += (r['outer_width_mm']+p['length_mm'])/2
        toward += (r['outer_depth_mm']+p['width_mm'])/2
    elif placement['offset_reference'] != 'centers':
        raise ValueError('offset_reference must be centers or nearest_edges')
    yaw = math.radians(r['rz'])
    right = lateral if placement['side'] == 'right' else -lateral
    p.update(x=r['x']+math.cos(yaw)*right+math.sin(yaw)*toward,
             y=r['y']+math.sin(yaw)*right-math.cos(yaw)*toward, yaw_deg=r['rz'])
    scene['measurements'] = dimensions
    scene['layout'] = dict(offset_reference=placement['offset_reference'], side=placement['side'],
        plate_rack_local_mm=[right,-toward], absolute_rack_pose_verified=False,
        placement_interpretation_confirmed=placement['interpretation_confirmed'])
    return scene
