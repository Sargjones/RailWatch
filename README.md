[README.md](https://github.com/user-attachments/files/30056400/README.md)
[README.md](https://github.com/user-attachments/files/28936572/README.md)
# RailWatch Canada

**Corridor intelligence for Canada's freight rail network.**
A public infrastructure intelligence platform — part of the [Critical TO](https://criticalto.ca) family.

🚂 **Live dashboard:** [rail.criticalto.ca](https://rail.criticalto.ca)  
📡 **Data repo:** [RailWatch](https://github.com/Sargjones/RailWatch) (auto-updated daily via GitHub Actions)  
📋 **Submit an observation:** [Open an issue](https://github.com/Sargjones/railwatch-observations/issues/new?template=observation.md)

---

## What this is

RailWatch documents dangerous goods movement on Canada's freight rail network using public data and community observations. It exists because of a transparency gap: under Canada's Transportation of Dangerous Goods Act, freight railroads are only required to notify provincial fusion centres — not the communities the trains pass through.

A community observer watching sodium hypochlorite cars roll through a CN station has no legitimate path to know where they're going, who shipped them, or why. RailWatch doesn't claim to solve that gap — it documents it and builds the infrastructure for when transparency improves.

---

## Coverage

**Pilot corridor (deepest monitoring):** CN Dundas Subdivision — the Toronto–Windsor corridor, originally built by the Great Western Railway in 1853. Passes through Toronto, Hamilton, Woodstock, London, and Windsor, carrying a significant volume of industrial chemicals, agricultural products, and petroleum products daily.

**Province-wide (as of 15 Jul 2026):** RailWatch now registers all CN and Ontario Northland subdivisions covered by our existing corridor geometry — 25 subdivisions across southern, central, and northwestern Ontario, organized into three monitoring tiers by traffic density and reporting redundancy. See `railwatch_corridors_on.json`. Monitoring depth varies by tier: Tier 1 (southern Ontario) gets the full TDG/observation/correlation treatment; Tier 2–3 (transcontinental main line through central and northwestern Ontario) currently get Fire Watch coverage only, with other layers to follow.

---

## Fire Watch

**New module, launched 15 Jul 2026.** Fire Watch tracks wildfire activity intersecting Ontario rail corridors — service suspensions, crew evacuations, and TDG-relevant exposure where trains carrying dangerous goods are halted or rerouted by fire.

It exists for the same reason the rest of RailWatch does: the first public signal of a hazmat-adjacent rail emergency is often a viral video, not a structured disclosure. The seed incident (`FW-2026-001`) is exactly that — three CN trains halted by wildfire on the Allanwater Subdivision near Armstrong, ON, with crew evacuated and the event only reaching the public through a crew member's cellphone footage. The same subdivision was the site of a 2009 TSB-investigated derailment/fire involving sodium chlorate and propane tank cars (R09W0033) — a reminder this isn't a one-off risk profile for that corridor.

- **Data:** `railwatch_firewatch.json`
- **Pipeline (in progress):** `scraper/railwatch_firewatch.py` — currently a scaffolded pipeline (fetch → buffer → intersect → flag → enrich → write) with the corridor-loading and incident-write stages working, but the CWFIS/Ontario active-fire fetch stage not yet wired up. Incidents are captured manually until that's automated. See the module docstring for the planned data sources.
- **Priority:** Tier 3 subdivisions (remote transcontinental main line through unorganized territory) — the combination of long single-track exposure and minimal redundant public reporting is exactly the gap this module is meant to close.

---

## Data sources (all open/public)

| Source | What we use | Update frequency |
|--------|------------|-----------------|
| [TSB Rail Occurrence Database](https://www.tsb-bst.gc.ca/eng/stats/rail/) | All rail incidents 1983–present | Annual |
| [Transport Canada TDG Schedule 1](https://open.canada.ca/data/en/dataset/197260f1-b5dc-4f53-a036-2541cff379eb) | Full dangerous goods classification lookup | As published |
| [TC Weekly Freight Performance](https://tdih-cdit.tc.canada.ca/en) | CN/CP network performance indicators | Weekly |
| [OpenStreetMap Overpass API](https://overpass-api.de) | Corridor geometry | On demand |
| Community observations | Placard sightings via GitHub Issues | Continuous |

---

## What we cannot show (yet)

Real-time car positions, cargo manifests, shipper/consignee data, and bill of lading information are held by CN and CPKC under commercial confidentiality. Access requires:

- Carrier partnership agreements (CN/CPKC API programs require shipper relationship)
- Railinc industry membership (RailSight car tracking)
- Access to Information requests to Transport Canada for corridor-level hazmat flow data

RailWatch is pursuing these through formal channels.

---

## Repository structure

```
railwatch/
├── railwatch_scraper.py          # Python data scraper (runs via GitHub Actions)
├── railwatch_firewatch.py        # Fire Watch pipeline (scaffolded, fetch stage pending)
├── railwatch_dashboard.html      # Single-file dashboard (deployed to gh-pages)
├── .github/
│   ├── workflows/scrape.yml      # Daily scrape automation
│   └── ISSUE_TEMPLATE/
│       └── observation.md        # Community observation submission template
└── README.md
```

**Data outputs** (written to `gh-pages` branch automatically):
- `railwatch_data_latest.json` — current day's data
- `railwatch_data_YYYYMMDD.json` — daily archive
- `railwatch_tdg.json` — TDG Schedule 1 lookup table
- `railwatch_corridors_on.json` — province-wide corridor/tier registry
- `railwatch_firewatch.json` — Fire Watch incidents

---

## Corridor tiers

Full registry: `railwatch_corridors_on.json`

- **Tier 1 — Southern Ontario:** CN Dundas ✅ Pilot · CN Chatham 🔲 · CPKC Windsor 🔲 · CN Halton 🔲 · CN Oakville, Kingston, Grimsby ✅ Active
- **Tier 2 — Central/Northeastern Ontario:** CN Bala, Vankleek, Parry Sound, North Bay, Cartier, Ruel, Soo · ONT Temagami, Devonshire, Ramore
- **Tier 3 — Northwestern/remote Ontario:** CN Kashabowie, Allanwater, Fort Frances, Sprague · ONT Iroquois Falls, Island Falls, Kapuskasing, Pagwa — **Fire Watch priority tier**

---

## Part of Critical TO

RailWatch shares its scraper architecture, threshold-alert logic, and design system with:
- [Toronto Infrastructure Intelligence](https://criticalto.ca)
- [WaterWatch](https://waterwatch.criticalto.ca) — national water intelligence dashboard
- [PEI Infrastructure Monitor](https://pei.criticalto.ca)
- [CSI-Global](https://global.criticalto.ca) — humanitarian supply chain monitoring
