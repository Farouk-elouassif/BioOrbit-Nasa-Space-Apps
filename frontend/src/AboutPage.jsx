import React from 'react';
import {ArrowUpRight,Braces,Mail,Microscope} from 'lucide-react';
import PublicLayout from './PublicLayout.jsx';
import './about.css';

const team=[
  {
    name:'Farouk El Ouassif',initials:'FE',role:'Data & Software Engineer',Icon:Braces,
    focus:'AI-driven applications · Data pipelines · Software architecture',
    paragraphs:[
      'Farouk El Ouassif is a Data and Software Engineer specializing in AI-driven applications, scalable data pipelines, and intelligent software systems. His work combines backend development, data engineering, and machine learning to turn complex data into reliable software solutions.'
    ],
    expertise:['Data engineering','Backend development','Software engineering'],
    email:'elouassiffarouk@gmail.com',
    links:[{label:'LinkedIn',url:'https://www.linkedin.com/in/farouk-el-ouassif/'}]
  },
  {
    name:'Dr. Abdenacer Benchrifa',initials:'AB',role:'Biomedical Researcher',Icon:Microscope,
    focus:'Medical biotechnology',
    paragraphs:[
      'Dr. Abdenacer Benchrifa is a Moroccan biomedical researcher specializing in medical biotechnology and diagnostic innovation. He develops rapid, low-cost diagnostic kits for infectious diseases and cancer, with the aim of making reliable testing accessible to more patients and healthcare systems.'
    ],
    expertise:['Molecular research','Biomedical engineering'],
    email:'abdenacer.benchrifa@gmail.com',
    links:[
      {label:'LinkedIn',url:'https://www.linkedin.com/in/a-benchrifa/'},
      {label:'ResearchGate',url:'https://www.researchgate.net/profile/Abdenacer-Benchrifa-2'},
      {label:'SciProfiles',url:'https://sciprofiles.com/profile/nacer'},
      {label:'ORCID',url:'https://orcid.org/0009-0009-1456-4046'}
    ]
  }
];

export default function AboutPage(){
  return <PublicLayout page="about" title="About us · BioOrbit">
    <section className="about-hero" aria-labelledby="about-title">
      <span className="landing-eyebrow">ABOUT US / THE PEOPLE BEHIND BIOORBIT</span>
      <h1 id="about-title">Two disciplines.<br/>One shared project.</h1>
      <p>BioOrbit was built by Farouk El Ouassif and Abdenacer Benchrifa, bringing software and data engineering together with biomedical research to explore human health in spaceflight.</p>
      <div className="about-disciplines"><span><Braces size={17} aria-hidden="true"/>Engineering</span><span className="about-connection" aria-hidden="true"/><span><Microscope size={17} aria-hidden="true"/>Biomedical research</span></div>
    </section>
    <section className="about-team" aria-labelledby="team-title">
      <div className="about-section-heading"><span className="landing-eyebrow">MEET THE TEAM</span><h2 id="team-title">The people behind the work.</h2></div>
      <div className="about-profiles">{team.map(({name,initials,role,Icon,focus,paragraphs,expertise,email,links})=><article className="about-profile" key={name} aria-label={name}>
        <div className="about-profile-heading"><span className="about-monogram" aria-hidden="true">{initials}</span><Icon size={25} aria-hidden="true"/></div>
        <p className="about-role">{role}</p><h3>{name}</h3><p className="about-focus">{focus}</p>
        <div className="about-bio">{paragraphs.map(paragraph=><p key={paragraph}>{paragraph}</p>)}</div>
        <ul className="about-expertise" aria-label={`${name} expertise`}>{expertise.map(item=><li key={item}>{item}</li>)}</ul>
        <div className="about-contact" aria-label={`${name} contact and profiles`}>
          <a className="about-email" href={`mailto:${email}`}><Mail size={16} aria-hidden="true"/><span>{email}</span></a>
          <div className="about-social-links">{links.map(link=><a key={link.url} href={link.url} target="_blank" rel="noopener noreferrer" aria-label={`${name} on ${link.label} (opens in a new tab)`}>{link.label}<ArrowUpRight size={14} aria-hidden="true"/></a>)}</div>
        </div>
      </article>)}</div>
    </section>
    <section className="about-project"><div><span className="landing-eyebrow">EXPLORE OUR WORK</span><h2>From biological context<br/>to recorded observations.</h2><p>Explore the research behind BioOrbit or open the console to see the project in action.</p></div><div className="about-project-links"><a href="/documentation">Read the biology guide<ArrowUpRight size={18}/></a><a href="/dashboard">Visit the dashboard<ArrowUpRight size={18}/></a></div></section>
  </PublicLayout>;
}
