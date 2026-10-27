"""Read saved, identical-path trials and plot observed traversal times. No robot I/O."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "demonstrations/return_path_trials_20261016_131713"
OUT = ROOT / "reports/trajectory_smoothing/speed_comparison"
TRIALS = [
    "50239_50407", "54961_55106", "55210_55355", "57862_57990",
    "58084_58211", "59988_60089", "60158_60260", "61675_61766",
    "61841_61932", "63245_63321", "63408_63484", "65856_65919", "66010_66071",
    "67055_67113", "67224_67282",
]
PATH_ID = "6d532ee8f22607688bee8943e05449415c7a0ad15c59a895f91cd3d251d3c420"


def main():
    rows = []
    for trial in TRIALS:
        filename = f"trial_{trial}.json"
        data = json.loads((DATA / filename).read_text(encoding="utf-8"))
        result = data["sequence"]["result"]
        assert result["ok"] and result["path_id"] == PATH_ID, filename
        assert data["invalid_samples"] == 0, filename
        rows.append(dict(speed=data["speed"], direction=result["direction"],
                         seconds=data["observed_duration_s"], trial=filename))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "comparison.json").write_text(json.dumps({
        "path_id": PATH_ID,
        "notes": "Single trial per speed and direction. Recorder task-window times include dispatch and completion detection. Controller feedback does not establish physical clearance or repeatability. No comparable reverse trial at speed 40.",
        "trials": rows,
    }, indent=2) + "\n", encoding="utf-8")
    fig, ax = plt.subplots(figsize=(9, 5.5), layout="constrained")
    for direction, label, marker in [
        ("to_hamilton", "Home-area → Hamilton", "o"),
        ("toward_home", "Hamilton → Home-area", "s"),
    ]:
        subset = sorted((r for r in rows if r["direction"] == direction), key=lambda r: r["speed"])
        ax.plot([r["speed"] for r in subset], [r["seconds"] for r in subset],
                marker=marker, label=label, linewidth=2, alpha=.85)
        if direction == "to_hamilton":
            for r in subset:
                ax.annotate(f'{r["seconds"]:.2f} s', (r["speed"], r["seconds"]),
                            xytext=(0, -20) if r["speed"] == 137 else (0, 10),
                            textcoords="offset points", ha="center")
    ax.set(title="Same taught path: measured speed versus time",
           xlabel="Commanded speed setting (mm/s)", ylabel="Observed traversal time (seconds)",
           xticks=[40, 47, 55, 70, 80, 100, 130, 137], ylim=(9, 38))
    ax.grid(alpha=.25)
    ax.legend()
    fig.suptitle("One trial per direction at each speed · unchanged Z212 / 3 mm entrance geometry", fontsize=10)
    fig.savefig(OUT / "speed_vs_time.png", dpi=180)
    plt.close(fig)
    print(json.dumps(rows, indent=2))
    print(OUT / "speed_vs_time.png")


if __name__ == "__main__":
    main()
