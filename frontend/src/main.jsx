import React,{lazy,Suspense} from 'react';
import {createRoot} from 'react-dom/client';
import LandingPage from './LandingPage.jsx';
import './styles.css';
import './readability.css';
import './landing.css';

const Dashboard=lazy(()=>import('./Dashboard.jsx'));
const isDashboard=window.location.pathname.replace(/\/+$/,'')==='/dashboard';
createRoot(document.getElementById('root')).render(
  isDashboard?<Suspense fallback={<div className="route-loading" role="status">Opening the research console…</div>}><Dashboard/></Suspense>:<LandingPage/>
);
