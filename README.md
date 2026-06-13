[README.md](https://github.com/user-attachments/files/28919674/README.md)
# RailWatch# RailWatch Canada

**Corridor intelligence for Canada's freight rail network.**
A public infrastructure intelligence platform — part of the [Critical TO](https://criticalto.ca) family.

🚂 **Live dashboard:** [rail.criticalto.ca](https://rail.criticalto.ca)  
📡 **Data repo:** [railwatch-data](https://github.com/Sargjones/railwatch-data) (auto-updated daily)  
📋 **Submit an observation:** [Open an issue](https://github.com/Sargjones/railwatch-observations/issues/new?template=observation.md)

---

## What this is

RailWatch documents dangerous goods movement on Canada's freight rail network using public data and community observations. It exists because of a transparency gap: under Canada's Transportation of Dangerous Goods Act, freight railroads are only required to notify provincial fusion centres — not the communities the trains pass through.

A resident watching sodium hypochlorite cars roll through Brantford station at midnight has no legitimate path to know where they're going, who shipped them, or why. RailWatch doesn't claim to solve that gap — it documents it and builds the infrastructure for when transparency improves.

---

## Pilot corridor

**CN Dundas Subdivision** — the Toronto–Windsor corridor, originally built by the Great Western Railway in 1853. Passes through Toronto, Hamilton, Brantford, Woodstock, London, and Windsor, carrying a significant volume of industrial chemicals, agricultural products, and petroleum products daily.

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

---

## Planned corridors

- CN Dundas Sub: Toronto–Windsor ✅ **Pilot**
- CN Chatham Sub: Windsor–Sarnia 🔲 Planned
- CPKC Windsor Sub: Toronto–Windsor via Kitchener 🔲 Planned
- CN Halton Sub: MacMillan Yard–Burlington 🔲 Planned

---

## Part of Critical TO

RailWatch shares its scraper architecture, threshold-alert logic, and design system with:
- [Toronto Infrastructure Intelligence](https://criticalto.ca)
- [WaterWatch](https://waterwatch.criticalto.ca) — national water intelligence dashboard
- [PEI Infrastructure Monitor](https://pei.criticalto.ca)
- [CSI-Global](https://global.criticalto.ca) — humanitarian supply chain monitoring
