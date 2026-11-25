"""mbot2-drift-racer: drive an mBot2 like an RC race car from a phone, with a drift mode.

The CyberPi runs its own Wi-Fi hotspot and a tiny web server. The phone loads a
touch controller from it, sends the stick positions several times a second, and
plays the engine, exhaust and horn sounds itself.

Setup
    1. Set ROBOT_WIFI_PASS below (8+ characters).
    2. Upload with mBlock 5: Python editor -> Upload mode. Power-cycle the robot
       afterwards for a clean start.
    3. Join the Wi-Fi shown on the CyberPi screen.
    4. Open http://192.168.4.1 on the phone, turn it sideways, tap to start.
       On iPhone: Share -> Add to Home Screen for full screen.

Controls
    Left stick   throttle (forward / reverse)
    Right stick  steering
    BRAKE / BOOST / HORN buttons, DRIFT toggle, settings (gear) for speed,
    steering stiffness, volume, auto-brake and sound.

Drift mode
    With DRIFT on, steer hard while moving forward. The inner wheel kicks
    backwards briefly to break the rear loose (flick), then the robot holds the
    slide while you keep steering. Afterwards the phone shows the gyro rotation
    versus the rotation the wheel speeds predict; the difference is the slip.
    Smooth tape on the tires and a smooth floor help it slide.

Lights (CyberPi LEDs)
    driving: white (boost: bright) | turning: amber signal on that side |
    braking: red | reversing: flashing yellow/white | idle: dim amber | off: no phone

Safety
    Auto-brake stops the robot before it hits something (earlier at higher
    speed). The robot also stops if the phone stops sending for FAILSAFE_MS.

License: MIT
"""

import cyberpi
import mbot2
import time

try:
    import usocket as socket
except ImportError:
    import socket

try:
    import mbuild
    US = mbuild.ultrasonic2
except Exception:
    US = getattr(cyberpi, "ultrasonic2", None)

# =============================================================================
# SETTINGS
# =============================================================================

# --- Network ---
ROBOT_WIFI_NAME = "Mbot-Racer"
ROBOT_WIFI_PASS = "change-me-123"   # change this (8+ characters)

# --- Motor direction ---
FLIP_RIGHT = True     # set False if the robot spins in circles when driving straight
FLIP_LEFT = False     # set True if it drives backwards when you push the stick up

# --- Safety and auto-brake ---
FAILSAFE_MS = 700       # stop if the phone is silent this long (ms)
STOP_CM = 8             # base stopping distance (cm)
STOP_PER_POWER = 0.17   # extra cm per % of power (faster = brakes earlier)
BRAKE_HITS = 2          # consecutive close readings needed to brake (filters glitches)
RELEASE_CM = 6          # must be this much further than the limit before releasing

# --- Lights ---
BRAKE_LIGHT_MS = 600    # how long the brake light stays on after you let go (ms)
FLIP_SIGNALS = False    # set True if the turn signal blinks on the wrong side

# --- Speedometer (phone estimate, not measured) ---
WHEEL_CM = 6.5          # wheel diameter (cm)
MAX_RPM = 255           # motor speed at full power with the wheels in the air

# --- Drift ---
DRIFT_ENTER = 60          # steering (%) needed while moving to start a drift
DRIFT_HOLD = 35           # keep steering above this (%) to hold the slide
DRIFT_MIN_THROTTLE = 40   # forward throttle (%) needed to start a drift
FLICK_MS = 150            # how long the inner wheel kicks backwards (ms)
SLIDE_INNER = 20          # inner wheel power while sliding (lower = tighter; may be negative)
GYRO_ASSIST = True        # use the gyro to hold a steady spin rate during the slide
TARGET_YAW = 320          # spin rate (deg/s) at full steering when GYRO_ASSIST is on
ASSIST_GAIN = 0.15        # how hard the gyro assist corrects
TRACK_CM = 11.6           # distance between the centres of the two tires (cm)

# --- Eyes (ultrasonic sensor LEDs) ---
EVIL_EYES = True
# Brightness 0-100 for LEDs 1-8. If the "scowl" looks wrong, reorder the values
# to match how the LEDs are numbered on your sensor.
EYE_MEAN = (40, 0, 100, 100, 0, 40, 100, 100)          # normal: inner-top dark
EYE_SLIT = (0, 0, 100, 100, 0, 0, 100, 100)            # braking: narrowed
EYE_RAGE = (100, 100, 100, 100, 100, 100, 100, 100)    # boost: full

# =============================================================================
# TIME HELPERS
# =============================================================================

try:
    ticks = time.ticks_ms
    diff = time.ticks_diff
except AttributeError:
    ticks = lambda: int(time.time() * 1000)
    diff = lambda a, b: a - b


def sleep_ms(ms):
    try:
        time.sleep_ms(ms)
    except AttributeError:
        time.sleep(ms / 1000)


