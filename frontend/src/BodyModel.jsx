import React, {useEffect, useRef, useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {ArrowUpRight, RotateCcw, Move, Plus, House} from 'lucide-react';
import {ALERT_COLORS,baselineText,FIELD_META,formatValue,highestAlert,KEY_METRICS,lastObservation,tierLabel,timeLabel} from './data.js';
import {SeriesPanel} from './charts.jsx';

const regions=[
 {name:'Brain & mind',pos:[0,2.48,.3],description:'Sleep, mood, and self-reported symptoms.',metrics:['sleep','mood','stress'],function:'Cognition, sleep regulation, and emotional wellbeing.'},
 {name:'Eyes',pos:[.18,2.3,.38],description:'Visual acuity, blur, and eye examination records.',function:'Vision and visual processing.'},
 {name:'Ears & balance',pos:[-.36,2.3,.02],description:'Hearing, dizziness, and motion-sickness observations.',function:'Hearing and spatial orientation.'},
 {name:'Heart & circulation',pos:[.2,1.6,.39],description:'Heart rate and blood pressure in personal context.',metrics:['hr','bp'],function:'Circulates blood and supports tissue oxygen delivery.'},
 {name:'Lungs & breathing',pos:[-.29,1.77,.33],description:'Breathing rate and oxygen saturation.',metrics:['rr','spo2'],function:'Gas exchange and respiratory function.'},
 {name:'Blood & immune',pos:[-.5,1.05,.2],description:'Blood glucose and laboratory observations.',metrics:['glucose'],function:'Nutrient transport and immune defense.'},
 {name:'Stomach & nutrition',pos:[.16,1.08,.3],description:'Food, fluid, appetite, and digestive check-ins.',metrics:['fluid'],function:'Digestion, nutrient absorption, and hydration.'},
 {name:'Kidneys & bladder',pos:[-.23,.65,.22],description:'Urine observations and urinary symptoms.',function:'Fluid balance and waste removal.'},
 {name:'Muscles & joints',pos:[.78,1.16,.07],description:'Exercise, workload, and discomfort observations.',function:'Movement, strength, and physical function.'},
 {name:'Skin',pos:[-.98,.42,.06],description:'Skin symptoms, wounds, and image observations.',function:'Protective barrier and temperature regulation.'},
 {name:'Bones',pos:[.29,-.39,.16],description:'Resistance exercise and bone-health records.',function:'Structural support and mineral storage.'},
 {name:'Whole body & exposure',pos:[-.28,-1.02,.15],description:'Temperature and personal exposure observations.',metrics:['temp','radiation','dose'],function:'Whole-body state and exposure context.'},
];
const cabinPoints=[{pos:[-1.35,2.05,0]},{pos:[1.35,2.1,0]},{pos:[-1.4,.12,0]},{pos:[1.4,-.15,0]}];
const floatingPosition=(index,time=0)=>{const base=index===12?[1.5,1.25,0]:cabinPoints[index-13].pos;return [base[0]+Math.sin(time*.65+index*1.7)*.045,base[1]+Math.sin(time*.8+index*1.3)*.065,base[2]];};
const labels=Object.fromEntries(Object.entries(FIELD_META).map(([key,meta])=>[key,meta]));
function getRegionStatus(index,member){
 const alert=highestAlert((member.alerts||[]).filter(a=>a.region_index===index));
 if(alert)return {level:alert.tier,label:tierLabel(alert.tier),alert};
 const keys=regions[index].metrics||[];
 const readings=keys.map(key=>lastObservation(member,key)).filter(Boolean);
 if(!readings.length)return {level:'unavailable',label:'No data'};
 if(readings.every(r=>r.freshness==='overdue'))return {level:'unavailable',label:'Overdue data'};
 return {level:'neutral',label:'Recorded data'};
}
const regionContext=[
 ['Isolation, workload, and disrupted light cycles can affect sleep and mood.','Review sleep duration, self-reported mood, and recent workload together.'],
 ['Fluid shifts in microgravity can affect eye health and vision.','Record visual changes and review available eye-test observations.'],
 ['Gravity transitions can affect spatial orientation and balance.','Record dizziness, motion sickness, hearing changes, and mission phase.'],
 ['Microgravity changes fluid distribution and cardiovascular loading.','Compare readings taken under similar resting and activity conditions.'],
 ['Cabin atmosphere and activity provide important respiratory context.','Review breathing observations alongside cabin oxygen and CO₂.'],
 ['Stress, nutrition, and mission conditions can influence immune and metabolic observations.','Record meal context for glucose and review available laboratory records.'],
 ['Appetite, workload, and food access affect nutrition and hydration.','Add food, fluid, and digestive observations to the daily record.'],
 ['Hydration and changes in mineral balance are relevant urinary context.','Record fluid intake, urinary symptoms, and available test results.'],
 ['Reduced gravitational loading changes muscle use and physical conditioning.','Review exercise completion, workload, and reported discomfort.'],
 ['Dry cabin air, equipment contact, and minor injuries can affect skin.','Record the site, duration, and progression of a skin observation.'],
 ['Reduced mechanical loading affects bone maintenance over long missions.','Review resistance-exercise logs; bone density is not measured by this demo.'],
 ['Thermal conditions, activity, and exposure history provide whole-body context.','Keep core and skin temperature distinct and review measurement conditions.'],
];
function RegionOutlook({region,member}){
 const [metric,setMetric]=useState('');
 const keys=regions[region].metrics||[];
 const key=keys.includes(metric)?metric:keys[0];
 return <div className="region-outlook"><div className="outlook-title"><h4>Recorded perspective</h4><span className="tiny-index">STORED OBSERVATIONS</span></div>{key?<>
  {keys.length>1&&<div className="outlook-controls"><select aria-label="Trend indicator" value={key} onChange={e=>setMetric(e.target.value)}>{keys.map(k=><option key={k} value={k}>{labels[k][0]}</option>)}</select></div>}
  <div className="outlook-metric-label">{labels[key][0]}{key==='bp'?' · systolic / diastolic':''}<span>{labels[key][1]}</span></div>
  <SeriesPanel key={`${member.runId}:${member.id}:${key}`} member={member} metric={KEY_METRICS[key]} defaultWindow="7d" compact/>
  <p className="outlook-disclaimer">A forecast model is not connected. Only recorded measurements are shown.</p>
 </>:<div className="outlook-missing">No measurements are available for this region yet.</div>}</div>;
}
function buildHuman(){
 const group=new THREE.Group();
 const fabric=new THREE.MeshStandardMaterial({color:0xe4e5df,roughness:.88,metalness:.03});
 const trim=new THREE.MeshStandardMaterial({color:0x313741,roughness:.7,metalness:.25});
 const silver=new THREE.MeshStandardMaterial({color:0xb1b7bc,roughness:.32,metalness:.75});
 const red=new THREE.MeshStandardMaterial({color:0x9c3134,roughness:.8});
 const skin=new THREE.MeshStandardMaterial({color:0xc39a80,roughness:.86});
 const mesh=(geometry,material,x,y,z)=>{const m=new THREE.Mesh(geometry,material);m.position.set(x,y,z);group.add(m);return m};
 const oval=(x,y,z,a,b,c,mat=fabric)=>{const m=mesh(new THREE.SphereGeometry(1,32,24),mat,x,y,z);m.scale.set(a,b,c);return m};
 const box=(x,y,z,a,b,c,mat=fabric)=>mesh(new THREE.BoxGeometry(a,b,c,3,3,3),mat,x,y,z);
 const segment=(start,end,r1,r2,mat=fabric)=>{const a=new THREE.Vector3(...start),b=new THREE.Vector3(...end),delta=b.clone().sub(a);const m=mesh(new THREE.CylinderGeometry(r2,r1,delta.length(),32,5),mat,0,0,0);m.position.copy(a.add(b).multiplyScalar(.5));m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),delta.normalize());return m};
 const cuff=(center,radius,tube,axis=[0,1,0],mat=trim)=>{const m=mesh(new THREE.TorusGeometry(radius,tube,10,40),mat,...center);m.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),new THREE.Vector3(...axis).normalize());return m};
 // Continuous tailored torso: broad shoulders, tapered waist, natural hips.
 const profile=[[.28,.55],[.39,.65],[.4,.8],[.34,1.02],[.38,1.25],[.49,1.55],[.5,1.72],[.4,1.85],[.23,1.94]].map(([r,y])=>new THREE.Vector2(r,y));
 const torso=mesh(new THREE.LatheGeometry(profile,48),fabric,0,0,0);torso.scale.z=.68;
 oval(0,.59,0,.4,.24,.27);
 // Life-support backpack and hard upper torso hardware remain visible on rotation.
 box(0,1.4,-.36,.65,.87,.3);box(0,1.41,-.53,.51,.66,.06,trim);
 cuff([0,1.97,0],.245,.048,[0,1,0],silver);cuff([0,1.92,0],.25,.035);
 // Uncovered head with jaw, ears, nose, brow, and eyes.
 oval(0,2.28,.025,.24,.32,.225,skin);oval(0,2.13,.065,.19,.15,.17,skin);
 oval(0,2.49,-.015,.235,.14,.22,trim);
 for(const side of [-1,1]){oval(side*.243,2.27,.02,.044,.085,.04,skin);oval(side*.084,2.32,.222,.04,.017,.011,trim);oval(side*.086,2.365,.214,.055,.012,.012,trim);}
 oval(0,2.255,.244,.036,.065,.05,skin);oval(0,2.15,.226,.067,.009,.008,trim);
 for(const side of [-1,1]){
  oval(side*.47,1.72,0,.215,.23,.23);cuff([side*.48,1.7,0],.18,.027,[side*.3,-1,0]);
  const shoulder=[side*.5,1.68,0],elbow=[side*.74,1.09,.015],wrist=[side*.91,.5,.055];
  segment(shoulder,elbow,.145,.19);oval(...elbow,.16,.16,.17,trim);segment(elbow,wrist,.105,.15);
  // Fabric bellows and red identification bands follow the limb axis.
  for(let i=0;i<4;i++){const t=.24+i*.13;cuff([side*(.5+.24*t),1.68-.59*t,.015*t],.174-i*.005,.012,[side*.24,-.59,.015],fabric);}
  cuff([side*.63,1.36,.01],.163,.026,[side*.24,-.59,.015],red);
  cuff(wrist,.115,.025,[side*.17,-.59,.04],silver);
  oval(side*.94,.35,.06,.112,.18,.09);oval(side*1.015,.36,.12,.045,.1,.045);
  for(let i=0;i<4;i++)oval(side*(.884+i*.033),.205+Math.abs(i-1.5)*.014,.074,.023,.085,.036);
  const hip=[side*.22,.6,0],knee=[side*.28,-.32,.015],ankle=[side*.3,-1.12,.04];
  segment(hip,knee,.18,.225);oval(...knee,.18,.19,.19,trim);segment(knee,ankle,.12,.17);
  oval(side*.28,-.3,.155,.145,.15,.065);cuff([side*.27,-.13,.01],.183,.026,[0,1,0],red);
  for(let i=0;i<3;i++)cuff([side*.29,-.48-i*.055,.025],.161-i*.003,.012,[0,1,0],fabric);
  cuff(ankle,.13,.03,[0,1,0],silver);oval(side*.3,-1.22,.15,.16,.16,.285);
  box(side*.3,-1.345,.15,.3,.055,.48,trim);
 }
 // Chest controller, connectors, harness, and equipment panels.
 box(0,1.47,.332,.43,.3,.12,trim);box(0,1.5,.398,.35,.18,.025,silver);
 box(-.065,1.52,.417,.12,.06,.015,new THREE.MeshStandardMaterial({color:0x486472,emissive:0x1c3038,emissiveIntensity:.35}));
 for(let i=0;i<3;i++)oval(.04+i*.055,1.45,.421,.013,.013,.009,i===2?red:trim);
 for(const side of [-1,1]){cuff([side*.23,1.06,.247],.049,.017,[0,0,1],silver);box(side*.255,1.72,.259,.045,.3,.028,trim);}
 const hosePath=new THREE.CatmullRomCurve3([new THREE.Vector3(-.23,1.06,.29),new THREE.Vector3(-.43,.94,.36),new THREE.Vector3(-.46,.73,.16),new THREE.Vector3(-.38,.79,-.2)]);
 mesh(new THREE.TubeGeometry(hosePath,40,.025,10,false),silver,0,0,0);
 // Locally drawn NASA-style identification patch: no external textures needed.
 const canvas=document.createElement('canvas');canvas.width=256;canvas.height=256;const ctx=canvas.getContext('2d');
 if(ctx){ctx.fillStyle='#174a88';ctx.beginPath();ctx.arc(128,128,117,0,Math.PI*2);ctx.fill();ctx.fillStyle='#fff';for(let i=0;i<24;i++){const x=35+(i*71)%186,y=35+(i*43)%186;ctx.fillRect(x,y,2,2);}ctx.strokeStyle='#e84543';ctx.lineWidth=9;ctx.beginPath();ctx.moveTo(25,191);ctx.quadraticCurveTo(130,140,233,52);ctx.stroke();ctx.fillStyle='#fff';ctx.font='bold italic 59px serif';ctx.textAlign='center';ctx.fillText('NASA',125,148);const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;const patch=mesh(new THREE.PlaneGeometry(.17,.17),new THREE.MeshStandardMaterial({map:texture,transparent:true,roughness:1}),-.255,1.68,.295);patch.rotation.y=-.18;}
 return group;
}
export default function BodyModel({member,cabin=[],habitat,onHabitat,onEnvironment,onCheckin,viewState,region,onRegionChange,onAlert}){
 const host=useRef(null),markerRefs=useRef([]),controlsRef=useRef(null);
 const [available,setAvailable]=useState(true),[hovered,setHovered]=useState(null);
 const hoverLine=useRef(null),hoverCard=useRef(null),current=regions[region];
 const regionStatus=getRegionStatus(region,member);
useEffect(()=>{const mount=host.current;let renderer;try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});}catch{setAvailable(false);return;}renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));renderer.setClearColor(0,0);mount.prepend(renderer.domElement);const scene=new THREE.Scene();const camera=new THREE.PerspectiveCamera(36,1,.1,100);camera.position.set(0,.7,8.4);const controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,.65,0);controls.enablePan=false;controls.enableZoom=false;controls.enableDamping=true;controls.minPolarAngle=Math.PI*.29;controls.maxPolarAngle=Math.PI*.66;controls.minAzimuthAngle=-Math.PI*.65;controls.maxAzimuthAngle=Math.PI*.65;if(viewState.current){camera.position.fromArray(viewState.current.position);controls.target.fromArray(viewState.current.target);controls.update()}controlsRef.current={controls,camera};const cabinCamera=new THREE.PerspectiveCamera(36,1,.1,100);cabinCamera.position.set(0,.7,8.4);cabinCamera.lookAt(new THREE.Vector3(0,.65,0));cabinCamera.updateMatrixWorld();scene.add(new THREE.HemisphereLight(0xe3e7ef,0x181a21,2));const key=new THREE.DirectionalLight(0xf0f1f6,3);key.position.set(-3,5,4);scene.add(key);const rim=new THREE.DirectionalLight(0x9aaac9,3);rim.position.set(3,2,-3);scene.add(rim);scene.add(buildHuman());
const ring=new THREE.Mesh(new THREE.TorusGeometry(1.53,.006,8,120),new THREE.MeshBasicMaterial({color:0x737781,transparent:true,opacity:.35}));ring.rotation.x=Math.PI/2;ring.position.y=-1.39;scene.add(ring);
const resize=new ResizeObserver(()=>{const w=mount.clientWidth,h=mount.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();cabinCamera.aspect=w/h;cabinCamera.updateProjectionMatrix()});resize.observe(mount);let frame;const motion=window.matchMedia('(prefers-reduced-motion: reduce)');const vector=new THREE.Vector3();function draw(){if(document.hidden){frame=null;return;}const floatTime=motion.matches?0:performance.now()/1000;controls.update();renderer.render(scene,camera);regions.forEach((r,i)=>{const el=markerRefs.current[i];if(!el)return;vector.set(...r.pos).project(camera);el.style.left=`${(vector.x*.5+.5)*100}%`;el.style.top=`${(-vector.y*.5+.5)*100}%`;el.style.visibility=vector.z>1?'hidden':'visible';});for(let i=12;i<17;i++){const pin=markerRefs.current[i];if(pin){vector.set(...floatingPosition(i,floatTime)).project(cabinCamera);pin.style.left=`${(vector.x*.5+.5)*100}%`;pin.style.top=`${(-vector.y*.5+.5)*100}%`;}}const preview=hoverCard.current,line=hoverLine.current;if(preview&&line){const index=Number(preview.dataset.region);vector.set(...(index>=12?floatingPosition(index,floatTime):regions[index].pos)).project(index>=12?cabinCamera:camera);const w=mount.clientWidth,h=mount.clientHeight,x=(vector.x*.5+.5)*w,y=(-vector.y*.5+.5)*h;const cardWidth=240,cardHeight=preview.offsetHeight;const layout=mount.closest('.anatomy-layout');const outer=layout.getBoundingClientRect(),viewport=mount.getBoundingClientRect();const xOffset=viewport.left-outer.left,yOffset=viewport.top-outer.top;const info=layout.querySelector('.anatomy-information');const stack=info.getBoundingClientRect().top>=viewport.bottom;let left,top,edgeX,edgeY;if(stack){left=Math.max(10,Math.min(outer.width-cardWidth-10,xOffset+x-cardWidth/2));top=yOffset+h+12;edgeX=left+cardWidth/2;edgeY=top;}else{left=viewport.right-outer.left+18;top=Math.max(58,Math.min(outer.height-cardHeight-16,yOffset+y-cardHeight/2));edgeX=left;edgeY=top+Math.min(30,cardHeight/2);}preview.style.width=cardWidth+'px';preview.style.left=left+'px';preview.style.top=top+'px';line.setAttribute('points',`${xOffset+x},${yOffset+y} ${stack?xOffset+x:(xOffset+x+edgeX)/2},${stack?edgeY-10:edgeY} ${edgeX},${edgeY}`);}frame=requestAnimationFrame(draw)}function visibilityChanged(){if(document.hidden){cancelAnimationFrame(frame);frame=null;}else if(frame==null){draw();}}document.addEventListener('visibilitychange',visibilityChanged);draw();return()=>{document.removeEventListener('visibilitychange',visibilityChanged);viewState.current={position:camera.position.toArray(),target:controls.target.toArray()};cancelAnimationFrame(frame);resize.disconnect();controls.dispose();controlsRef.current=null;scene.traverse(o=>{o.geometry?.dispose();if(o.material){const materials=Array.isArray(o.material)?o.material:[o.material];materials.forEach(m=>{m.map?.dispose();m.dispose()})}});renderer.dispose();renderer.domElement.remove()};},[viewState]);
useEffect(()=>{const state=controlsRef.current;if(state){state.controls.reset();state.camera.position.set(0,.7,8.4);state.controls.target.set(0,.65,0);state.controls.update();viewState.current=null;}setHovered(null);},[member.id,member.runId,viewState]);
function reset(){const state=controlsRef.current;if(state){state.camera.position.set(0,.7,8.4);state.controls.target.set(0,.65,0);state.controls.update()}}
 const value=key=>key==='bp'?(member.bp||'—'):formatValue(member[key],FIELD_META[key]?.[2]??1);
 const preview=hovered!==null&&hovered<12?regions[hovered]:null;
 const cabinPoint=hovered>12?cabin[hovered-13]:null;
 return <section className="anatomy-section">
  <div className="section-cap"><h2><span>02</span>Human systems map</h2><span className="mono-muted">{member.name.toUpperCase()}</span></div>
  <div className={`anatomy-layout ${hovered!==null?'has-point-preview':''}`} onMouseLeave={()=>setHovered(null)}>
   <div className="anatomy-stage">
    <div className="anatomy-stage-top"><span className="tiny-index">SUIT VIEW / INTERACTIVE 3D</span><button onClick={reset} aria-label="Reset body orientation"><RotateCcw size={14}/></button></div>
    <div className="model-viewport" aria-label={`Interactive 3D body model for ${member.name}`}><div className="model-canvas-mount" ref={host}/>
     {available?regions.map((r,i)=><button key={r.name} ref={el=>markerRefs.current[i]=el} className={`anatomy-pin ${region===i?'pin-selected':''} ${getRegionStatus(i,member).level==='neutral'?'pin-data':'pin-empty'} ${getRegionStatus(i,member).alert?'pin-alert-'+getRegionStatus(i,member).level:''}`} aria-label={r.name} aria-pressed={region===i} aria-describedby={hovered===i?'body-point-preview':undefined} onMouseEnter={()=>setHovered(i)} onFocus={()=>setHovered(i)} onBlur={()=>setHovered(null)} onClick={()=>onRegionChange(i)}><span/><b>{String(i+1).padStart(2,'0')}</b></button>):<div className="model-fallback">3D rendering is unavailable in this browser. Explore all regions using the controls below.</div>}
     {available&&cabin.slice(0,4).map((point,i)=><button key={point.metric} ref={el=>markerRefs.current[i+13]=el} className={`environment-pin ${point.alert?'pin-alert-'+point.alert.tier:''}`} aria-label={`${point.name}: ${formatValue(point.value,2)} ${point.unit}`} aria-describedby={hovered===i+13?'body-point-preview':undefined} onMouseEnter={()=>setHovered(i+13)} onFocus={()=>setHovered(i+13)} onBlur={()=>setHovered(null)} onClick={()=>setHovered(hovered===i+13?null:i+13)}><span/><b>{point.label}</b></button>)}
     {available&&<button ref={el=>markerRefs.current[12]=el} className="cabin-floating-pin" aria-label="Cabin environment" aria-describedby={hovered===12?'body-point-preview':undefined} onMouseEnter={()=>setHovered(12)} onFocus={()=>setHovered(12)} onBlur={()=>setHovered(null)} onClick={onEnvironment}><span className="cabin-pin-orbit"/><House size={16}/><span className="cabin-pin-label">CABIN<small>STORED DATA</small></span></button>}
    </div>
    <div className="habitat-orbit"><button onClick={onHabitat}><House size={13}/>{habitat?.name||'SHARED ENVIRONMENT'}<ArrowUpRight size={12}/></button></div>
    <div className="anatomy-stage-bottom"><span><Move size={12}/>Drag to rotate</span><span><i/>Reading available<i className="unavailable"/>Unavailable / overdue</span></div>
   </div>
   <div className="anatomy-information">
    <div className="region-picker" aria-label="Body regions">{regions.map((r,i)=><button key={r.name} aria-pressed={region===i} className={`region-option region-${getRegionStatus(i,member).level} ${region===i?'region-active':''}`} style={getRegionStatus(i,member).alert?{borderColor:ALERT_COLORS[getRegionStatus(i,member).level],backgroundColor:ALERT_COLORS[getRegionStatus(i,member).level]+'18'}:undefined} onClick={()=>onRegionChange(i)}><span>{String(i+1).padStart(2,'0')}</span><span className="region-option-copy">{r.name}<small style={getRegionStatus(i,member).alert?{color:ALERT_COLORS[getRegionStatus(i,member).level],fontWeight:700}:undefined}>{getRegionStatus(i,member).label}</small></span></button>)}</div>
    <div className={`region-detail region-detail-${regionStatus.level}`}><div className="kicker">REGION / {String(region+1).padStart(2,'0')}</div><h3>{current.name}</h3><p>{current.function}</p>
     {regionStatus.alert&&<button className={`region-alert-summary tier-${regionStatus.alert.tier}`} onClick={()=>onAlert?.(regionStatus.alert)}><strong>{tierLabel(regionStatus.alert.tier)} · {regionStatus.alert.title}</strong><p>{regionStatus.alert.message}</p><small>{timeLabel(regionStatus.alert.last_observation_at)} · Review alert →</small></button>}
     {current.metrics?<div className="region-readings">{current.metrics.map(key=><div key={key}><span>{labels[key][0]}</span><strong>{value(key)}<small>{labels[key][1]}</small></strong><span className="tiny-index">{timeLabel(lastObservation(member,key)?.measured_at)}{lastObservation(member,key)?.freshness==='overdue'?' · OVERDUE':''}</span><small className="region-baseline">{baselineText(member,key)}</small></div>)}</div>:<div className="region-unavailable"><span className="tiny-index">NO MEASUREMENT AVAILABLE</span><p>{current.description} No observation has been supplied for {member.name}.</p></div>}
     <div className="region-context"><h4>Spaceflight context</h4><p>{regionContext[region][0]}</p><h4>What to review</h4><p>{regionContext[region][1]}</p></div>
     <RegionOutlook region={region} member={member}/><button className="region-checkin" onClick={onCheckin}><Plus size={13}/>Add a session observation<ArrowUpRight size={13}/></button>
    </div>
   </div>
   {hovered!==null&&available&&<><svg className="anatomy-hover-line" aria-hidden="true"><polyline ref={hoverLine} points=""/></svg><div ref={hoverCard} data-region={hovered} id="body-point-preview" role="tooltip" className="anatomy-hover-card"><span className="tiny-index">{hovered>=12?'SHARED ENVIRONMENT':member.id}</span><h4>{hovered===12?'Cabin environment':hovered>12?cabinPoint?.name:preview?.name}</h4>
    {hovered===12?cabin.slice(0,4).map(point=><div className="hover-reading" key={point.metric}><span>{point.label}</span><strong>{formatValue(point.value,2)}<small>{point.unit}</small></strong></div>):hovered>12?<><div className="hover-reading"><span>{cabinPoint?.label}</span><strong>{formatValue(cabinPoint?.value,2)}<small>{cabinPoint?.unit}</small></strong></div><p>{timeLabel(cabinPoint?.measured_at)}{cabinPoint?.freshness==='overdue'?' · overdue':''}</p></>:preview?.metrics?preview.metrics.map(key=><div className="hover-reading" key={key}><span>{labels[key][0]}</span><strong>{value(key)}<small>{labels[key][1]}</small></strong></div>):<p>No measurement available</p>}
    {preview&&getRegionStatus(hovered,member).alert&&<p className="hover-alert-status" style={{color:ALERT_COLORS[getRegionStatus(hovered,member).level]}}>{getRegionStatus(hovered,member).label}: {getRegionStatus(hovered,member).alert.message}</p>}{cabinPoint?.alert&&<p style={{color:ALERT_COLORS[cabinPoint.alert.tier]}}>{tierLabel(cabinPoint.alert.tier)}: {cabinPoint.alert.message}</p>}<span className="hover-source">Recorded synthetic observations</span><span className="hover-hint">{hovered===12?'Click to explore the habitat':hovered>12?'Use the large CABIN point to explore':'Click point for region details'}</span>
   </div></>}
  </div>
 </section>;
}
