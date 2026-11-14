# BioOrbit crew console

React + Vite frontend with a shared view of all four crew members. No login or account flow.

Run manually from the project root:

```bash
cd frontend
npm install
npm run dev
```

Production validation:

```bash
npm run build
```

Features: selectable crew roster, six-indicator readings, whole-crew comparison, metric trend dialogs, recovery visualization, habitat dashboard, advisory acknowledgment, and check-ins for any crew member with a shared observation log.

All telemetry, personal reference values, charts, cabin locations, and mission clocks are illustrative. Check-ins update the selected person's readings and the crew comparison in React memory; reload clears observations and acknowledgment. The overview sleep chart remains seeded demonstration history. No backend integration, login, offline cache, or persistent storage is configured. Fonts load from Google Fonts with system fallbacks.

The human systems map uses Three.js for a procedural, rotatable 3D mannequin with twelve clickable anatomical points and a habitat control. Region readings follow the selected crew member and session check-ins. Regions without supplied data explicitly show availability. This is a stylized visualization, not a medical anatomical model. WebGL-unavailable browsers retain the full region picker. After updating, run `npm install` manually to install the new `three` dependency before starting Vite.
