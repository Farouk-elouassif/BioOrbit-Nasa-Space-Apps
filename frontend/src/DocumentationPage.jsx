import React,{useMemo,useState} from 'react';
import {ArrowRight,ArrowUpRight,BookOpen,Search} from 'lucide-react';
import PublicLayout from './PublicLayout.jsx';
import {chapters} from './biologyContent.js';
import atlas from './measurementAtlas.json';
import bibliography from './references.json';
import './knowledge.css';

const glossary=[
  ['Baseline','A set of reference observations for an individual and period. It describes that reference; it is not automatically a clinical normal range.'],
  ['Partial pressure','The pressure contribution of a gas within a mixture. It must not be substituted for a concentration percentage.'],
  ['SpO₂','An optical estimate of peripheral haemoglobin oxygen saturation, rather than a direct measurement of tissue oxygen delivery.'],
  ['ETCO₂','Carbon dioxide measured near the end of an exhaled breath. It differs from environmental CO₂.'],
  ['HRV / RMSSD','Heart-rate variability describes variation between beat intervals. RMSSD is one calculation used to summarize that variation.'],
  ['Circadian alignment','The relationship between biological timing and the scheduled sleep–wake cycle.'],
  ['SANS','Spaceflight-associated neuro-ocular syndrome: a constellation of eye findings associated with spaceflight, with an incompletely established mechanism.'],
  ['Dose rate / cumulative dose','Exposure per unit time versus exposure accumulated over a specified period. Always preserve the unit and accumulation window.'],
  ['NEWS2','A clinical early-warning scoring system. Its space-adjusted use in BioOrbit is an unvalidated prototype adaptation.'],
  ['Ground analog','An Earth-based experimental model, such as bed rest or isolation, used to investigate selected aspects of spaceflight.'],
];
function SourceLinks({chapter}){
  return <div className="biology-sources"><span>Further reading</span>{chapter.refs.map(id=>{const ref=bibliography.references.find(item=>item.id===id);return <a key={id} href={`/resources#${id}`}><span>{id.slice(4)}</span>{ref.title}<ArrowUpRight size={12}/></a>})}{chapter.extraSources?.map(source=><a key={source.url} href={source.url} target="_blank" rel="noreferrer"><span>+</span>{source.title} · additional background<ArrowUpRight size={12}/></a>)}</div>;
}
function MeasurementAtlas(){
  const [query,setQuery]=useState(''),[domain,setDomain]=useState('all');
  const records=useMemo(()=>{
    const words=query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    return atlas.filter(record=>(domain==='all'||record.domain===domain)&&words.every(word=>`${record.label} ${record.unit} ${record.biology} ${record.code} ${record.chapter}`.toLowerCase().includes(word)));
  },[query,domain]);
  return <section id="measurement-atlas" className="biology-chapter">
    <span className="landing-eyebrow">14 / MEASUREMENT ATLAS</span><h2>What each observation represents.</h2><p>A biological field guide to all {atlas.length} configured measurement types. A configured type does not mean a measurement has been collected or is shown for every crew member. Units below are the units declared by this prototype, not clinical reference ranges.</p>
    <div className="atlas-controls"><div className="library-search"><Search size={18}/><label className="sr-only" htmlFor="atlas-search">Find a measurement</label><input id="atlas-search" type="search" value={query} onChange={e=>setQuery(e.target.value)} placeholder="Find a measurement, unit, or biological process…"/></div><label className="sr-only" htmlFor="atlas-domain">Measurement domain</label><select id="atlas-domain" value={domain} onChange={e=>setDomain(e.target.value)}><option value="all">All observations</option><option value="astronaut">Crew observations</option><option value="cabin">Cabin observations</option></select></div>
    <p className="atlas-result-count" role="status">{records.length} of {atlas.length} measurement types</p>
    <div className="measurement-atlas">{records.map(record=><details key={record.code}><summary><span>{record.label}</span><small>{record.unit}</small></summary><div><span className="atlas-domain-label">{record.domain==='cabin'?'CABIN / ENVIRONMENT':'CREW / PHYSIOLOGY'}</span><p>{record.biology}</p><a className="knowledge-inline-link" href={`#${record.chapter}`}>Read the biological context<ArrowRight size={13}/></a></div></details>)}</div>
    {!records.length&&<p>No matching measurement. Try a broader term or another domain.</p>}
  </section>;
}
export default function DocumentationPage(){
  return <PublicLayout page="documentation" title="Biology documentation · BioOrbit">
    <section className="knowledge-hero"><div><span className="landing-eyebrow">THE FIELD GUIDE / DOCUMENTATION</span><h1>The biology behind<br/>the observations.</h1><p>Understand what changes in spaceflight, what each measurement represents, and where interpretation needs more evidence.</p></div><a className="knowledge-inline-link" href="/resources"><BookOpen size={18}/>Explore the bibliography<ArrowUpRight size={16}/></a></section>
    <div className="documentation-layout"><aside className="documentation-toc"><h2>In this guide</h2><nav aria-label="Documentation contents">{chapters.map((chapter,i)=><a href={`#${chapter.id}`} key={chapter.id}><span>{String(i+1).padStart(2,'0')}</span>{chapter.title}</a>)}<a href="#measurement-atlas"><span>14</span>Measurement atlas</a><a href="#glossary"><span>15</span>Terms & abbreviations</a></nav><a className="knowledge-inline-link" href="/dashboard">Open the dashboard<ArrowUpRight size={14}/></a></aside>
      <div className="documentation-body"><div className="biology-introduction"><span>READING NOTE</span><p>This guide explains the biology and the prototype’s interpretation model. Source links lead to entries from the supplied bibliography; additional clinical background is identified separately. It is educational context, not an individual assessment or treatment protocol.</p></div>
        {chapters.map(chapter=><section id={chapter.id} className="biology-chapter" key={chapter.id}><span className="landing-eyebrow">{chapter.eyebrow}</span><h2>{chapter.title}</h2>{chapter.paragraphs.map((paragraph,i)=><p key={i}>{paragraph}</p>)}<div className="biology-takeaway"><h3>In the research view</h3><p>{chapter.takeaway}</p></div><SourceLinks chapter={chapter}/></section>)}
        <MeasurementAtlas/>
        <section id="glossary" className="biology-chapter"><span className="landing-eyebrow">15 / TERMS & ABBREVIATIONS</span><h2>A shared vocabulary.</h2><dl className="biology-glossary">{glossary.map(([term,definition])=><div key={term}><dt>{term}</dt><dd>{definition}</dd></div>)}</dl></section>
        <div className="documentation-next"><div><span className="landing-eyebrow">KEEP THE SOURCE CLOSE</span><h2>Go back to the evidence.</h2><p>Read the original study methods, populations, and limitations in the reference library.</p></div><a href="/resources">Browse resources<ArrowUpRight size={18}/></a></div>
      </div>
    </div>
  </PublicLayout>;
}
