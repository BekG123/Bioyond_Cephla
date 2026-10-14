# Plate edge/corner image-only experiment

`plate_edges.py` has no robot imports or motion commands. It tests the user's
proposal to center the actual plate outline in the camera image, independently
of ArUco markers and the two calibration circles.

The detector uses contrast enhancement, Canny edges and closed quadrilateral
contours. For interrupted outlines (tabs/chamfers), it also fits four sides
from line segments. Every candidate must pass rectangular geometry, plausible
aspect ratio (1.15-2.3), image-boundary, and observed-edge support tests on ALL
four sides. Multiple distinct candidates are rejected as ambiguous. Corners
are fitted side intersections, not necessarily physical chamfer vertices.

The plate center is the intersection of its fitted diagonals. The image center
and axes define the desired view. Plate corners are NOT driven to the image
corners (that would change scale/fill the field of view). The reported angle
and correction are IMAGE coordinates, not robot wrist commands. Side-support
scores are fractions of supported edge samples, not detection probabilities.

The current camera snapshot was tested successfully with four fitted sides.
The initial closed-contour method alone did not work on the low-contrast
background. Its diagnostic overlay is `captures/plate_edges_preview.jpg`.
The plate is right/below image center, and its long axis slopes about 7.6
degrees in image coordinates. Right-side corners are close to the frame edge;
review the overlay before using it for any motion experiment.

Run from the project root:

```
py operator_ui/plate_edges.py operator_ui/captures/marker_id_check.jpg --output operator_ui/captures/plate_edges_preview.jpg
py -m unittest discover -s operator_ui/tests -p test_plate_edges.py -v
```

The detector itself remains image-only. The separately implemented Flask
`edge_center.py` sequence now uses it for guarded XY centering; see
`EDGE_CENTERING.md`. It does not replace grasp alignment or generate a grasp
target. Image-center alignment differs from the vendor's taught camera view.
Z/grasp depth, tool offset, joint limits, collision clearance and plate gripping
orientation remain separate requirements. The original detection experiment
did not command robot movement.
