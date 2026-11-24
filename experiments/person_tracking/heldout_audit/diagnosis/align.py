from common import *
import subprocess, xml.etree.ElementTree as ET
for name, xml in CLIPS:
    video, x, gt, det = load(name, xml)
    times = p.pts_times(str(video))
    d = np.diff(times)
    xf = [int(f.attrib['number']) for f in ET.parse(x).getroot().findall('frame')]
    old,_ = legacy(x)
    nb = sum(len(b) for b in gt.values())
    moved = [np.hypot(*np.subtract(p.center(gt[g][n]), p.center(old[g][n]))) for g in gt for n in gt[g]]
    print(f"{name}: decoded {len(times)} frames, PTS0={times[0]:.4f}, dt min/median/max={d.min():.4f}/{np.median(d):.4f}/{d.max():.4f}; "
          f"XML frames {min(xf)}..{max(xf)} ({len(xf)} entries, {len(set(xf))} unique); det frames {len(det)} (stride 5 up to {max(map(int,det))}); "
          f"person boxes {nb}; legacy-reader centre shift median {np.median(moved):.1f}px max {max(moved):.1f}")
