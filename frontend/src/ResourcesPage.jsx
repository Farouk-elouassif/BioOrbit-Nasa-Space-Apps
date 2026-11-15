import React,{useEffect,useMemo,useState} from 'react';
import {ArrowUpRight,Download,Search,X} from 'lucide-react';
import PublicLayout from './PublicLayout.jsx';
import bibliography from './references.json';
import {searchReferences} from './referenceSearch.js';
import './knowledge.css';

const shortGroupNames=['NASA standards & briefs','NASA technical reports','Open science datasets','Journal studies','Partners, industry & news','Clinical references','Hackathon materials'];
export default function ResourcesPage(){
  const [query,setQuery]=useState(''),[group,setGroup]=useState('all');
  const matches=useMemo(()=>searchReferences(bibliography.references,query,group),[query,group]);
  useEffect(()=>{const hash=window.location.hash.slice(1);if(hash){const frame=requestAnimationFrame(()=>document.getElementById(hash)?.scrollIntoView());return()=>cancelAnimationFrame(frame)}},[]);
  return <PublicLayout page="resources" title="Resources · BioOrbit">
    <section className="knowledge-hero"><div><span className="landing-eyebrow">THE READING ROOM / RESOURCES</span><h1>The research,<br/>within reach.</h1><p>A reference library for the biology, environments, and measurements behind BioOrbit. Browse the bibliography supplied by the project team.</p></div><a className="knowledge-download" href="/downloads/References.docx" download><Download size={18}/><span>Download the bibliography<small>References.docx · Original document</small></span></a></section>
    <div className="library-layout">
      <aside className="library-sidebar"><h2>Browse the collection</h2><div className="library-categories" role="group" aria-label="Reference categories"><button aria-pressed={group==='all'} onClick={()=>setGroup('all')}>All references<span>{bibliography.references.length}</span></button>{bibliography.groups.map((category,i)=><button key={category.id} aria-pressed={group===category.id} onClick={()=>setGroup(category.id)}>{shortGroupNames[i]}<span>{bibliography.references.filter(r=>r.groupId===category.id).length}</span></button>)}</div><p>From <strong>References.docx</strong></p><p>{bibliography.attribution}</p><a href="/documentation" className="knowledge-inline-link">Read the biology guide<ArrowUpRight size={14}/></a></aside>
      <section className="reference-library" aria-label="Research references">
        <div className="library-search"><Search size={19}/><label className="sr-only" htmlFor="reference-search">Search titles, authors, dates or study IDs</label><input id="reference-search" type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="Search titles, authors, dates, or study IDs…"/>{query&&<button onClick={()=>setQuery('')} aria-label="Clear reference search"><X size={17}/></button>}</div>
        <div className="library-result-heading"><p role="status" aria-live="polite">{matches.length} of {bibliography.references.length} references</p>{(query||group!=='all')&&<button onClick={()=>{setQuery('');setGroup('all')}}>Reset filters</button>}</div>
        <p className="library-editorial-note">Citations and source links are preserved from the supplied bibliography. Dates and editions reflect that document; a publisher may serve a newer revision. A listed source is not evidence that its dataset is connected to the dashboard.</p>
        {matches.map(ref=><article className="reference-entry" id={ref.id} key={ref.id}><span className="reference-number">{ref.id.slice(4)}</span><div><div className="reference-entry-meta"><span>{shortGroupNames[bibliography.groups.findIndex(g=>g.id===ref.groupId)]}</span><span>{ref.format}</span></div><h2>{ref.url?<a href={ref.url} target="_blank" rel="noreferrer">{ref.title}<ArrowUpRight size={17}/></a>:ref.title}</h2><details><summary>Full citation</summary><p>{ref.citation}</p></details>{!ref.url&&<p className="reference-missing-link">No URL was supplied for this entry.</p>}</div></article>)}
        {!matches.length&&<div className="library-empty"><h2>No matching references.</h2><p>Try a broader term, an author’s name, or another category.</p><button onClick={()=>{setQuery('');setGroup('all')}}>Show all references</button></div>}
      </section>
    </div>
  </PublicLayout>;
}
