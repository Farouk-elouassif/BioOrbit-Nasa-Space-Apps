import React,{useState} from 'react';
import {postJSON} from './api.js';

const fields=[['heart_rate','Heart rate (bpm)',1,300],['respiratory_rate','Breathing rate (/min)',1,100],['spo2','SpO₂ (%)',1,100],['systolic_blood_pressure','Systolic BP (mmHg)',1,300],['diastolic_blood_pressure','Diastolic BP (mmHg)',1,200],['blood_glucose','Glucose (mg/dL)',1,1000],['body_temperature','Temperature (°C)',25,45],['sleep_duration','Sleep (hours)',0,24],['mood','Mood (0–10)',0,10]];
const symptoms=[['chest_pain','Chest pain'],['collapse','Collapse'],['breathlessness_at_rest','Breathlessness at rest'],['new_confusion','New confusion'],['neurological_signs','New neurological signs'],['sweating','Sweating'],['shaking','Shaking'],['lightheadedness','Lightheadedness'],['fainting','Fainting'],['vision_change','Vision change'],['nausea','Nausea'],['vomiting','Vomiting'],['ecg_alarm','ECG alarm']];
export default function CheckInForm({run,crew,initialCrew,onSaved}){
 const [person,setPerson]=useState(initialCrew),[values,setValues]=useState({}),[findings,setFindings]=useState({});
 const [activity,setActivity]=useState('resting'),[meal,setMeal]=useState('fasting'),[notes,setNotes]=useState('');
 const [username,setUsername]=useState(''),[password,setPassword]=useState(''),[needLogin,setNeedLogin]=useState(false);
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 const [attempt,setAttempt]=useState(null);
 async function submit(e){
  e.preventDefault();setBusy(true);setError('');
  try{
   if(needLogin){await postJSON('session',{username,password});setPassword('');setNeedLogin(false);setAttempt(null);return;}
   const measurements=Object.fromEntries(Object.entries(values).filter(([,v])=>v!=='').map(([k,v])=>[k,Number(v)]));
   const rule_inputs=Object.fromEntries(Object.entries(findings).filter(([,v])=>v!=='').map(([k,v])=>[k,k==='consciousness'?v:k==='headache'?Number(v):v==='true']));
   const payload={run_id:run.id,astronaut_id:person,measurements,rule_inputs,activity,meal_context:meal,notes};
   const fingerprint=JSON.stringify(payload);
   const id=attempt?.fingerprint===fingerprint?attempt.id:crypto.randomUUID();
   setAttempt({fingerprint,id});
   const result=await postJSON('check-ins',{...payload,id});onSaved(result);
  }catch(e){if(e.status===401)setNeedLogin(true);setError(e.message)}finally{setBusy(false)}
 }
 return <><div className="kicker">STORED CREW OBSERVATION</div><h2>{needLogin?'Sign in to record a check-in':'Record a check-in'}</h2><form onSubmit={submit}>
 {needLogin?<><label htmlFor="checkin-user">Username</label><input id="checkin-user" autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)} required/><label htmlFor="checkin-password">Password</label><input id="checkin-password" type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required/></>:<>
 <label htmlFor="checkin-crew">Crew member</label><select id="checkin-crew" value={person} onChange={e=>setPerson(e.target.value)}>{crew.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select>
 <label htmlFor="checkin-activity">Activity at measurement</label><select id="checkin-activity" value={activity} onChange={e=>setActivity(e.target.value)}>{['resting','sleeping','working','exercising','eva'].map(v=><option key={v} value={v}>{v}</option>)}</select>
 <p>Enter only observations you measured or reviewed. Blank fields remain unknown.</p>
 {fields.map(([code,label,min,max])=><React.Fragment key={code}><label htmlFor={`checkin-${code}`}>{label}</label><input id={`checkin-${code}`} type="number" min={min} max={max} step="any" value={values[code]??''} onChange={e=>setValues(old=>({...old,[code]:e.target.value}))}/></React.Fragment>)}
 <label htmlFor="checkin-meal">Glucose context</label><select id="checkin-meal" value={meal} onChange={e=>setMeal(e.target.value)}><option value="fasting">Fasting</option><option value="after_meal">After meal</option></select>
 <label htmlFor="checkin-consciousness">Consciousness</label><select id="checkin-consciousness" value={findings.consciousness??''} onChange={e=>setFindings(old=>({...old,consciousness:e.target.value}))}><option value="">Not reviewed</option>{['alert','new_confusion','voice','pain','unresponsive'].map(v=><option key={v} value={v}>{v.replaceAll('_',' ')}</option>)}</select>
 <label htmlFor="checkin-oxygen">Supplemental oxygen</label><select id="checkin-oxygen" value={findings.supplemental_oxygen??''} onChange={e=>setFindings(old=>({...old,supplemental_oxygen:e.target.value}))}><option value="">Not reviewed</option><option value="true">In use</option><option value="false">Not in use</option></select>
 <label htmlFor="checkin-headache">Headache severity</label><select id="checkin-headache" value={findings.headache??''} onChange={e=>setFindings(old=>({...old,headache:e.target.value}))}><option value="">Not reviewed</option>{[0,1,2,3].map(v=><option key={v} value={String(v)}>{v===0?'0 — None':String(v)}</option>)}</select>
 {symptoms.map(([code,label])=><React.Fragment key={code}><label htmlFor={`finding-${code}`}>{label}</label><select id={`finding-${code}`} value={findings[code]??''} onChange={e=>setFindings(old=>({...old,[code]:e.target.value}))}><option value="">Not reviewed</option><option value="true">Present</option><option value="false">Absent</option></select></React.Fragment>)}
 <label htmlFor="checkin-notes">Notes</label><textarea id="checkin-notes" maxLength={4000} value={notes} onChange={e=>setNotes(e.target.value)}/><p>Saved in mission time and evaluated for alerts. Symptom reports take precedence over simulator defaults for one mission hour. Notes alone do not trigger rules.</p>
 </>}
 {error&&<p role="alert">{error}</p>}<button className="entry-button" type="submit" disabled={busy}>{busy?'Saving…':needLogin?'Sign in':'Save and evaluate'}</button>
 </form></>;
}