# =============================================================================
# PHONE CONTROLLER (served to the phone; runs entirely in its browser)
# =============================================================================
# Kept free of comments where possible: this text lives in the robot's RAM.
# Placeholders __WHEEL__ and __RPM__ are filled in below.

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Drift Racer">
<link rel="manifest" href="/m.json">
<title>Mbot Drift Racer</title><style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;height:100%;background:#080c18;color:#e6ebff;font-family:system-ui,-apple-system,sans-serif;overflow:hidden;overscroll-behavior:none;user-select:none;-webkit-user-select:none;-webkit-touch-callout:none;-webkit-text-size-adjust:100%}
body{position:fixed;inset:0}
.z{position:fixed;top:0;bottom:0;width:50%;touch-action:none;overflow:hidden}
#L{left:0;background:radial-gradient(circle at 50% 62%,#111a33,transparent 60%)}
#R{right:0;background:radial-gradient(circle at 50% 62%,#111a33,transparent 60%)}
.b{position:absolute;border:3px solid #38bdf899;background:#38bdf812;opacity:.35;pointer-events:none}
.b.on{opacity:1}
.b.y{width:124px;height:270px;margin:-135px 0 0 -62px;border-radius:62px}
.b.x{width:270px;height:124px;margin:-62px 0 0 -135px;border-radius:62px}
.k{position:absolute;left:50%;top:50%;width:96px;height:96px;border-radius:50%;background:#38bdf8;transform:translate(-50%,-50%);box-shadow:0 6px 20px #000a}
.lab{position:absolute;bottom:max(10px,env(safe-area-inset-bottom));left:0;right:0;text-align:center;font-size:11px;letter-spacing:2px;color:#5d6890;pointer-events:none}
#hud{position:fixed;top:max(6px,env(safe-area-inset-top));left:50%;transform:translateX(-50%);text-align:center;pointer-events:none;z-index:3}
#mph{font-size:46px;font-weight:800;font-variant-numeric:tabular-nums;line-height:1}
#mph small{font-size:14px;font-weight:700;color:#8a94b8;margin-left:4px}
#bar{width:180px;height:6px;border-radius:3px;background:#1c2440;margin:6px auto 4px;overflow:hidden}
#fill{height:100%;width:0;background:linear-gradient(90deg,#38bdf8,#f97316)}
#st{font-size:11px;color:#f87171}#st.ok{color:#4ade80}
#dg{font-size:10px;color:#5d6890;margin-top:2px;font-variant-numeric:tabular-nums}
#ab{display:none;margin-top:4px;font-weight:800;color:#f87171;font-size:13px;letter-spacing:1px}
body.blk{box-shadow:inset 0 0 0 4px #f87171}
.btn{position:fixed;z-index:6;pointer-events:auto;border-radius:50%;font:inherit;font-weight:800;font-size:14px;letter-spacing:.5px;color:#e6ebff;border:2px solid #26304f;background:#151c33;touch-action:manipulation;-webkit-appearance:none;appearance:none;padding:0}
.btn.h{filter:brightness(1.5);transform:scale(.94)}
#gear{left:max(16px,env(safe-area-inset-left));top:max(16px,env(safe-area-inset-top));width:56px;height:56px;font-size:22px}
#dft{left:calc(max(16px,env(safe-area-inset-left)) + 68px);top:max(10px,env(safe-area-inset-top));width:84px;height:84px;font-size:14px}
#dft.on{background:#f97316;border-color:#f97316;color:#1a0b00;box-shadow:0 0 18px #f97316aa}
#dr{font-size:12px;color:#fbbf24;margin-top:3px;font-weight:700;font-variant-numeric:tabular-nums}
body.drifting #dr{color:#f97316}
#bst{right:max(16px,env(safe-area-inset-right));top:max(16px,env(safe-area-inset-top));width:104px;height:104px;background:#f97316;border-color:#f97316;color:#1a0b00}
#hrn{right:calc(max(16px,env(safe-area-inset-right)) + 116px);top:max(22px,env(safe-area-inset-top));width:80px;height:80px}
#brk{right:max(16px,env(safe-area-inset-right));bottom:max(16px,env(safe-area-inset-bottom));width:108px;height:108px;background:#3a1420;border-color:#f87171;font-size:15px}
#set{position:fixed;inset:0;z-index:9;background:#080c18ee;display:none;align-items:center;justify-content:center}
#set.on{display:flex}
.pn{background:#151c33;border:1px solid #26304f;border-radius:16px;padding:16px 18px;width:min(460px,90vw);display:flex;flex-direction:column;gap:12px;font-size:15px}
.row{display:flex;align-items:center;gap:10px}.row input{flex:1;accent-color:#38bdf8;touch-action:auto}
.row b{min-width:44px;text-align:right}
.tg{font:inherit;font-weight:700;padding:10px;border-radius:10px;border:1px solid #26304f;background:#0b1020;color:#e6ebff;touch-action:manipulation;-webkit-appearance:none;appearance:none}
.tg.on{background:#38bdf8;color:#04121d;border-color:#38bdf8}
.hint{font-size:12px;color:#8a94b8;line-height:1.4}
#go{position:fixed;inset:0;z-index:10;background:#080c18;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;text-align:center;padding:20px;touch-action:manipulation}
#go h1{margin:0;font-size:30px}#go .big{font-size:20px;font-weight:800;color:#38bdf8}
#rot{position:fixed;inset:0;z-index:11;background:#080c18;display:none;align-items:center;justify-content:center;font-size:20px;font-weight:700}
@media (orientation:portrait){#rot{display:flex}}
</style></head><body>
<div class="z" id="L"><div class="lab">THROTTLE</div></div>
<div class="z" id="R"><div class="lab">STEER</div></div>
<div id="hud"><div id="mph">0.00<small>MPH</small></div><div id="bar"><div id="fill"></div></div>
<div id="st">&#9679; offline</div><div id="dr">Tap DRIFT, then steer hard while moving</div><div id="dg"></div><div id="ab">AUTO-BRAKE</div></div>
<button class="btn" id="gear">&#9881;</button><button class="btn" id="dft">DRIFT<br>off</button>
<button class="btn" id="hrn">HORN</button><button class="btn" id="bst">BOOST</button>
<button class="btn" id="brk">BRAKE</button>
<div id="set"><div class="pn">
<div class="row">Speed <input id="sp" type="range" min="20" max="100" step="5"><b id="spv"></b></div>
<div class="row">Steering <input id="se" type="range" min="15" max="100" step="5"><b id="sev"></b></div>
<div class="row">Volume <input id="vo" type="range" min="0" max="100" step="5"><b id="vov"></b></div>
<div class="row"><button class="tg" id="au">Auto-brake</button><button class="tg" id="sn">Engine sound</button><button class="tg" id="cl" style="margin-left:auto">Done</button></div>
<div class="hint">Lower Steering = stiffer turning. Speed is estimated from throttle.<br>Full screen on iPhone: Share &#8679; &rarr; Add to Home Screen, then open it from your home screen.</div>
</div></div>
<div id="go"><h1>MBOT<br>DRIFT RACER</h1><div class="big">TAP TO START ENGINE</div><div class="hint" id="ios"></div></div>
<div id="rot">Turn your phone sideways &#8635;</div>
<script>
['gesturestart','gesturechange'].forEach(function(t){document.addEventListener(t,function(e){e.preventDefault()},{passive:false})});
document.addEventListener('touchmove',function(e){if(e.touches.length>1)e.preventDefault()},{passive:false});
document.addEventListener('dblclick',function(e){e.preventDefault()},{passive:false});
var $=function(i){return document.getElementById(i)};
function ls(k,d){try{var v=localStorage.getItem('mdr'+k);return v===null?d:v}catch(e){return d}}
function ss(k,v){try{localStorage.setItem('mdr'+k,v)}catch(e){}}
var WHEEL=__WHEEL__,MAXMPH=__RPM__*Math.PI*WHEEL*60/100/1609.34;
var spd=+ls('sp',60),sens=+ls('se',60),vol=+ls('vo',80),auto=ls('au','1')==='1',snd=ls('sn','1')==='1';
var boost=0,brake=0,blocked=0,mph=0,rtt=0;

/* Touch stick: ax 'y' = vertical (throttle), 'x' = horizontal (steering); value -100..100 */
function Stick(z,ax,hy){var s=this;s.v=0;var b=document.createElement('div');b.className='b '+ax;var k=document.createElement('div');k.className='k';b.appendChild(k);z.appendChild(b);
 var id=null,o=0,r,R=86;function home(){var q=z.getBoundingClientRect();b.style.left=q.width/2+'px';b.style.top=q.height*hy+'px'}
 function up(e){var d=ax=='y'?e.clientY-r.top-o:e.clientX-r.left-o;if(d>R)d=R;if(d<-R)d=-R;
  k.style.transform=ax=='y'?'translate(-50%,calc(-50% + '+d+'px))':'translate(calc(-50% + '+d+'px),-50%)';
  s.v=Math.round(ax=='y'?-d/R*100:d/R*100);kick()}
 z.addEventListener('pointerdown',function(e){if(id!==null)return;id=e.pointerId;try{z.setPointerCapture(id)}catch(_){}r=z.getBoundingClientRect();
  o=ax=='y'?e.clientY-r.top:e.clientX-r.left;b.style.left=(e.clientX-r.left)+'px';b.style.top=(e.clientY-r.top)+'px';b.classList.add('on');up(e)});
 z.addEventListener('pointermove',function(e){if(e.pointerId===id)up(e)});
 function end(e){if(e.pointerId!==id)return;id=null;s.v=0;k.style.transform='translate(-50%,-50%)';b.classList.remove('on');home();kick()}
 z.addEventListener('pointerup',end);z.addEventListener('pointercancel',end);addEventListener('resize',home);home()}
var TH=new Stick($('L'),'y',0.6),SR=new Stick($('R'),'x',0.5);

/* ---- Sound: synthesized in the browser (Web Audio). Plays with the iPhone silent switch on. ---- */
var ac=null,master,fxm,eg,o1,o2,o3,fl,lfo,lg,lfo2,lg2,sc,sg,sf,tw,tg,noise=null,hr=null,spool=0;
function silentWav(){var n=8000,b=new ArrayBuffer(44+n),v=new DataView(b),i,w=function(o,s){for(i=0;i<s.length;i++)v.setUint8(o+i,s.charCodeAt(i))};
 w(0,'RIFF');v.setUint32(4,36+n,true);w(8,'WAVE');w(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);
 v.setUint32(24,8000,true);v.setUint32(28,8000,true);v.setUint16(32,1,true);v.setUint16(34,8,true);w(36,'data');v.setUint32(40,n,true);
 for(i=0;i<n;i++)v.setUint8(44+i,128);return URL.createObjectURL(new Blob([b],{type:'audio/wav'}))}
function osc(type,f){var o=ac.createOscillator();o.type=type;o.frequency.value=f;o.start();return o}
function gain(v,to){var g=ac.createGain();g.gain.value=v;if(to)g.connect(to);return g}
function unlock(){
 try{if(navigator.audioSession)navigator.audioSession.type='playback'}catch(e){}
 try{var a=document.createElement('audio');a.setAttribute('playsinline','');a.loop=true;a.src=silentWav();var p=a.play();if(p&&p.catch)p.catch(function(){})}catch(e){}
 var A=window.AudioContext||window.webkitAudioContext;if(!A)return;
 if(ac){if(ac.state!=='running')ac.resume();return}
 ac=new A();
 var comp=ac.createDynamicsCompressor();comp.threshold.value=-18;comp.ratio.value=4;comp.connect(ac.destination);
 master=gain(vol/100,comp);
 var lim=ac.createDynamicsCompressor();lim.threshold.value=-1;lim.ratio.value=20;lim.attack.value=0.001;lim.release.value=0.15;lim.connect(ac.destination);
 var grit=ac.createWaveShaper(),cv=new Float32Array(1024);for(var k=0;k<1024;k++){var xx=k/511.5-1;cv[k]=Math.tanh(2.5*xx)}grit.curve=cv;grit.connect(lim);
 fxm=gain(vol/100,grit);
 eg=gain(0,master);fl=ac.createBiquadFilter();fl.type='lowpass';fl.Q.value=3;fl.frequency.value=1400;fl.connect(eg);
 o1=osc('sawtooth',105);o2=osc('square',52);o3=osc('sawtooth',210);
 o1.connect(fl);o2.connect(gain(0.3,fl));o3.connect(gain(0.3,fl));
 lfo=osc('sine',9);lg=gain(0);lfo.connect(lg);lg.connect(eg.gain);
 lfo2=osc('triangle',4.3);lg2=gain(0);lfo2.connect(lg2);lg2.connect(eg.gain);
 sg=gain(0,master);sf=ac.createBiquadFilter();sf.type='bandpass';sf.Q.value=2.5;sf.connect(sg);sc=osc('sawtooth',800);sc.connect(sf);
 tg=gain(0,master);tw=osc('sine',2000);tw.connect(tg);
 var nb=ac.createBuffer(1,ac.sampleRate,ac.sampleRate),d=nb.getChannelData(0);for(var i=0;i<d.length;i++)d[i]=Math.random()*2-1;noise=nb}
var duckUntil=0;
function engine(r,thr,dt){if(!ac)return;var t=ac.currentTime,on=snd?1:0;
 spool+=((thr*r)-spool)*(1-Math.exp(-dt/(thr*r>spool?0.6:0.9)));
 tw.frequency.setTargetAtTime(1500+spool*3200,t,0.05);tg.gain.setTargetAtTime(on*spool*0.045,t,0.05);
 if(performance.now()<duckUntil)return;
 var f=100+r*300+(boost?25:0),base=on*(0.045+thr*0.2+r*0.12);
 o1.frequency.setTargetAtTime(f,t,0.05);o2.frequency.setTargetAtTime(f*0.5+0.7,t,0.05);o3.frequency.setTargetAtTime(f*2.01,t,0.05);
 fl.frequency.setTargetAtTime(500+r*1300+thr*300+(boost?600:0),t,0.06);eg.gain.setTargetAtTime(base,t,0.06);
 var lump=1-Math.min(1,r*1.6);
 lfo.frequency.setTargetAtTime(9+r*40,t,0.08);lg.gain.setTargetAtTime(base*(0.2+0.1*lump),t,0.08);
 lfo2.frequency.setTargetAtTime(4.3+r*12,t,0.08);lg2.gain.setTargetAtTime(base*0.12*lump,t,0.08);
 var scr=Math.max(0,Math.min(1,(r-0.5)/0.45));scr=scr*scr*(3-2*scr);
 sc.frequency.setTargetAtTime(f*4,t,0.04);sf.frequency.setTargetAtTime(f*4,t,0.04);sg.gain.setTargetAtTime(on*scr*(0.055+thr*0.07)*(boost?1.4:1),t,0.06);
 }
function burst(at,len,lvl,type,freq,q,out){var s=ac.createBufferSource();s.buffer=noise;s.playbackRate.value=0.7+Math.random()*0.6;
 var f=ac.createBiquadFilter();f.type=type;f.frequency.value=freq;f.Q.value=q;var g=ac.createGain();
 g.gain.setValueAtTime(0.0001,at);g.gain.exponentialRampToValueAtTime(lvl,at+0.004);g.gain.exponentialRampToValueAtTime(0.0001,at+len);
 s.connect(f);f.connect(g);g.connect(out||fxm);s.start(at,Math.random()*0.5,len+0.03)}
function pop(size){if(!ac||!snd||!noise)return;var t=ac.currentTime+0.005,len=0.03+Math.random()*0.06,pk=(0.5+Math.random()*0.5)*size;
 burst(t,len,pk*1.8,'bandpass',700+Math.random()*1500,0.9);
 var th=ac.createOscillator(),g=ac.createGain();th.type='square';th.frequency.setValueAtTime(150+Math.random()*90,t);th.frequency.exponentialRampToValueAtTime(60,t+len);
 g.gain.setValueAtTime(0.0001,t);g.gain.exponentialRampToValueAtTime(0.8*size,t+0.003);g.gain.exponentialRampToValueAtTime(0.0001,t+len*0.8);th.connect(g);g.connect(fxm);th.start(t);th.stop(t+len+0.02)}
function bang(size){if(!ac||!snd||!noise)return;var t=ac.currentTime+0.005,len=0.15+Math.random()*0.08;
 burst(t,len,3.0*size,'bandpass',1400+Math.random()*900,0.7);
 burst(t,0.04,2.2*size,'highpass',2800,0.7);
 var th=ac.createOscillator(),g=ac.createGain();th.type='triangle';th.frequency.setValueAtTime(300+Math.random()*80,t);th.frequency.exponentialRampToValueAtTime(140,t+len);
 g.gain.setValueAtTime(0.0001,t);g.gain.exponentialRampToValueAtTime(0.9*size,t+0.003);g.gain.exponentialRampToValueAtTime(0.0001,t+len*0.7);th.connect(g);g.connect(fxm);th.start(t);th.stop(t+len)}
function duck(sec){if(!eg)return;var t=ac.currentTime;eg.gain.cancelScheduledValues(t);eg.gain.setValueAtTime(eg.gain.value,t);eg.gain.linearRampToValueAtTime(0.01,t+0.03);
 sg.gain.cancelScheduledValues(t);sg.gain.setValueAtTime(sg.gain.value,t);sg.gain.linearRampToValueAtTime(0,t+0.03);duckUntil=performance.now()+sec*1000}
function howMany(){var q=Math.random();return q<0.15?0:q<0.55?1:q<0.85?2:3}
function liftoff(r,sp){var n=howMany(),s=0.9+r*0.3,at=0;if(!n){if(sp>0.3&&Math.random()<0.5)bov(sp*0.7);return}duck(0.15+n*0.22);bang(s);
 for(var i=1;i<n;i++){at+=170+Math.random()*190;(function(z){setTimeout(function(){bang(z)},at)})(s*(0.75+Math.random()*0.4))}
 if(Math.random()<0.5)setTimeout(function(){crackle(1+Math.round(r),0.5)},at+160);if(sp>0.3&&Math.random()<0.3)setTimeout(function(){bov(sp*0.7)},at+220)}
function crackle(n,size){for(var i=0,at=0;i<n;i++){at+=40+Math.random()*110;setTimeout(function(){pop(size)},at)}}
function bov(sp){if(!ac||!snd||!noise)return;var t=ac.currentTime+0.01;
 burst(t,0.35+sp*0.25,0.25+sp*0.45,'highpass',1800,0.7);
 if(Math.random()<0.5)for(var i=0;i<7;i++)burst(t+0.05+i*0.045,0.03,(0.35-i*0.04)*sp,'bandpass',900,1.2)}
var scg=null,scf=null,sclfo=null;
function screech(level){if(!ac||!noise)return;
 if(!scg){var src=ac.createBufferSource();src.buffer=noise;src.loop=true;scf=ac.createBiquadFilter();scf.type='bandpass';scf.frequency.value=2300;scf.Q.value=7;
  sclfo=ac.createOscillator();sclfo.frequency.value=7;var lg3=ac.createGain();lg3.gain.value=450;sclfo.connect(lg3);lg3.connect(scf.frequency);sclfo.start();
  scg=ac.createGain();scg.gain.value=0;src.connect(scf);scf.connect(scg);scg.connect(fxm);src.start()}
 scg.gain.setTargetAtTime(snd?level:0,ac.currentTime,level>0?0.03:0.12)}
function horn(on){if(!ac)return;if(on&&!hr){var hg=gain(0.35,master);var lp=ac.createBiquadFilter();lp.type='lowpass';lp.frequency.value=2600;lp.connect(hg);
  var a=ac.createOscillator(),c=ac.createOscillator();a.type=c.type='square';a.frequency.value=415;c.frequency.value=523;a.connect(lp);c.connect(lp);a.start();c.start();hr=[a,c,hg]}
 else if(!on&&hr){hr[0].stop();hr[1].stop();hr[2].disconnect();hr=null}}

/* ---- Buttons: touch events first (most reliable on iPhone), mouse as fallback ---- */
function hold(el,f){var on=0;
 function dn(e){e.preventDefault();e.stopPropagation();if(on)return;on=1;el.classList.add('h');f(1);kick()}
 function up(e){if(e&&e.cancelable)e.preventDefault();if(!on)return;on=0;el.classList.remove('h');f(0);kick()}
 el.addEventListener('touchstart',dn,{passive:false});el.addEventListener('touchend',up,{passive:false});el.addEventListener('touchcancel',up,{passive:false});
 el.addEventListener('mousedown',dn);el.addEventListener('mouseup',up);el.addEventListener('mouseleave',up)}
function tap(el,f){el.addEventListener('touchend',function(e){e.preventDefault();e.stopPropagation();f()},{passive:false});el.addEventListener('click',f)}
hold($('bst'),function(v){if(!v&&boost&&rpm>0.4)liftoff(rpm,Math.max(spool,0.5));boost=v});
hold($('brk'),function(v){brake=v});hold($('hrn'),function(v){horn(v)});

function paint(){$('sp').value=spd;$('spv').textContent=spd+'%';$('se').value=sens;$('sev').textContent=sens+'%';$('vo').value=vol;$('vov').textContent=vol+'%';
 $('au').classList.toggle('on',auto);$('sn').classList.toggle('on',snd)}
$('sp').oninput=function(){spd=+this.value;ss('sp',spd);paint()};$('se').oninput=function(){sens=+this.value;ss('se',sens);paint()};
$('vo').oninput=function(){vol=+this.value;ss('vo',vol);paint();if(master){master.gain.setTargetAtTime(vol/100,ac.currentTime,0.05);fxm.gain.setTargetAtTime(vol/100,ac.currentTime,0.05)}};
tap($('au'),function(){auto=!auto;ss('au',auto?'1':'0');paint();kick()});tap($('sn'),function(){snd=!snd;ss('sn',snd?'1':'0');paint()});
tap($('gear'),function(){$('set').classList.add('on')});tap($('cl'),function(){$('set').classList.remove('on')});paint();
function fix(){window.scrollTo(0,0)}addEventListener('resize',fix);addEventListener('orientationchange',function(){setTimeout(fix,300)});

/* ---- Start screen: a tap is required to unlock audio ---- */
var ios=/iPhone|iPad|iPod/.test(navigator.userAgent),standalone=navigator.standalone||matchMedia('(display-mode: standalone)').matches;
if(ios&&!standalone)$('ios').innerHTML='For full screen: tap Share &#8679; then <b>Add to Home Screen</b>,<br>and open Drift Racer from your home screen.';
var revUntil=0;
function start(e){if(e){e.preventDefault()}unlock();$('go').style.display='none';revUntil=performance.now()+900;setTimeout(function(){liftoff(0.8,0.5)},950)}
$('go').addEventListener('touchend',start,{passive:false});$('go').addEventListener('click',start);
document.addEventListener('touchend',function(){if(ac&&ac.state!=='running')ac.resume()},true);

/* ---- Speedometer and engine: estimated from the sticks, costs the robot nothing ---- */
var lastF=performance.now(),lastE=0,prevThr=0,rpm=0;
function frame(now){var dt=Math.min(0.1,(now-lastF)/1000);lastF=now;
 var thr=(brake||(blocked&&TH.v>0))?0:Math.abs(TH.v)/100,target=MAXMPH*thr*(boost?100:spd)/100;
 mph+=(target-mph)*(1-Math.exp(-dt/(target>mph?0.35:0.2)));
 $('mph').firstChild.nodeValue=mph.toFixed(2);$('fill').style.width=(mph/MAXMPH*100)+'%';
 if(now-lastE>50){lastE=now;var r=mph/MAXMPH,rev=now<revUntil;
  rpm+=((rev?0.8:thr*(boost?1:0.92))-rpm)*(1-Math.exp(-0.05/(thr>0.05?0.5:0.25)));
  if(prevThr-thr>0.4&&rpm>0.45)liftoff(rpm,spool);
  else if(thr<0.05&&rpm>0.3&&Math.random()<0.04*rpm)pop(0.3+rpm*0.4);
  prevThr=thr;engine(rpm,rev?0.9:thr,0.05);
  var st=Math.abs(SR.v),sliding=drift&&(dPhase>0||(TH.v>=40&&st>=60))&&TH.v>=20&&st>=35;
  screech(sliding?0.25+0.35*st/100:0)}
 requestAnimationFrame(frame)}
requestAnimationFrame(frame);

/* ---- Link to the robot: send on change (at most every 30 ms), one request at a time, 60 ms heartbeat ---- */
var drift=0,dPhase=0,lastShown='';
tap($('dft'),function(){drift=drift?0:1;$('dft').classList.toggle('on',!!drift);$('dft').innerHTML='DRIFT<br>'+(drift?'ON':'off');kick()});
function state(){return Math.round(SR.v*sens/100)+','+TH.v+','+(boost?100:spd)+','+brake+','+(auto?1:0)+','+drift+','+SR.v}
function got(t){var p=t.split('|');if(p[2]){var w=p[2].split(',');dPhase=+w[0];document.body.classList.toggle('drifting',dPhase>0);
  var res=w[1]+','+w[2]+','+w[3]+','+w[4];
  if(dPhase>0)$('dr').textContent='DRIFTING...';
  else if(res!==lastShown&&+w[2]>0){lastShown=res;$('dr').textContent='Last drift: turned '+w[1]+'° · wheels said '+w[2]+'° · slip '+w[3]+'% · peak '+w[4]+'°/s'}}
 if(p[1]){var q=p[1].split(',');
 $('dg').textContent='stops: link '+q[0]+' · auto-brake '+q[1]+'  |  worst: msg gap '+q[2]+' · sensor '+q[3]+' · loop '+q[4]+' ms'}
 var b=p[0]==='1';if(b!==blocked){blocked=b;document.body.classList.toggle('blk',b);$('ab').style.display=b?'block':'none'}}
function net(ok){var s=$('st');s.className=ok?'ok':'';s.innerHTML=ok?'&#9679; linked &middot; '+Math.round(rtt)+' ms':'&#9679; offline'}
var busy=0,tm=0,t0=0,GAP=30;
function kick(){if(busy)return;var w=GAP-(performance.now()-t0);if(tm)clearTimeout(tm);tm=w>0?setTimeout(loop,w):0;if(w<=0)loop()}
async function loop(){tm=0;busy=1;var s=state(),c=new AbortController(),to=setTimeout(function(){c.abort()},1500),wait=60;t0=performance.now();
 try{var r=await fetch('/d?'+s,{cache:'no-store',signal:c.signal});var t=await r.text();var d=performance.now()-t0;rtt=rtt?rtt*0.85+d*0.15:d;got(t);net(1)}
 catch(e){net(0);wait=300}
 clearTimeout(to);busy=0;if(wait<300&&state()!==s)kick();else tm=setTimeout(loop,wait)}
loop();
</script></body></html>"""

MANIFEST = ('{"name":"Mbot Drift Racer","short_name":"Drift Racer","start_url":"/",'
            '"display":"fullscreen","orientation":"landscape",'
            '"background_color":"#080c18","theme_color":"#080c18"}')

# Pre-built HTTP responses (built once, then the source strings are freed).
HDR = (b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n"
       b"Cache-Control: no-store\r\nConnection: close\r\n\r\n")
PAGE = (b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n" +
        HTML.replace("__WHEEL__", str(WHEEL_CM)).replace("__RPM__", str(MAX_RPM)).encode())
MAN = (b"HTTP/1.1 200 OK\r\nContent-Type: application/manifest+json\r\n"
       b"Connection: close\r\n\r\n" + MANIFEST.encode())
del HTML, MANIFEST

# =============================================================================
# LIGHTS
# =============================================================================

# Solid colours (R, G, B).
COLORS = {"brake": (255, 0, 0), "rev1": (255, 170, 0), "rev2": (255, 255, 255),
          "drive": (190, 190, 190), "high": (255, 255, 255),
          "park": (70, 28, 0), "off": (0, 0, 0)}
# Turn signals on the 5 CyberPi LEDs (LED 1 first): o = amber, w = white, k = off.
SIGNALS = {"L1": "o o w w w", "L0": "k k w w w", "R1": "w w w o o", "R0": "w w w k k"}

_light = None   # last light pattern sent


def light(key):
    """Show a light pattern. Talks to the LEDs only when the pattern changes."""
    global _light
    if key == _light:
        return
    if key in COLORS:
        r, g, b = COLORS[key]
        cyberpi.led.on(r, g, b)
    else:
        pat = SIGNALS[key]
        cyberpi.led.show(" ".join(pat.split()[::-1]) if FLIP_SIGNALS else pat)
    _light = key


_eye = None     # last eye pattern sent


def eyes(now):
    """Animate the ultrasonic sensor's LEDs. Sends only the lights that changed."""
    global _eye
    if not (EVIL_EYES and US):
        return
    if blocked:                                   # auto-brake: flashing warning
        pat, k = EYE_SLIT, (1.0 if (now // 120) & 1 else 0.15)
    elif brake:                                   # braking: narrowed
        pat, k = EYE_SLIT, 1.0
    elif diff(twitch_until, now) > 0:             # fast lift-off: twitch
        pat, k = EYE_MEAN, (1.0 if (now // 70) & 1 else 0.0)
    elif power >= 100 and gy > 0:                 # boost: full blaze
        pat, k = EYE_RAGE, 1.0
    elif gx or gy:                                # driving: brightness follows throttle
        pat, k = EYE_MEAN, 0.5 + 0.5 * abs(gy) / 100
    else:                                         # parked: slow breathing
        ph = (now % 2400) / 1200.0
        pat, k = EYE_MEAN, 0.2 + 0.8 * (ph if ph < 1 else 2 - ph)
    look = tuple(int(v * k) // 10 * 10 for v in pat)   # steps of 10 to limit updates
    if look == _eye:
        return
    poll()                                        # a waiting phone command goes first
    try:
        if look.count(look[0]) == 8:              # all lights equal: one call
            US.set_bri(look[0], "all", index=1)
        else:
            for i in range(8):
                if _eye is None or look[i] != _eye[i]:
                    US.set_bri(look[i], i + 1, index=1)
    except Exception:
        pass
    _eye = look


# =============================================================================
# MOTORS
# =============================================================================

_lr = None      # last (left, right) power sent


def _send(l, r, refresh):
    """Send forward-positive wheel powers (-100..100), applying the FLIP settings.

    Sent when the command changes, and on every phone message (refresh), because
    the motor board can stop motors that stop hearing from us.
    """
    global _lr
    if FLIP_LEFT:
        l = -l
    if FLIP_RIGHT:
        r = -r
    if refresh or (l, r) != _lr:
        mbot2.drive_power(l, r)
        _lr = (l, r)


def motors(x, y, p, refresh=False):
    """Arcade drive: mix steering x and throttle y (-100..100), scaled to power p (%)."""
    l = y + x
    r = y - x
    m = max(abs(l), abs(r), 100)
    l = l * p // m if l >= 0 else -(-l * p // m)   # round both signs the same way
    r = r * p // m if r >= 0 else -(-r * p // m)
    _send(l, r, refresh)


def wheels(l, r, refresh=False):
    """Drive each wheel directly (used by drift moves)."""
    _send(int(max(-100, min(100, l))), int(max(-100, min(100, r))), refresh)


# =============================================================================
# NETWORK
# =============================================================================

def start_hotspot():
    """Start the Wi-Fi access point and return the robot's IP address."""
    import network
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    try:
        ap.config(essid=ROBOT_WIFI_NAME, password=ROBOT_WIFI_PASS, authmode=3)
    except Exception:
        ap.config(essid=ROBOT_WIFI_NAME, password=ROBOT_WIFI_PASS)
    while not ap.active():
        time.sleep(0.2)
    return ap.ifconfig()[0]


def open_server():
    """Open the web server on port 80 (non-blocking).

    Right after a re-upload the previous program may still hold the port, so
    retry for about 10 s. If it never frees up, reboot once; a marker file
    prevents a reboot loop.
    """
    for attempt in range(14):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass
            s.bind(("0.0.0.0", 80))
            s.listen(3)
            s.settimeout(0)
            return s
        except OSError:
            try:
                s.close()
            except Exception:
                pass
            if attempt == 0:
                cyberpi.console.println("Waiting for port...")
            sleep_ms(700)
    if not rebooted_already():
        cyberpi.console.clear()
        cyberpi.console.println("Restarting...")
        try:
            with open("racer_reboot.txt", "w") as f:
                f.write("1")
            import machine
            sleep_ms(300)
            machine.reset()
        except Exception:
            pass
    cyberpi.console.clear()
    cyberpi.console.println("Port still busy.")
    cyberpi.console.println("Turn the robot")
    cyberpi.console.println("off and on.")
    raise OSError("port 80 busy - turn the robot off and on")


def rebooted_already():
    """Return True if we just rebooted because of a busy port; clears the marker."""
    try:
        with open("racer_reboot.txt") as f:
            f.read()
    except Exception:
        return False
    try:
        import os
        os.remove("racer_reboot.txt")
    except Exception:
        pass
    return True


# =============================================================================
# STATE
# =============================================================================

# Latest command from the phone
x = y = brake = 0     # steering (after the stiffness slider), throttle, brake button
power = 60            # speed limit (%); 100 while boosting
auto = 1              # auto-brake enabled
steer_raw = 0         # steering before the stiffness slider (used for drifting)
drift_on = 0          # DRIFT button is on

# Derived / output state
gx = gy = 0           # steering and throttle actually applied (after brake / auto-brake)
blocked = 0           # auto-brake is holding the robot
near = False          # filtered "something is close" flag
hits = 0              # consecutive close readings
phone_seen = False    # a phone has connected
twitch_until = 0      # eyes twitch until this time (after a fast lift-off)
srv = None            # web server socket

t_cmd = t_dist = ticks()                  # last phone message / last distance read
t_move = ticks() - BRAKE_LIGHT_MS - 1     # last time moving (no red flash at power-on)

# Drift
drift_phase = 0       # 0 = none, 1 = flick, 2 = slide
drift_dir = 1         # +1 right, -1 left
t_drift = 0           # when the current drift started
t_meas = 0            # last drift measurement time
inner_pw = SLIDE_INNER                 # inner wheel power (adjusted by gyro assist)
d_angle = d_pred = d_peak = 0.0        # gyro angle, wheel-predicted angle, peak deg/s
last_drift = (0, 0, 0, 0)              # (gyro deg, predicted deg, slip %, peak deg/s)

# Diagnostics shown on the phone
n_fs = 0              # failsafe stops (phone link went quiet while driving)
n_ab = 0              # auto-brake stops
w_gap = w_us = w_lp = 0   # worst phone-message gap / sensor read / loop time (ms)
t_win = ticks()       # start of the current 5 s diagnostics window


# =============================================================================
# DRIFT
# =============================================================================

def drift_end():
    """End the current drift and record its result."""
    global drift_phase, last_drift
    if drift_phase:
        slip = 0
        if d_pred > 20:
            slip = int(max(0, min(100, 100 - 100 * d_angle / d_pred)))
        last_drift = (int(d_angle), int(d_pred), slip, int(d_peak))
    drift_phase = 0


def drift_update(now):
    """Start, hold or end a drift based on the phone's sticks."""
    global drift_phase, drift_dir, t_drift, inner_pw, d_angle, d_pred, d_peak, t_meas
    if brake or blocked or not drift_on:
        drift_end()
        return
    if drift_phase == 0:
        if y >= DRIFT_MIN_THROTTLE and abs(steer_raw) >= DRIFT_ENTER:
            drift_phase = 1                      # flick: kick the rear out
            drift_dir = 1 if steer_raw > 0 else -1
            t_drift = t_meas = now
            inner_pw = SLIDE_INNER
            d_angle = d_pred = d_peak = 0.0
        return
    if y < 20 or abs(steer_raw) < DRIFT_HOLD:    # eased off: drift over
        drift_end()
        return
    if drift_phase == 1 and diff(now, t_drift) >= FLICK_MS:
        drift_phase = 2                          # slide: hold it


def drift_wheels(refresh):
    """Wheel powers during a drift: outer wheel at full power, inner wheel kicks, then drags."""
    if drift_phase == 1:
        outer, inner = 100, -100
    else:
        inner = inner_pw - (abs(steer_raw) - DRIFT_HOLD) * 0.8   # more steering = tighter
        outer = 100
    if drift_dir > 0:
        wheels(outer, inner, refresh)            # drifting right: left wheel is outer
    else:
        wheels(inner, outer, refresh)


def drift_measure(now):
    """While drifting: integrate gyro rotation vs wheel-predicted rotation, and run the gyro assist."""
    global d_angle, d_pred, d_peak, t_meas, inner_pw
    dt = diff(now, t_meas) / 1000.0
    if dt < 0.015:
        return
    t_meas = now
    try:
        rate = abs(cyberpi.get_gyro("z"))        # deg/s the body is really turning
    except Exception:
        rate = 0
    try:
        l = mbot2.EM_get_speed("EM1")
        r = mbot2.EM_get_speed("EM2")
        if FLIP_LEFT:
            l = -l
        if FLIP_RIGHT:
            r = -r
        cm_per_rpm = 3.14159 * WHEEL_CM / 60.0
        pred = abs((r - l) * cm_per_rpm) / TRACK_CM * 57.3   # deg/s the wheels imply
    except Exception:
        pred = 0
    d_angle += rate * dt
    d_pred += pred * dt
    if rate > d_peak:
        d_peak = rate
    if GYRO_ASSIST and drift_phase == 2:         # hold a steady spin rate
        target = TARGET_YAW * abs(steer_raw) / 100.0
        inner_pw = max(-100, min(100, inner_pw + (rate - target) * ASSIST_GAIN * dt * 10))
        drift_wheels(False)


# =============================================================================
# DRIVING
# =============================================================================

def drive(refresh=False):
    """Apply the newest command (with brake, auto-brake and drift) to the motors."""
    global blocked, gx, gy
    blocked = 1 if (auto and y > 0 and not brake and near) else 0
    gy = 0 if (brake or blocked) else y
    gx = 0 if brake else x
    drift_update(ticks())
    if drift_phase:
        drift_wheels(refresh)
    else:
        motors(gx, gy, power, refresh)


def poll():
    """Handle one waiting phone request: update the motors first, then reply.

    Returns True if a request was handled.
    """
    global x, y, power, brake, auto, t_cmd, w_gap, twitch_until, phone_seen, drift_on, steer_raw
    try:
        conn, _ = srv.accept()
    except OSError:
        return False
    try:
        conn.settimeout(1)
        req = conn.recv(1024)
        if req[:7] == b"GET /d?":
            # /d?steer,throttle,power,brake,auto,drift,steer_raw
            v = req[7:req.find(b" ", 7)].decode().split(",")
            was_y = y
            phone_seen = True
            x, y, power, brake, auto = int(v[0]), int(v[1]), int(v[2]), int(v[3]), int(v[4])
            if len(v) > 6:
                drift_on, steer_raw = int(v[5]), int(v[6])
            now = ticks()
            if was_y > 60 and abs(y) < 10:
                twitch_until = now + 350         # fast lift-off: eyes twitch
            gap = diff(now, t_cmd)
            if gap > w_gap:
                w_gap = gap
            t_cmd = now
            drive(True)
            # Reply: blocked | diagnostics | drift state and last result
            conn.sendall(HDR + (b"1" if blocked else b"0") +
                         ("|%d,%d,%d,%d,%d|%d,%d,%d,%d,%d" % (
                             n_fs, n_ab, w_gap, w_us, w_lp,
                             drift_phase, last_drift[0], last_drift[1],
                             last_drift[2], last_drift[3])).encode())
        elif req[:11] == b"GET /m.json":
            conn.sendall(MAN)
        else:
            conn.sendall(PAGE)
    except Exception:
        pass
    try:
        conn.close()
    except Exception:
        pass
    return True


# =============================================================================
# STARTUP
# =============================================================================

motors(0, 0, 0)
cyberpi.console.clear()
cyberpi.console.println("Starting hotspot...")
ip = start_hotspot()
srv = open_server()
rebooted_already()                  # started fine: clear any old reboot marker
cyberpi.console.clear()
cyberpi.console.println("Wi-Fi: " + ROBOT_WIFI_NAME)
cyberpi.console.println("Pass: " + ROBOT_WIFI_PASS)
cyberpi.console.println(ip)
light("off")                        # lights stay off until a phone connects

# =============================================================================
# MAIN LOOP
# =============================================================================

t_loop = ticks()
t_eye = 0
while True:
    busy = poll()

    now = ticks()
    lp = diff(now, t_loop)
    t_loop = now
    if lp > w_lp:
        w_lp = lp
    if diff(now, t_win) > 5000:             # diagnostics show the worst of the last 5 s
        w_gap = w_us = w_lp = 0
        t_win = now

    # Failsafe: stop if the phone went quiet. Check for a waiting message first;
    # if the robot itself was slow (e.g. a long sensor read), that is not the phone's fault.
    if diff(now, t_cmd) > FAILSAFE_MS and not poll():
        if gx or gy:
            n_fs += 1
        x = y = brake = 0
        drive()

    # Auto-brake: read the distance every 40 ms when driving forward, every
    # 300 ms when parked (so starting toward a wall is blocked too), never while
    # turning or reversing.
    if auto and US and diff(now, t_dist) >= (
            40 if (y > 0 and not brake) else 300 if not (gx or gy) else 100000):
        busy = poll() or busy
        t_us = ticks()
        try:
            d = int(US.get(index=1))
        except Exception:
            d = 0
        t_dist = ticks()
        us = diff(t_dist, t_us)
        if us > w_us:
            w_us = us
        # Glitch filter: brake only after BRAKE_HITS close readings in a row, and
        # release only when clearly further away (no stop/go flicker).
        lim = STOP_CM + power * STOP_PER_POWER
        if d >= 300 or d > lim + RELEASE_CM:  # clear (300 = nothing in range)
            hits = 0
            near = False
        elif 2 < d < lim:                     # close (0-2 = bad reading, ignored)
            hits += 1
            if hits >= BRAKE_HITS:
                if not near and y > 0:
                    n_ab += 1
                near = True
        drive()                               # re-evaluate with the fresh distance
        busy = True

    # Lights (sent only when the pattern changes)
    if brake or blocked:
        key = "brake"
    elif gy < 0:                              # reversing: flash yellow/white
        key = "rev1" if (now // 200) & 1 else "rev2"
    elif gx or gy:
        if abs(gx) > 15:                      # turning: amber signal on that side
            key = ("L" if gx < 0 else "R") + ("1" if (now // 330) & 1 else "0")
        else:
            key = "high" if power >= 100 else "drive"   # boost = high beams
    elif diff(now, t_move) < BRAKE_LIGHT_MS:  # just stopped: brake light
        key = "brake"
    elif phone_seen and diff(now, t_cmd) < FAILSAFE_MS:
        key = "park"                          # idle: dim amber
    else:
        key = "off"                           # no phone
    if gx or gy:
        t_move = now
    if key != _light:
        poll()
        light(key)

    # Drift: measure, run the gyro assist, and switch flick -> slide on time
    if drift_phase:
        drift_measure(now)
        drift_update(now)
        if drift_phase == 2 and diff(now, t_drift) < FLICK_MS + 40:
            drive()                           # flick just ended: apply slide powers now
        elif not drift_phase:
            drive()                           # drift just ended: back to normal driving
        busy = True

    if diff(now, t_eye) >= 90:                # eyes: at most ~11 updates/s
        t_eye = now
        eyes(now)

    if not busy:
        sleep_ms(3)
