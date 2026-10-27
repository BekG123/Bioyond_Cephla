"""Offline 3MF metrology. Does not connect to the instrument or change the CAD."""
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import numpy as np

SOURCE = Path(r'C:\Users\Cephla\Downloads\hamilton_tip_pedestal_v2.3mf')
OUT = Path(__file__).parent / 'holder_cad_audit'
OUT.mkdir(exist_ok=True)
with zipfile.ZipFile(SOURCE) as archive:
    model = ET.fromstring(archive.read('3D/Objects/object_1.model'))
    assembly = ET.fromstring(archive.read('3D/3dmodel.model'))
    settings = json.loads(archive.read('Metadata/project_settings.config'))
    vertices = np.array([[float(v.attrib[k]) for k in 'xyz']
                         for v in model.findall('.//{*}vertex')])
    faces = np.array([[int(t.attrib[k]) for k in ('v1', 'v2', 'v3')]
                     for t in model.findall('.//{*}triangle')])
    transforms = [e.attrib.get('transform') for e in assembly.iter()
                  if e.tag.split('}')[-1] in ('component', 'item')]
assert model.attrib['unit'] == 'millimeter'
# Confirm this project's assembly applies translation only, not print scaling.
for transform in transforms:
    assert np.allclose(np.array(transform.split(), float)[:9].reshape(3, 3), np.eye(3))
vertices[:, 2] -= vertices[:, 2].min()
triangles = vertices[faces]
cross = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
area = np.linalg.norm(cross, axis=1)/2
horizontal = np.ptp(triangles[:, :, 2], axis=1) < 1e-5
surfaces = []
for z in np.unique(np.round(triangles[horizontal, 0, 2], 4)):
    keep = horizontal & np.isclose(triangles[:, 0, 2], z, atol=1e-4, rtol=0)
    if area[keep].sum() > 5:
        surfaces.append({'z_above_model_base_mm': float(z),
                         'area_mm2': float(area[keep].sum()),
                         'upward_area_mm2': float(area[keep & (cross[:, 2] > 0)].sum()),
                         'xy_bounds': [triangles[keep, :, :2].min(axis=(0, 1)).tolist(),
                                       triangles[keep, :, :2].max(axis=(0, 1)).tolist()]})

def section(axis, level):
    segments = []
    for tri in triangles:
        delta = tri[:, axis]-level
        if delta.min() >= 0 or delta.max() <= 0:
            continue
        points = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            if delta[a]*delta[b] < 0:
                points.append(tri[a]+(-delta[a]/(delta[b]-delta[a]))*(tri[b]-tri[a]))
        if len(points) == 2:
            segments.append(points)
    return np.array(segments)

def intercepts(segments, axis):
    other = 1-axis
    vals = []
    for a, b in segments:
        if a[other]*b[other] < 0:
            point = a + (-a[other]/(b[other]-a[other]))*(b-a)
            vals.append(point[axis])
    return sorted(set(round(float(v), 4) for v in vals))

levels = [0.1, 2, 5, 10, 30, 50, 55, 57, 58, 59, 60, 61, 61.49]
sections = []
for level in levels:
    seg = section(2, level)
    sections.append({'z_mm':level, 'x_intercepts_at_y0':intercepts(seg, 0),
                     'y_intercepts_at_x0':intercepts(seg, 1)})
