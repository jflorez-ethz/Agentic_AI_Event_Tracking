"""The eight annotated CAVIAR clips: three with a left object, five without (false alarm set)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW, ANNOTATIONS = ROOT / "data/raw", ROOT / "data/annotations"
TUNING = "LeftBag"
VIDEOS = [  # name, decoded source (PTS-clean), CAVIAR XML
    ("LeftBag", "LeftBag.mpg", "LeftBag.xml"),
    ("LeftBox", "LeftBox_pts.mkv", "LeftBox.xml"),
    ("LeftBag_PickedUp", "LeftBag_PickedUp.mpg", "lbpugt.xml"),
    ("Rest_FallOnFloor", "Rest_FallOnFloor.mpg", "Rest_FallOnFloor.xml"),
    ("Walk2", "Walk2.mpg", "wk2gt.xml"),
    ("TwoEnterShop1front", "TwoEnterShop1front_pts.mkv", "f2es1gt.xml"),
    ("Meet_WalkSplit", "Meet_WalkSplit_pts.mp4", "mws1gt.xml"),
    ("Meet_WalkTogether1", "Meet_WalkTogether1_pts.mp4", "Meet_WalkTogether1.xml"),
]
