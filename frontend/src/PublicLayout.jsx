import React,{useEffect,useState} from 'react';
import {ArrowUpRight,Moon,Orbit,Sun} from 'lucide-react';

export default function PublicLayout({children,page='home',title='BioOrbit · Astronaut health monitoring'}){
  const [theme,setTheme]=useState(()=>{try{return localStorage.getItem('bioorbit-theme')==='dark'?'dark':'light'}catch{return 'light'}});
  useEffect(()=>{document.documentElement.dataset.theme=theme;try{localStorage.setItem('bioorbit-theme',theme)}catch{}},[theme]);
  useEffect(()=>{document.title=title},[title]);
  return <div id="landing-page" className="landing-page">
    <a className="landing-skip" href="#landing-content">Skip to content</a>
    <header className="landing-header">
      <a className="landing-brand" href="/" aria-label="BioOrbit home"><span className="landing-brand-symbol"><Orbit size={25}/></span>Bio<span>Orbit</span></a>
      <nav aria-label="Main navigation"><a href="/#approach">The approach</a><a href="/documentation" aria-current={page==='documentation'?'page':undefined}>Documentation</a><a href="/resources" aria-current={page==='resources'?'page':undefined}>Resources</a><a href="/about" aria-current={page==='about'?'page':undefined}>About us</a></nav>
      <div className="landing-header-actions"><button className="landing-theme" aria-label={`Switch to ${theme==='dark'?'light':'dark'} mode`} onClick={()=>setTheme(theme==='dark'?'light':'dark')}>{theme==='dark'?<Sun size={18}/>:<Moon size={18}/>}</button><a href="/dashboard" className="landing-nav-cta">Visit dashboard<ArrowUpRight size={16}/></a></div>
    </header>
    <main id="landing-content">{children}</main>
    <footer className="landing-footer"><a className="landing-brand" href="/"><Orbit size={21}/>Bio<span>Orbit</span></a><p>An independent research prototype. Not affiliated with or endorsed by NASA.<br/>Simulated observations. Not for clinical use.</p><div className="public-footer-links"><a href="/documentation">Documentation</a><a href="/resources">Resources</a><a href="/about">About us</a></div></footer>
  </div>;
}
