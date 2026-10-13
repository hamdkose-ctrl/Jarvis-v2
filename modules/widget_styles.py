"""Bounded native drawing vocabulary shared by real widgets and source previews."""
import math

FAMILIES = {'wave', 'glass', 'orbit', 'neon', 'facet'}


def validate(spec):
    if not isinstance(spec, dict) or set(spec) != {'family', 'accent', 'background', 'amplitude', 'frequency', 'phase', 'radius'}:
        raise ValueError('Tasarım alanları geçersiz.')
    if spec['family'] not in FAMILIES:
        raise ValueError('Desteklenmeyen çizim ailesi.')
    for key in ('accent', 'background'):
        rgb = spec[key]
        if not isinstance(rgb, (list, tuple)) or len(rgb) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in rgb):
            raise ValueError('Geçersiz tasarım rengi.')
    for key, low, high in (('amplitude', 2, 12), ('frequency', 1, 5), ('phase', 0, 6.3), ('radius', 4, 28)):
        value = spec[key]
        if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError('Tasarım parametresi sınır dışında: '+key)
    return spec


def draw(d, x0, y0, x1, y1, cx, cy, R, u, t, col, speed, state, spec):
    validate(spec)
    family = spec['family']; accent = tuple(spec['accent']); bg = tuple(spec['background'])
    phase = spec['phase'] + (t * .7 if speed else 0)
    # State colors still convey listening/thinking/speaking. Idle uses the chosen accent.
    ink = col if state != 'idle' else accent
    width = x1-x0; height = y1-y0
    radius = int(min(spec['radius']*u, height/2))
    d.rounded_rectangle((x0,y0,x1,y1),radius=radius,fill=bg+(255,),outline=ink+(180,),width=max(1,int(u)))
    if family == 'wave':
        # Layered sine ribbons: a different silhouette around the left organic nucleus.
        for layer in range(4):
            points=[]
            for i in range(101):
                x=x0+3*u+(width-6*u)*i/100
                y=cy+math.sin(i/100*math.pi*spec['frequency']+phase+layer*.65)*spec['amplitude']*u
                y+= (layer-1.5)*2*u
                points.append((x,max(y0+3*u,min(y1-3*u,y))))
            strength=.18+layer*.08
            color=tuple(int(bg[j]*(1-strength)+ink[j]*strength) for j in range(3))
            d.line(points,fill=color+(255,),width=max(1,int((4-layer*.6)*u)),joint='curve')
        points=[]
        for i in range(81):
            a=i/80*2*math.pi
            r=R*(.79+.12*math.sin(a*spec['frequency']+phase))
            points.append((cx+math.cos(a)*r,cy+math.sin(a)*r))
        d.line(points,fill=ink+(255,),width=max(1,int(2*u)),joint='curve')
        d.ellipse((cx-4*u,cy-4*u,cx+4*u,cy+4*u),fill=ink+(255,))
    elif family == 'glass':
        # A drawn glass highlight, not actual desktop translucency.
        shine=tuple(min(255,v+25) for v in bg)
        d.rounded_rectangle((x0+3*u,y0+3*u,x1-3*u,cy),radius=max(1,radius//2),fill=shine+(255,))
        d.line((x0+radius,y0+3*u,x1-radius,y0+3*u),fill=(190,218,240,255),width=max(1,int(u)))
        d.ellipse((cx-R,cy-R,cx+R,cy+R),fill=ink+(255,))
        d.ellipse((cx-R*.65,cy-R*.65,cx+R*.65,cy+R*.65),fill=bg+(255,))
        d.ellipse((cx-3*u,cy-3*u,cx+3*u,cy+3*u),fill=(220,245,255,255))
    elif family == 'orbit':
        for index in range(3):
            r=R*(.65+index*.18)
            d.arc((cx-r,cy-r*.55,cx+r,cy+r*.55),index*80+phase*30,index*80+phase*30+250,fill=ink+(255,),width=max(1,int(1.5*u)))
        d.ellipse((cx-4*u,cy-4*u,cx+4*u,cy+4*u),fill=ink+(255,))
        d.line((cx+R+4*u,y1-5*u,x1-67*u,y1-5*u),fill=ink+(255,),width=max(1,int(u)))
    elif family == 'neon':
        for offset in range(3):
            tint=tuple(int(v*(.25+offset*.25)) for v in ink)
            d.rounded_rectangle((x0+(offset+1)*u,y0+(offset+1)*u,x1-(offset+1)*u,y1-(offset+1)*u),radius=radius,outline=tint+(255,),width=max(1,int(u)))
        for index in range(7):
            h=(3+abs(math.sin(index+phase))*spec['amplitude'])*u
            x=cx+(index-3)*3*u
            d.line((x,cy-h,x,cy+h),fill=ink+(255,),width=max(1,int(1.5*u)))
    else:
        points=[(cx+math.cos(i*math.pi/3+phase*.1)*R,cy+math.sin(i*math.pi/3+phase*.1)*R) for i in range(6)]
        d.polygon(points,fill=ink+(255,))
        d.polygon([(cx+(x-cx)*.7,cy+(y-cy)*.7) for x,y in points],fill=bg+(255,))
        d.line((x0+4*u,y1-4*u,x0+45*u,y1-4*u,x0+52*u,y1-10*u,x1-68*u,y1-10*u),fill=ink+(255,),width=max(1,int(u)))
