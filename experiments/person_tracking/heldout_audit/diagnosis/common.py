import json, sys, hashlib
from pathlib import Path
import numpy as np
PT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PT))
import pilot as p
from meet2_audit.legacy_reader import ground_truth as legacy
CLIPS = [('LeftBag_BehindChair','lbbcgt.xml'), ('Walk1','wk1gt.xml'), ('Meet_WalkTogether2','mwt2gt.xml')]
MAN = json.loads((PT/'results_heldout_nano_576x768.json').read_text())
FROZEN = MAN['frozen']
W, H = 384, 288
def load(name, xml):
    video, x = p.RAW/(name+'.mpg'), p.ANNOTATIONS/xml
    for f in (video, x):
        assert hashlib.sha256(f.read_bytes()).hexdigest() == MAN['inputs'][f.name]['sha256'], f
    src = PT/'meet2_audit' if name=='Meet_WalkTogether2' else PT/'heldout_audit'
    det = json.loads((src/'detections_stride5_nano_576x768.json').read_text())[name]
    gt, bag = p.ground_truth(x)
    return video, x, gt, det
def iou_mat(A, B):
    A = np.asarray(A, float).reshape(-1,4); B = np.asarray(B, float).reshape(-1,4)
    ix = np.clip(np.minimum(A[:,None,2],B[None,:,2]) - np.maximum(A[:,None,0],B[None,:,0]),0,None)
    iy = np.clip(np.minimum(A[:,None,3],B[None,:,3]) - np.maximum(A[:,None,1],B[None,:,1]),0,None)
    inter = ix*iy
    aa = (A[:,2]-A[:,0])*(A[:,3]-A[:,1]); bb=(B[:,2]-B[:,0])*(B[:,3]-B[:,1])
    return inter/np.maximum(aa[:,None]+bb[None,:]-inter,1e-9)
