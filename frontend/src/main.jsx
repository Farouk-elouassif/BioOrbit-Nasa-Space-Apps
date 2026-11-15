import React,{lazy,Suspense} from 'react';
import {createRoot} from 'react-dom/client';
import LandingPage from './LandingPage.jsx';
import './styles.css';
import './readability.css';
import './landing.css';

const Dashboard=lazy(()=>import('./Dashboard.jsx'));
const Documentation=lazy(()=>import('./DocumentationPage.jsx'));
const Resources=lazy(()=>import('./ResourcesPage.jsx'));
const About=lazy(()=>import('./AboutPage.jsx'));
const path=window.location.pathname.replace(/\/+$/,'')||'/';
const pages={'/dashboard':Dashboard,'/documentation':Documentation,'/resources':Resources,'/about':About};
const Page=pages[path]||LandingPage;
createRoot(document.getElementById('root')).render(
  <Suspense fallback={<div className="route-loading" role="status">Opening BioOrbit…</div>}><Page/></Suspense>
);
