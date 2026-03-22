# NYCuriosity Data

**[data.nycuriosity.com](https://data.nycuriosity.com)**

A companion site to [NYCuriosity](https://nycuriosity.substack.com), a Substack publication covering NYC urban policy, transit, infrastructure, and street design. Each project on this site surfaces the raw data and interactive tools behind a NYCuriosity article.

---

## Projects

### [CB3 Resolutions Explorer](https://data.nycuriosity.com/cb3-resolutions/)
Search and browse 151,000+ resolutions voted on by Manhattan Community Board 3. Filter by keyword across any column, sort by any field, and read full resolution text in-browser. Built from a structured CSV of CB3 meeting records.

---

## About NYCuriosity

NYCuriosity is written by **Tal Roded** and published on Substack. It covers:

- **Transit** — MTA service, capital plans, ridership data
- **Streets & infrastructure** — bike lanes, bus lanes, pedestrian signals, the NYC Streets Plan
- **Community Board 3** — land use, street design, and parks decisions in the Lower East Side and East Village
- **Urban policy** — city legislation, fiscal impacts, agency planning

The publication is analytical but accessible — data-driven reporting aimed at curious general readers, not policy specialists.

---

## Tech

Static site hosted on GitHub Pages at a custom domain (`data.nycuriosity.com`). No backend. Each project is a self-contained directory with an `index.html` that loads data client-side.

**Dependencies:**
- [PapaParse](https://www.papaparse.com/) — CSV parsing
- [Google Fonts](https://fonts.google.com/) — Roboto Mono, Inter

---

## Structure

```
/               → Hub homepage (project tiles)
/cb3-resolutions/   → CB3 Resolutions Explorer
```

New projects follow the same pattern: add a subdirectory with an `index.html` and a card to the hub page.
