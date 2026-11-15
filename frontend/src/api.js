import { useCallback, useEffect, useState } from 'react';

export function apiUrl(resource,params={}) {
  const query=new URLSearchParams(Object.entries(params).filter(([,v])=>v!==null&&v!==undefined&&v!==''));
  return `/api/v1/${resource}${query.size?'?'+query:''}`;
}
export async function readJSON(url,signal) {
  const controller=new AbortController();
  const cancel=()=>controller.abort();
  if(signal?.aborted)cancel();
  signal?.addEventListener('abort',cancel,{once:true});
  const timer=setTimeout(cancel,10000);
  try {
    const response=await fetch(url,{signal:controller.signal,headers:{Accept:'application/json'},cache:'no-store'});
    let data;
    try { data=await response.json(); }
    catch { throw new Error('The data service returned an unexpected response. Please retry.'); }
    if(!response.ok)throw new Error(data.message||`Backend request failed (${response.status}).`);
    return data;
  } finally {clearTimeout(timer);signal?.removeEventListener('abort',cancel);}
}
export function useRemote(url,interval=5000) {
  const [state,setState]=useState({key:null,data:null,error:null,loading:true});
  const [revision,setRevision]=useState(0);
  const refresh=useCallback(()=>setRevision(v=>v+1),[]);
  useEffect(()=>{
    if(!url){setState({key:url,data:null,error:null,loading:false});return;}
    let cancelled=false,timer;
    const controller=new AbortController();
    setState(old=>old.key===url?{...old,loading:!old.data}:{key:url,data:null,error:null,loading:true});
    async function poll(){
      try {
        const data=await readJSON(url,controller.signal);
        if(!cancelled)setState({key:url,data,error:null,loading:false,receivedAt:new Date().toISOString()});
      } catch(error){
        if(!cancelled)setState(old=>({...old,key:url,error:error.name==='AbortError'?'Backend request timed out. Retrying…':error.message,loading:false}));
      } finally {if(!cancelled&&interval)timer=setTimeout(poll,interval);}
    }
    poll();
    return()=>{cancelled=true;controller.abort();clearTimeout(timer)};
  },[url,interval,revision]);
  return {...(state.key===url?state:{data:null,error:null,loading:!!url}),refresh};
}
export function useSeries({runId,metric,astronautId,habitatId,zoneId,window='7d',domain='astronaut'}){
  return useRemote(runId&&metric&&(astronautId||habitatId)?apiUrl('trends',{
    run_id:runId,metric,astronaut_id:astronautId,habitat_id:habitatId,zone_id:zoneId,window,domain,
  }):null,15000);
}

export async function acknowledgeAlert(alert){
  const cookie=document.cookie.split(';').map(v=>v.trim()).find(v=>v.startsWith('csrftoken='));
  const csrf=cookie?decodeURIComponent(cookie.slice('csrftoken='.length)):'';
  const response=await fetch(`/api/v1/alerts/${alert.id}/acknowledge`,{
    method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},
    body:JSON.stringify({tier:alert.tier}),
  });
  let data;try{data=await response.json()}catch{throw new Error('Acknowledgment failed. Refresh the mission data and try again.');}
  if(!response.ok)throw new Error(data.message||`Acknowledgment failed (${response.status}).`);
  return data;
}

export async function postJSON(resource,payload){
  // GET establishes CSRF before first login; login may rotate it for later writes.
  if(!document.cookie.split(';').some(v=>v.trim().startsWith('csrftoken=')))await readJSON(apiUrl('session'));
  const cookie=document.cookie.split(';').map(v=>v.trim()).find(v=>v.startsWith('csrftoken='));
  const csrf=cookie?decodeURIComponent(cookie.slice('csrftoken='.length)):'';
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),10000);
  try{
    const response=await fetch(apiUrl(resource),{method:'POST',credentials:'same-origin',signal:controller.signal,headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify(payload)});
    let data;
    try{data=await response.json()}catch{
      const message=response.status===404
        ?'The API endpoint is unavailable (404). Update and restart the backend, then retry.'
        :response.status===403
          ?'The server rejected this request (403). Refresh the page to renew your session, then retry.'
          :`The server returned an unexpected response (HTTP ${response.status}). Retry the same report.`;
      const error=new Error(message);error.status=response.status;throw error;
    }
    if(!response.ok){const error=new Error(data.message||`Save failed (${response.status}).`);error.status=response.status;throw error;}
    return data;
  }catch(error){
    if(error.name==='AbortError')throw new Error('Saving timed out. Retry the same report; duplicate observations will not be created.');
    throw error;
  }finally{clearTimeout(timer)}
}
