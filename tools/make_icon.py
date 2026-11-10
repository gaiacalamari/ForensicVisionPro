"""Disegna l'icona del programma (una foto con davanti una lente di ingrandimento) in src/fvp/ui/assets/fvp.ico.

Uso: python tools/make_icon.py
Serve solo Pillow. Il disegno è vettoriale-procedurale a 1024 px, poi ridotto a 16-256 px: lo script rende l'icona
riproducibile e modificabile senza programmi di grafica.
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "fvp" / "ui" / "assets" / "fvp.ico"
from PIL import Image, ImageDraw, ImageFilter
import math
S = 1024
def photo():
    # foto: cielo, sole, montagne, prato, cornice bianca, leggera rotazione
    w,h=660,520
    im=Image.new("RGBA",(w,h),(0,0,0,0)); d=ImageDraw.Draw(im)
    d.rounded_rectangle([0,0,w-1,h-1],radius=34,fill=(250,250,252,255))
    m=34; x0,y0,x1,y1=m,m,w-m,h-m
    sky=Image.new("RGBA",(x1-x0,y1-y0))
    sd=ImageDraw.Draw(sky)
    for y in range(y1-y0):
        t=y/(y1-y0)
        c=(int(70+(170-70)*t),int(140+(205-140)*t),int(220+(240-220)*t),255)
        sd.line([(0,y),(x1-x0,y)],fill=c)
    im.paste(sky,(x0,y0))
    d.ellipse([x1-190,y0+40,x1-90,y0+140],fill=(255,206,60,255))
    d.polygon([(x0,y1-120),(x0+170,y0+170),(x0+330,y1-120)],fill=(70,110,150,255))
    d.polygon([(x0+190,y1-110),(x0+380,y0+120),(x1,y1-110),(x1,y1)],fill=(52,92,128,255))
    d.polygon([(x0+380,y0+120),(x0+330,y0+185),(x0+360,y0+175),(x0+380,y0+200),(x0+405,y0+170),(x0+430,y0+185)],fill=(240,244,248,255))
    d.rectangle([x0,y1-120,x1,y1],fill=(78,160,90,255))
    d.polygon([(x0,y1-120),(x0+230,y1-150),(x1,y1-115),(x1,y1-100),(x0,y1-95)],fill=(98,178,104,255))
    mask=Image.new("L",(w,h),0); ImageDraw.Draw(mask).rounded_rectangle([x0,y0,x1,y1],radius=14,fill=255)
    frame=Image.new("RGBA",(w,h),(0,0,0,0)); ImageDraw.Draw(frame).rounded_rectangle([0,0,w-1,h-1],radius=34,fill=(250,250,252,255))
    frame.paste(im,(0,0),mask)
    return frame
img=Image.new("RGBA",(S,S),(0,0,0,0))
p=photo().rotate(-8,resample=Image.BICUBIC,expand=True)
# ombra della foto
sh=Image.new("RGBA",p.size,(0,0,0,0)); sh.putalpha(p.split()[3].point(lambda a: int(a*0.35)))
sh=sh.filter(ImageFilter.GaussianBlur(18))
px,py=40,70
img.alpha_composite(sh,(px+14,py+22)); img.alpha_composite(p,(px,py))
# lente
cx,cy,R=560,470,215
lens=Image.new("RGBA",(S,S),(0,0,0,0)); ld=ImageDraw.Draw(lens)
# manico
ang=math.radians(45); L0,L1=R+40,R+250
hw=52
def seg(a,b,wid,col):
    x0,y0=cx+a*math.cos(ang),cy+a*math.sin(ang); x1,y1=cx+b*math.cos(ang),cy+b*math.sin(ang)
    ld.line([(x0,y0),(x1,y1)],fill=col,width=wid)
    ld.ellipse([x1-wid/2,y1-wid/2,x1+wid/2,y1+wid/2],fill=col)
seg(R-10,R+70,70,(70,74,82,255))
seg(R+60,L1,hw*2,(38,52,78,255))
seg(R+70,L1-8,hw*2-30,(58,78,112,255))
# ombra lente
shl=Image.new("RGBA",(S,S),(0,0,0,0)); ImageDraw.Draw(shl).ellipse([cx-R+18,cy-R+28,cx+R+18,cy+R+28],fill=(0,0,0,90))
shl=shl.filter(ImageFilter.GaussianBlur(20))
img.alpha_composite(shl)
img.alpha_composite(lens)
# vetro: ingrandimento della foto sotto
glass=img.crop((cx-R,cy-R,cx+R,cy+R)).resize((2*R,2*R))
zoom=img.crop((int(cx-R*0.62),int(cy-R*0.62),int(cx+R*0.62),int(cy+R*0.62))).resize((2*R,2*R),Image.BICUBIC)
gm=Image.new("L",(2*R,2*R),0); ImageDraw.Draw(gm).ellipse([0,0,2*R-1,2*R-1],fill=255)
tint=Image.new("RGBA",(2*R,2*R),(200,225,255,40))
zoom.alpha_composite(tint)
img.paste(zoom,(cx-R,cy-R),gm)
d=ImageDraw.Draw(img)
# riflesso
hl=Image.new("RGBA",(S,S),(0,0,0,0)); hd=ImageDraw.Draw(hl)
hd.arc([cx-R+45,cy-R+45,cx+R-45,cy+R-45],start=200,end=265,fill=(255,255,255,170),width=26)
hl=hl.filter(ImageFilter.GaussianBlur(3)); img.alpha_composite(hl)
# montatura
d.ellipse([cx-R,cy-R,cx+R,cy+R],outline=(38,52,78,255),width=56)
d.ellipse([cx-R+20,cy-R+20,cx+R-20,cy+R-20],outline=(80,104,146,255),width=10)

bb=img.getbbox(); side=max(bb[2]-bb[0],bb[3]-bb[1]); pad=int(side*0.03); side+=2*pad
sq=Image.new("RGBA",(side,side),(0,0,0,0)); sq.alpha_composite(img.crop(bb),((side-(bb[2]-bb[0]))//2,(side-(bb[3]-bb[1]))//2))
img=sq.resize((S,S),Image.LANCZOS)
pass
sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)]
OUT.parent.mkdir(parents=True, exist_ok=True); img.resize((256,256),Image.LANCZOS).save(OUT,sizes=sizes)
