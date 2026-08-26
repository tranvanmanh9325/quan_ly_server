# Frontend Internals & UI Architecture

A technical reference for the React 19 frontend: state management, polling architecture, Sci-Fi HUD interaction layer, Web Audio API sound synthesis, and the parser utility layer.

---

## 1. Frontend State & Polling Architecture

```mermaid
flowchart TD
    subgraph BrowserLifecycle["Browser State & Visibility API"]
        VisState{"document.visibilityState"}
        VisVisible["Tab Visible / Focused"]
        VisHidden["Tab in Background / Hidden"]
        VisState -- "visible" --> VisVisible
        VisState -- "hidden" --> VisHidden
    end

    subgraph PollingEngine["Adaptive Polling Engine (setTimeout Chains)"]
        TimerActive["Active Telemetry Loop (10s)\nPromise.all([CPU, RAM, Disk, Temp, Ports...])"]
        TimerProcesses["Heavy Process Loop (30s)\nps aux --sort=-%cpu"]
        TimerSuspended["Suspend Polling\n(0 Network / SSH Calls)"]
    end

    VisVisible --> TimerActive
    VisVisible --> TimerProcesses
    VisHidden --> TimerSuspended

    subgraph ParsingLayer["Pure Function Parser Layer (parsers.js)"]
        RawSSH["Raw SSH Text Envelopes\n{ data: '...' }"]
        P_CPU["parseCpu() -> % Float"]
        P_RAM["parseRam() -> MB Object"]
        P_Disk["parseDisks() -> Partition Array"]
        P_Net["parseNetwork() -> RX/TX Speeds"]
        P_Proc["parseProcesses() -> Filtered Table"]
        
        RawSSH --> P_CPU
        RawSSH --> P_RAM
        RawSSH --> P_Disk
        RawSSH --> P_Net
        RawSSH --> P_Proc
    end

    TimerActive --> RawSSH
    TimerProcesses --> RawSSH

    subgraph HUDComponents["React 19 Cyberpunk HUD Pages & Modals"]
        C_Overview["OverviewPage (Gauges & Fan HUD)"]
        C_Map["MapPage (D3 3D Orthographic Globe)"]
        C_Terminal["TerminalPage (Web SSH Console)"]
        C_FB["FacebookPage (E2EE Threads & noVNC)"]
        C_TT["TikTokPage (Streaks & DMs)"]
    end

    P_CPU --> C_Overview
    P_RAM --> C_Overview
    P_Disk --> C_Overview
    P_Net --> C_Overview
    P_Proc --> C_Overview
```

---

## 2. Sci-Fi HUD Audio & Canvas Shockwave Pipeline

```mermaid
flowchart LR
    UserClick["User Click / Button Hover / Alert Trigger"] --> EventRouter{"Event Type"}
    
    EventRouter -->|Tactile Click / Laser| WebAudio["Web Audio API Synthesizer\naudioFx.js (Zero Audio Assets)"]
    EventRouter -->|Visual Burst| CanvasShockwave["HTML5 Canvas Layer\nSpaceInteractionLayer.jsx"]
    EventRouter -->|Cursor Track| SVGCrosshair["Dual-Ring Rotating Crosshair\nSVG HUD Cursor"]
    
    subgraph AudioPipeline["Audio Synthesizer Graph"]
        AudioCtx["AudioContext"] --> OscNode["OscillatorNode (Frequency Ramp)"]
        OscNode --> GainNode["GainNode (Exponential Decay)"]
        GainNode --> Destination["Speaker Output (Laser Chirp / Sub-Bass)"]
    end

    WebAudio --> AudioPipeline
    CanvasShockwave --> RenderBurst["Render Glowing Particle Burst & Expanding Neon Shockwave"]
    SVGCrosshair --> RenderCursor["Render Crosshair with Gyro Rotation"]
```

---

## 3. Tech Stack & Directory Structure

| Concern | Library | Version |
| --- | --- | --- |
| UI framework | React | 19 |
| Build tool | Vite | 8 |
| HTTP client | Axios | 1 |
| Charts | Recharts | 3 |
| 3D Globe | D3-geo + TopoJSON | 3 / 3 |
| Icons | Custom Sci-Fi SVG system (`SciFiIcons.jsx`) + Lucide React | latest |
| Audio & FX | Web Audio API + HTML5 Canvas | Native browser APIs |
| Production server | Nginx Alpine | latest |

```text
frontend/src/
├── main.jsx                       ← React DOM entry point — mounts <App /> into #root
├── App.jsx                        ← Root layout, routing outlet, global state & context
├── components/
│   ├── SciFiIcons.jsx             ← Custom SVG vector icon library (SciFiShield, SciFiLightning, etc.)
│   ├── SpaceInteractionLayer.jsx  ← Global rotating crosshair, canvas shockwaves & Web Audio laser FX
│   └── modals/                    ← Process termination, Docker log viewer modals
├── pages/
│   ├── OverviewPage.jsx           ← Real-time telemetry overview, KPI cards & multi-sensor Fan HUD
│   ├── ProcessesPage.jsx          ← Live process monitor, CPU/Mem filters & CSV export
│   ├── ServicesPage.jsx           ← Systemd units, container states, timers & host runtimes
│   ├── ContainersPage.jsx         ← Dedicated Docker container manager & live log streaming
│   ├── TerminalPage.jsx           ← Web SSH Terminal with macro chips & command sandbox
│   ├── MapPage.jsx                ← 3D Interactive Orthographic Globe & active SSH node tracer
│   ├── SecurityPage.jsx           ← Listening ports (ss), active sessions (who), colorized logs
│   ├── FilesPage.jsx              ← Remote SFTP file browser & syntax-highlighted viewer
│   ├── FacebookPage.jsx           ← Facebook E2EE threads, appointment manager & embedded noVNC viewer
│   ├── TikTokPage.jsx             ← TikTok streak keeper, automated DM logs & configuration
│   └── SettingsPage.jsx           ← Alert threshold sliders, polling speed & AI bot controls
└── utils/
    ├── parsers.js                 ← Pure functions: raw SSH text → typed JavaScript objects
    ├── audioFx.js                 ← Synthesized Web Audio laser chirps & sub-bass feedback
    └── api.js                     ← Axios instance with JWT interceptors & error handlers
```
