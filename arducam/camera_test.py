"""Preview the Arducam feed and find its camera index.

Usage:
  python camera_test.py --list         # probe indices 0-5 and report which open
  python camera_test.py --camera 0     # live preview (q to quit)

Note: close the Windows Camera app first -- only one program can hold the
camera at a time.
"""

import argparse

import cv2


def probe(max_index: int = 6) -> None:
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok:
                h, w = frame.shape[:2]
                print(f"index {i}: OPEN  {w}x{h}")
            else:
                print(f"index {i}: opens but no frames")
            cap.release()
        else:
            print(f"index {i}: not available")


def preview(index: int, width: int, height: int) -> None:
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if not cap.isOpened():
        raise SystemExit(
            f"Could not open camera {index}. Close the Windows Camera app and retry, "
            "or run with --list to find the right index."
        )
    print("Previewing... press q to quit.")
    while True:
        ok, frame = cap.read()
        if not ok:
            print("Frame grab failed.")
            break
        cv2.imshow("Arducam preview", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="probe camera indices")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    args = ap.parse_args()
    if args.list:
        probe()
    else:
        preview(args.camera, args.width, args.height)
