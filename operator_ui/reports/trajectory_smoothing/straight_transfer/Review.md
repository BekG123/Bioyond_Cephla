# Straight transfer: intermediate bends removed

**Offline candidate only. No movement has been commanded.**

Three continuous straight segments replace the curved transit. The two transitions between vertical and horizontal movement remain; this is not a continuous-velocity corner blend.

| Phase toward Hamilton | Target X | Target Y | Target Z | Rz |
|---|---:|---:|---:|---:|
| vertical_departure | 276.03 | 79.94 | 253.80 | 1.98° |
| straight_transfer | 195.34 | -360.31 | 253.80 | -1.90° |
| vertical_arrival | 195.34 | -360.31 | 48.61 | -1.90° |

Travel: **740.2 mm**, versus 1066.8 mm for the loop-pruned route (**30.6% shorter**). Full-segment IK passes in both directions. Saved Home is unchanged; endpoints are the taught Home-area and Hamilton points.

![Comparison](comparison.png)

## Required clearance review

- Straight transit at Z253.8 between the two station XY positions, including the complete arm, camera and gripper swept volume.
- Full Hamilton vertical column from Z48.61 to Z253.80; the taught route previously approached at roughly Z111 before lowering.
- Home-area vertical column from Z166.41 to Z253.80.

The chosen height comes from the recorded route, not an obstacle-height measurement. No fixture model establishes clearance along this new route. The original replay limits and permissions remain unchanged. This candidate exceeds the existing segment caps (the transit is about 448 mm and one vertical segment about 205 mm), so it is deliberately not executable through the current reviewed-route API.

[Three-segment coordinates and both-direction IK results](candidate.json)
