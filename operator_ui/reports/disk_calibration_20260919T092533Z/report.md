# Wide / Long two-disk calibration comparison

Offline replay of all 29 accepted captures. No hardware was connected and no configuration was changed.

| Measurement | Wide | Long |
|---|---:|---:|
| Median estimated distance | 206.464 mm | 211.994 mm |
| Estimated distance minimum | 204.517 mm | 209.995 mm |
| Estimated distance maximum | 207.949 mm | 213.519 mm |
| Distance standard deviation (not accuracy) | 0.852 mm | 0.875 mm |
| Same-origin distance span | 0.483 mm | 0.496 mm |
| Median XY alignment correction | 3.384 mm | 49.786 mm |
| Median yaw alignment correction | 0.212 deg | -27.082 deg |

![Comparison](comparison.png)

## Interpretation

Use Wide provisionally for the current taught viewing arrangement: the vendor selector chooses it on every recorded view. This does not establish its absolute distance accuracy.

Both share the same camera-to-tool and pixel-to-plane mapping. Long changes the distance scale and taught approach reference; these are not two independently calibrated depth sensors.

The estimated stationary plate location has 1.07 mm radial RMS scatter about its mean. Relative to recorded robot XY moves, the shared mapping has principal gains 0.897 and 0.888 (ideal 1.000), with a rotation mismatch magnitude of 15.41 degrees. This is a consistency diagnostic assuming a stationary plate, not an independent absolute position accuracy measurement. The current camera-to-robot mapping needs verification before precision pickup.

The 0.85 versus 0.87 mm distance standard deviations do not establish that Wide is more accurate: Long is simply scaled by its 2.68% larger reference radius.

A measured camera-to-plate distance and several independently known height changes are needed before either output becomes reference depth labels.

## First capture: directly comparable outputs

```json
{
  "index": 0,
  "sample": "20260919T000014_91c939227d",
  "pose": [
    303.289,
    20.513,
    286.304,
    0.0,
    0.0,
    9.94
  ],
  "offset_mm": [
    0,
    0
  ],
  "detection": {
    "mark": [
      1998.75,
      1239.0,
      7.473844790900765
    ],
    "big_r": 190.39999389648438,
    "small_r": 96.05000305175781,
    "big_c": [
      1695.75,
      1199.25
    ],
    "small_c": [
      2301.75,
      1278.75
    ]
  },
  "selected": "Wide",
  "rgb_sha256": "6cfab5111f35dcdf016d4387b8700663b3a2ba20692a01f65fe5637ec7094c7b",
  "detection_matches_saved": true,
  "settings": {
    "Wide": {
      "distance_mm": 204.99999999999963,
      "z_correction_mm": 1.9890719028385777e-13,
      "alignment_xy_mm": 0.7205689597230108,
      "alignment_yaw_deg": 0.03675984792769782,
      "mark_world_mm": [
        333.3919170388488,
        106.3613640653304,
        49.01706643976439
      ],
      "selection_score": {
        "cfg": "Wide",
        "err": 11.9,
        "px_dist": 11.7,
        "ang_diff": 0.04
      }
    },
    "Long": {
      "distance_mm": 210.49107817613228,
      "z_correction_mm": -5.491078176132272,
      "alignment_xy_mm": 49.785702448357206,
      "alignment_yaw_deg": -27.257192431509793,
      "mark_world_mm": [
        333.3919170388488,
        106.3613640653304,
        49.01706643976439
      ],
      "selection_score": {
        "cfg": "Long",
        "err": 547.3,
        "px_dist": 411.0,
        "ang_diff": 27.26
      }
    }
  }
}
```

## Full statistics

