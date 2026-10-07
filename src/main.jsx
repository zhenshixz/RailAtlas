import React from 'react';
import {createRoot} from 'react-dom/client';
import 'leaflet/dist/leaflet.css';
import './style.css';
import './planner.css';
import './readability.css';
import App from './PlannerApp';
createRoot(document.getElementById('root')).render(<App/>);
