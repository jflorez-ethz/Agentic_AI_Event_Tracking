from common import *
import subprocess, sys
from PIL import Image, ImageDraw
def frame(video, n):
    px = subprocess.check_output(['ffmpeg','-v','error','-i',str(video),'-fps_mode','passthrough','-vf',f'select=eq(n\\,{n})','-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'])
    return Image.frombytes('RGB',(W,H),px)
def sheet(name, xml, frames, out, tracks=None, scale=2):
    video,x,gt,det = load(name,xml)
    panels=[]
    for n in frames:
        im = frame(video,n).resize((W*scale,H*scale), Image.NEAREST); d = ImageDraw.Draw(im)
        S=lambda b:[v*scale for v in b]
        for b in det[str(n)]:
            if b[4]>=0.4: d.rectangle(S(b[:4]),outline=(0,255,0),width=2); d.text((b[0]*scale+2,b[3]*scale-10),f'{b[4]:.2f}',fill=(0,255,0))
            elif b[4]>=0.2: d.rectangle(S(b[:4]),outline=(255,80,80),width=1)
        for g in gt:
            if n in gt[g]: d.rectangle(S(gt[g][n]),outline=(255,255,0),width=2); d.text((gt[g][n][0]*scale+2,gt[g][n][1]*scale+2),f'X{g}',fill=(255,255,0))
        if tracks:
            for t,b in tracks.items():
                if n in b: d.rectangle(S(b[n]),outline=(0,200,255),width=1); d.text((b[n][2]*scale-20,b[n][1]*scale+2),f'T{t}',fill=(0,200,255))
        d.text((4,4),f'{name} frame {n}',fill=(255,255,255))
        panels.append(im)
    cols=min(3,len(panels)); rows=(len(panels)+cols-1)//cols
    S_=Image.new('RGB',(W*scale*cols,H*scale*rows))
    for i,im in enumerate(panels): S_.paste(im,((i%cols)*W*scale,(i//cols)*H*scale))
    S_.save(out)
if __name__=='__main__':
    name, xml = sys.argv[1], sys.argv[2]
    sheet(name, xml, [int(a) for a in sys.argv[4].split(',')], sys.argv[3])