```json
{
  "created_utc": "2026-09-19T09:25:33.203334+00:00",
  "source_session": "C:\\Users\\Cephla\\Downloads\\Bioyond_Cephla\\Bioyond_Cephla\\operator_ui\\datasets\\depth\\plate_xy_20260918_v2",
  "captures": 29,
  "origin_captures": 2,
  "detection_reproduced_count": 29,
  "robot_z_mm": {
    "mean": 286.304,
    "median": 286.304,
    "std_population": 0.0,
    "minimum": 286.304,
    "maximum": 286.304,
    "span": 0.0
  },
  "robot_rz_deg": {
    "mean": 9.94,
    "median": 9.94,
    "std_population": 0.0,
    "minimum": 9.94,
    "maximum": 9.94,
    "span": 0.0
  },
  "large_radius_px": {
    "mean": 189.27758683829472,
    "median": 189.04998779296875,
    "std_population": 0.7825229870682658,
    "minimum": 187.70001220703125,
    "maximum": 190.85000610351562,
    "span": 3.149993896484375
  },
  "disk_yaw_deg": {
    "mean": 7.261671932890162,
    "median": 7.298639391740286,
    "std_population": 0.11929917151340141,
    "minimum": 6.898551996560613,
    "maximum": 7.473844790900765,
    "span": 0.575292794340152
  },
  "summary": {
    "Wide": {
      "reference_radius_px": 190.399993896484,
      "distance_mm": {
        "mean": 206.21916269607067,
        "median": 206.46390515255524,
        "std_population": 0.8520288534190227,
        "minimum": 204.51662300502394,
        "maximum": 207.94883436516412,
        "span": 3.4322113601401725
      },
      "origin_distance_mm": {
        "mean": 204.7583115025118,
        "median": 204.7583115025118,
        "std_population": 0.24168849748784282,
        "minimum": 204.51662300502394,
        "maximum": 204.99999999999963,
        "span": 0.48337699497568565
      },
      "z_correction_mm": {
        "mean": -1.1491318678707727,
        "median": -1.4639051525552147,
        "std_population": 0.8974722313710498,
        "minimum": -2.9488343651641005,
        "maximum": 0.2419737768956907,
        "span": 3.190808142059791
      },
      "alignment_xy_mm": {
        "mean": 3.402137313734735,
        "median": 3.3842789680390086,
        "std_population": 1.3794008507194206,
        "minimum": 0.7205689597230108,
        "maximum": 6.08250273642949,
        "span": 5.361933776706479
      },
      "alignment_yaw_deg": {
        "mean": 0.24893270593830838,
        "median": 0.21196524708818743,
        "std_population": 0.11929917151339979,
        "minimum": 0.03675984792769782,
        "maximum": 0.6120526422678552,
        "span": 0.5752927943401573
      },
      "selection_count": 29,
      "stationary_target_xy_rms_about_mean_mm": 1.0698831824812933,
      "stationary_target_xy_axis_span_mm": [
        3.076620577338076,
        2.940592301762422
      ]
    },
    "Long": {
      "reference_radius_px": 195.5,
      "distance_mm": {
        "mean": 211.74289705597673,
        "median": 211.99419512202996,
        "std_population": 0.8748510828943621,
        "minimum": 209.99475356716658,
        "maximum": 213.51889927313866,
        "span": 3.5241457059720744
      },
      "origin_distance_mm": {
        "mean": 210.24291587164942,
        "median": 210.24291587164942,
        "std_population": 0.2481623044828467,
        "minimum": 209.99475356716658,
        "maximum": 210.49107817613228,
        "span": 0.4963246089656934
      },
      "z_correction_mm": {
        "mean": -6.742897055976719,
        "median": -6.994195122029964,
        "std_population": 0.8748510828943645,
        "minimum": -8.518899273138647,
        "maximum": -4.994753567166573,
        "span": 3.5241457059720744
      },
      "alignment_xy_mm": {
        "mean": 49.79176585756887,
        "median": 49.785702448357206,
        "std_population": 2.490006548121768,
        "minimum": 44.43887090150226,
        "maximum": 54.60143031604474,
        "span": 10.162559414542478
      },
      "alignment_yaw_deg": {
        "mean": -27.04501957349921,
        "median": -27.08198703234939,
        "std_population": 0.11929917151339643,
        "minimum": -27.257192431509793,
        "maximum": -26.681899637169636,
        "span": 0.5752927943401573
      },
      "selection_count": 0,
      "stationary_target_xy_rms_about_mean_mm": 1.0698831824812933,
      "stationary_target_xy_axis_span_mm": [
        3.076620577338076,
        2.940592301762422
      ]
    }
  },
  "paired_long_minus_wide_mm": {
    "mean": 5.523734359906075,
    "median": 5.5302899694747225,
    "std_population": 0.022822229475339264,
    "minimum": 5.478130562142638,
    "maximum": 5.57006490797454,
    "span": 0.09193434583190196
  },
  "shared_xy_check": {
    "mapping_expected_identity": [
      [
        0.8593780078923156,
        -0.23296400423591782
      ],
      [
        0.24118678363764848,
        0.861221357429009
      ]
    ],
    "principal_gains": [
      0.896581229764962,
      0.8881543656623463
    ],
    "rotation_mismatch_deg": 15.406770837872253,
    "residual_rms_mm": 0.049257082331781596
  },
  "limitations": [
    "No independent absolute camera-to-plate distance labels.",
    "One physical setup, one Z and wrist angle; nearby XY views are correlated.",
    "Distance standard deviation measures consistency, not accuracy or true depth RMSE.",
    "Wide/Long selection uses image midpoint/yaw proximity to taught references, not measured depth error.",
    "XY consistency assumes the plate remained stationary and robot telemetry is reliable.",
    "Configured 205 mm plane is used for XY mapping in both settings.",
    "Z correction includes vendor half-gain when radius error is below one pixel.",
    "No robot movement, configuration changes, depth training, or label promotion."
  ]
}
```