result = {'source':str(SOURCE), 'units':'mm', 'assembly_transforms':transforms,
          'model_dimensions_xyz_mm':np.ptp(vertices, axis=0).tolist(),
          'horizontal_surfaces':surfaces, 'center_cross_sections':sections,
          'nominal_seating_comparison':{
              'pocket_envelope_xy_mm':[123.0,83.2],
              'vendor_frame_envelope_xy_mm':[122.4,82.6],
              'total_nominal_clearance_xy_mm':[0.6,0.6],
              'maximum_center_shift_per_axis_if_fully_seated_mm':0.3,
              'main_ledge_height_mm':57.5,
              'ledge_recess_below_holder_top_mm':4.0,
              'tip_rim_height_above_holder_base_if_frame_bottom_seated_mm':67.1,
              'tip_rim_height_derivation':'57.5 + 5.8 - 4.2 + (29.95 - 21.95)',
              'metal_to_holder_base_implied_by_75mm_tip_rim_mm':7.9,
              'physical_seating_and_base_elevation_verified':False,
              'caveat':'Vendor frame is a simplified envelope; printed dimensions, fit, tilt and contact must be checked.'},
          'slicer_settings':{k:settings[k] for k in ('filament_type','filament_shrink',
              'xy_contour_compensation','xy_hole_compensation','elefant_foot_compensation')},
          'limitations':['Dimensions describe CAD, not measured printed dimensions.',
                        'Installed base datum and rack contact surface remain unverified.',
                        'No motion target or printed-holder revision is approved by this audit.']}
(OUT/'dimensions.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

fig, axes = plt.subplots(2, 2, figsize=(13, 10), constrained_layout=True)
for ax, level in zip(axes[0], (57, 60)):
    seg = section(2, level)[:, :, :2]
    ax.add_collection(LineCollection(seg, colors='#176b94', linewidths=1))
    ax.set_title(f'Horizontal section: {level} mm above CAD base')
    ax.set_xlabel('Model X (mm)'); ax.set_ylabel('Model Y (mm)')
for ax, axis, label in zip(axes[1], (1, 0), ('X', 'Y')):
    # Cut away from the center finger notches to show the main support ledge.
    seg = section(axis, 20.013)[:, :, [1-axis, 2]]
    ax.add_collection(LineCollection(seg, colors='#176b94', linewidths=1))
    ax.set_title(f'Vertical section away from finger notch: {label} / Z')
    ax.set_xlabel(f'Model {label} (mm)'); ax.set_ylabel('Height above CAD base (mm)')
for ax in axes.flat:
    ax.autoscale(); ax.margins(.08); ax.set_aspect('equal'); ax.grid(alpha=.2)
fig.suptitle('Printed Hamilton holder: measured CAD sections\n127.76 × 85.48 × 61.50 mm; no assembly scaling',fontsize=16)
fig.savefig(OUT/'cad_sections.png', dpi=170)

# Separate schematic clearly distinguishes CAD facts from an assumed mating stack.
fig, ax = plt.subplots(figsize=(11, 7), constrained_layout=True)
ax.add_collection(LineCollection(section(1,20.013)[:, :, [0,2]], colors='#176b94', linewidths=1.5))
seat=57.5; frame_center=seat+5.8; hole=frame_center-4.2; rim=hole+8
ax.plot([-61.2,61.2,61.2,-61.2,-61.2],[seat,seat,seat+11.6,seat+11.6,seat],color='#d18c00',linestyle='--',label='Nominal frame envelope, assumed seated on ledge')
for x in np.arange(12)*9-49.5:
    ax.plot([x,x],[hole-51.9,rim],color='#4b5563',alpha=.45)
    ax.plot([x-3.4,x+3.4],[rim,rim],color='#167768',linewidth=2)
for z,label,color in [(0,'Holder base = 0','#176b94'),(57.5,'Support ledge = 57.5 mm','#176b94'),(61.5,'Holder top = 61.5 mm','#176b94'),(rim,'Inferred tip rim = 67.1 mm','#167768')]:
    ax.annotate(label,xy=(64,z),xytext=(76,z+(3 if z==rim else -2 if z==61.5 else 0)),color=color,va='center',arrowprops={'arrowstyle':'-','color':color})
ax.set_xlim(-75,125); ax.set_ylim(-5,80); ax.set_aspect('equal'); ax.grid(alpha=.2)
ax.set_xlabel('Model X (mm)');ax.set_ylabel('Height above printed holder bottom (mm)')
ax.set_title('Height reconciliation — an assumed seating stack, not a motion target\n75 mm measured above metal − 67.1 mm nominal stack = 7.9 mm implied base elevation')
ax.legend(loc='lower center',bbox_to_anchor=(.5,-.24))
fig.savefig(OUT/'seating_height_schematic.png',dpi=170)
print(json.dumps(result, indent=2))
