import React,{useState} from 'react';
import {ArrowDown,ArrowUpRight} from 'lucide-react';
import PublicLayout from './PublicLayout.jsx';

const systems=[
  {id:'circulation',number:'01',title:'Circulation',label:'Heart rate · blood pressure',note:'Heart rate and blood pressure are shown with personal reference values, activity, and cabin conditions.',point:[245,231]},
  {id:'recovery',number:'02',title:'Rest & recovery',label:'Sleep · mood · workload',note:'Sleep, mood, and workload observations provide a record of changes across mission days.',point:[238,100]},
  {id:'environment',number:'03',title:'Shared environment',label:'Atmosphere · radiation · temperature',note:'Cabin observations provide context for crew readings. Similar symptoms across crew members may warrant a review of the shared environment.',point:[370,310]},
];

function ResearchPlate(){
  const [selected,setSelected]=useState(0);
  const system=systems[selected];
  return <figure className="research-plate">
    <div className="plate-heading"><span>FIG. 01 / HUMAN SYSTEMS</span><span>IN CONTEXT</span></div>
    <div className="plate-illustration">
      <svg viewBox="0 0 480 505" role="img" aria-label="Astronaut health illustration showing circulation, recovery and cabin conditions">
        <defs><pattern id="plate-grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" stroke="currentColor" strokeWidth=".5"/></pattern></defs>
        <rect width="480" height="505" fill="url(#plate-grid)" className="plate-grid"/>
        <g className="plate-orbits" fill="none"><circle cx="240" cy="253" r="187"/><circle cx="240" cy="253" r="150" strokeDasharray="2 7"/><ellipse cx="240" cy="253" rx="210" ry="79" transform="rotate(-31 240 253)"/><path d="M240 36V467M29 253H451" strokeDasharray="4 8"/></g>
        <g className="plate-calibration"><path d="M31 47h15M31 47v15M449 47h-15M449 47v15M31 458h15M31 458v-15M449 458h-15M449 458v-15"/><path d="M80 480h320"/>{Array.from({length:17},(_,i)=><path key={i} d={`M${80+i*20} 480v${i%4===0?9:4}`}/>)}</g>
        <g className="plate-human" strokeLinejoin="round" strokeLinecap="round">
          <path className="human-fill" d="M240 64C219 64 208 80 210 101L215 122 223 133 222 151C213 159 193 161 181 168 169 177 163 199 156 219L136 276 123 321 115 347 119 355 126 351 138 328 143 315 148 308 146 330 151 333 160 307 159 292 171 261 186 227 191 260 190 284 182 316 186 350 195 389 194 429 190 451 196 460 217 459 219 452 214 436 215 393 221 354 230 310 240 301 250 310 259 354 265 393 266 436 261 452 263 459 284 460 290 451 286 429 285 389 294 350 298 316 290 284 289 260 294 227 309 261 321 292 320 307 329 333 334 330 332 308 337 315 342 328 354 351 361 355 365 347 357 321 344 276 324 219C317 199 311 177 299 168 287 161 267 159 258 151L257 133 265 122 270 101C272 80 261 64 240 64Z"/>
          <path d="M222 151Q240 163 258 151M191 183Q212 187 234 175M289 183Q268 187 246 175M240 167V284M199 214Q218 220 235 213M281 214Q262 220 245 213M202 236Q219 241 235 236M278 236Q261 241 245 236M204 257Q221 260 235 254M276 257Q259 260 245 254M195 282Q240 268 285 282M191 300Q215 284 230 310M289 300Q265 284 250 310M198 320L207 380 204 424M282 320L273 380 276 424M186 190L169 241 146 297M294 190L311 241 334 297"/>
          <path d="M220 90Q240 79 260 90M221 107Q240 116 259 107M229 123Q240 129 251 123" opacity=".45"/>
          <path className={`plate-organ ${selected===0?'is-active':''}`} d="M246 214C234 199 225 212 229 224 233 237 247 244 247 244S262 231 261 220C260 210 251 207 246 214Z"/>
          <path className={`plate-organ ${selected===1?'is-active':''}`} d="M223 84C219 75 230 70 236 74 242 66 255 72 254 80 266 84 261 96 254 97 250 106 240 101 238 96 229 103 219 96 223 90Z"/>
        </g>
        <g className="plate-environment" fill="none"><path d="M344 302h47m-40 10h32m-38 10h42"/><circle cx="366" cy="270" r="5"/><path d="M366 258v-6m0 36v-6m-12-12h-6m36 0h-6"/></g>
        <path className="plate-leader" d={`M${system.point[0]} ${system.point[1]}H405V${selected===1?100:380}`} fill="none"/>
        <circle className="plate-focus-ring" cx={system.point[0]} cy={system.point[1]} r="12"/>
        <circle className="plate-focus" cx={system.point[0]} cy={system.point[1]} r="4"/>
        <text x="35" y="33" className="plate-svg-label">ANTERIOR VIEW</text><text x="445" y="33" textAnchor="end" className="plate-svg-label">BIO / ORBIT</text>
        <text x="405" y={selected===1?90:402} textAnchor="end" className="plate-svg-label plate-label-active">{system.number} / {system.title.toUpperCase()}</text>
      </svg>
    </div>
    <div className="plate-system-tabs" role="group" aria-label="Explore human systems">{systems.map((item,i)=><button key={item.id} aria-pressed={selected===i} onClick={()=>setSelected(i)}><span>{item.number}</span>{item.title}</button>)}</div>
    <figcaption aria-live="polite"><span>{system.label}</span><p>{system.note}</p><small>Concept illustration · Explore recorded observations in the dashboard</small></figcaption>
  </figure>;
}

