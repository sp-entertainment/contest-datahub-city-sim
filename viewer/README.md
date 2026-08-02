# Viewer

A rendered city and eight levers. The player's entire window onto the simulation.

## What it shows

A city that looks like a city: terrain and zoning, buildings that grow and densify and decay, roads
carrying traffic, utility infrastructure, and inhabitants moving between homes and workplaces. In
manual mode, the eight levers appear as real GUI inputs — sliders and selectors the player
manipulates directly — plus a control to advance the simulation and watch what happens.

## The hard constraint, and where the line actually falls

No charts, counters, gauges, trend lines, alerts, or numeric readouts of city state.

The line is not "no detail" — it is **showing the city versus showing measurements of the city.**
The first is the product. The second is the thing this entry deliberately removed, because a
metadata catalog and an agent are supposed to replace it.

| This is the city | This is instrumentation |
| --- | --- |
| A road drawn with visible potholes | `road quality: 34%` |
| Buildings going dark during a shortfall | An outage counter, or a red warning icon |
| A derelict, weed-grown lot | `vacancy: 12%` |
| Cars backed up along a street | A congestion index |
| Fewer people on the streets year over year | A population figure, or a trend line |

The player should be able to watch for thirty seconds, say something true about how the city is
doing, and not be able to point at a single number on screen. Anything more precise than that, they
ask the agent — that is the entire premise.

**Lever positions are exempt.** Those are the player's own inputs, not the simulation's state. A
slider has to show where it is set.

## Where the data comes from

`GET /scene` on the sim's FastAPI control surface returns everything to draw for the current tick,
shaped for rendering rather than analysis. Lever changes `POST` to `/lever`; stepping the
simulation `POST`s to `/advance`.

Lever names, ranges, and defaults come from `blindcity.levers` — the single source of truth. Do not
restate them here or hard-code them in the frontend.

## Not yet built

Plan: Slice 6 in `.tasks/mvp/TASKS.md`.

**Approach, decided** (see `docs/DECISIONS.md`): plain HTML with a 2D canvas, drawing a 2.5D
isometric tile scene. No build step, no framework, served as static files by the FastAPI process.

**Low fidelity is fine and is the target.** Flat-shaded isometric blocks for buildings, simple
sprites or dots for citizens. It has to read as a city sim at a glance — silhouette, density, and
condition are what carry that, not texture detail. Spend effort on making state legible, not on
making buildings pretty.