export default function LandingPage(){
  return <PublicLayout>

      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-hero-copy"><div className="landing-eyebrow"><span/>LONG-DURATION MISSIONS / CREW HEALTH CONSOLE</div>
          <h1 id="landing-title">Health monitoring<br/>for astronauts<span>.</span></h1>
          <p className="landing-intro">A software prototype for long-duration missions.</p>
          <p className="landing-description">BioOrbit gathers health indicators and cabin observations for astronauts to review during a mission. It displays personal references, recorded trends, and alerts with supporting evidence, recheck times, and workbook guidance.</p>
          <div className="landing-hero-actions"><a href="/dashboard" className="landing-primary-cta">Visit dashboard<ArrowUpRight size={19}/></a><a href="#approach" className="landing-text-link">Project overview<ArrowDown size={16}/></a></div>
          <div className="landing-prototype-note"><span className="landing-note-marker"/>Monitoring prototype<span className="landing-note-divider">/</span>Simulated mission data</div>
          <a className="landing-research-credit" href="https://www.nasa.gov/hrp/" target="_blank" rel="noreferrer">Research context: NASA Human Research Program<ArrowUpRight size={13}/></a>
        </div>
        <ResearchPlate/>
      </section>
      <div className="landing-index-strip"><span>THE PERSON</span><i/><span>THE MISSION DAY</span><i/><span>THE ENVIRONMENT</span><span className="landing-strip-note">Individual observations / Mission time / Cabin conditions</span></div>
      <section id="approach" className="landing-approach" aria-labelledby="approach-title">
        <div className="landing-section-intro"><span className="landing-eyebrow">01 / PROJECT OVERVIEW</span><h2 id="approach-title">Monitoring health<br/>during a mission.</h2><p>Long-duration missions expose astronauts to radiation, isolation and confinement, altered gravity, and a hostile closed environment. These conditions can affect immunity, bone health, cardiovascular function, and mental wellbeing. Astronauts carry much of the responsibility for noticing changes in themselves.</p><p>The project addresses the challenge of gathering health indicators and enabling astronauts to evaluate and act on their health status. The current prototype combines a body map, personal baselines, trends, cabin readings, alerts, and crew check-ins.</p></div>
        <div className="landing-methods">
          <article><span className="landing-method-number">01</span><div><h3>Personal references</h3><p>Core indicators, including heart rate, blood pressure, glucose, temperature, sleep, and mood, are displayed alongside available personal preflight references.</p><span>Personal baselines / Core indicators</span></div></article>
          <article><span className="landing-method-number">02</span><div><h3>Recorded trends</h3><p>Charts show observations across mission time, with sleep grouped by day. Missing time buckets remain visible as gaps.</p><span>Mission timeline / Recorded trends</span></div></article>
          <article><span className="landing-method-number">03</span><div><h3>Cabin observations</h3><p>Cabin pressure, oxygen, carbon dioxide, temperature, and radiation are displayed alongside crew observations to provide environmental context.</p><span>Habitat conditions / Shared exposure</span></div></article>
          <article><span className="landing-method-number">04</span><div><h3>Alerts and check-ins</h3><p>Alerts include their trigger, recorded evidence, workbook guidance, reference recipients, and a recheck deadline. Signed-in crew members can record symptoms and measurements; acknowledgment records that an alert has been reviewed.</p><span>Alert evidence / Guidance / Crew check-ins</span></div></article>
        </div>
      </section>
      <section id="research" className="landing-research" aria-labelledby="research-title">
        <div className="landing-section-intro"><span className="landing-eyebrow">02 / RESEARCH BACKGROUND</span><h2 id="research-title">Spaceflight health<br/>and performance.</h2><p>NASA’s human research resources describe the health and performance risks of spaceflight. These sources provide background for the biological topics and environmental conditions represented in BioOrbit.</p><p className="landing-source-note">Research informs the background. This prototype uses simulated mission observations; it does not diagnose conditions or replace approved mission medical procedures.</p></div>
        <div className="landing-sources">
          <a href="https://www.nasa.gov/hrp/" target="_blank" rel="noreferrer"><div><span>NASA / PROGRAM OVERVIEW</span><h3>Human Research Program</h3><p>Research into how people live and work in space.</p></div><ArrowUpRight size={22}/></a>
          <a href="https://www.nasa.gov/hrp/hazards/" target="_blank" rel="noreferrer"><div><span>NASA / ENVIRONMENTAL CONTEXT</span><h3>Five hazards of human spaceflight</h3><p>Radiation, isolation, distance, gravity, and closed environments.</p></div><ArrowUpRight size={22}/></a>
          <a href="https://humanresearchroadmap.nasa.gov/evidence/" target="_blank" rel="noreferrer"><div><span>NASA / HUMAN RESEARCH ROADMAP</span><h3>The evidence behind the risks</h3><p>Evidence reports on human health and performance.</p></div><ArrowUpRight size={22}/></a>
        </div>
      </section>
      <section className="landing-entry" aria-labelledby="entry-title"><div><span className="landing-eyebrow">03 / PROTOTYPE CONSOLE</span><h2 id="entry-title">The crew console.</h2><p>The dashboard contains the body map, measurement history, cabin conditions, alert evidence, and crew check-in form.</p></div><a href="/dashboard" className="landing-primary-cta">Visit dashboard<ArrowUpRight size={20}/></a><span className="landing-entry-coordinate" aria-hidden="true">BIOORBIT / HUMAN SYSTEMS</span></section>

  </PublicLayout>;
}
