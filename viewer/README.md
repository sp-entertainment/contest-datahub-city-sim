# Viewer

Cosmetic city scene plus the lever panel. The `human` mode's control surface.

**Read this first: the scene is cosmetic, the controls are not.** This project is a benchmark, not
a game (`docs/DECISIONS.md`, 2026-08-02). The render does not have to represent the city faithfully
— it has to look like a city so the human mode is playing something legible. The lever panel and the
advance control are functional: without them the human mode cannot play at all. Under time pressure
the scene is the **first** thing cut; the controls are not cut.

## What it shows

A city that looks like a city: terrain and zoning, buildings that grow and densify and decay, roads
carrying traffic, utility infrastructure, and inhabitants moving between homes and workplaces. In
manual mode, the eight levers appear as real GUI inputs — sliders and selectors the player
manipulates directly — plus a control to advance the simulation and watch what happens.

## The hard constraint, and why it is not a style rule

No charts, counters, gauges, trend lines, alerts, or numeric readouts of city state.

**This is the experiment's control.** Every mode — human, agent-with-DataHub, agent-without — must
get the same channel to the city's state, so that the only difference between them is the metadata.
A number on screen gives the human mode information the agent modes do not have, and the comparison
stops meaning anything. Breaking this does not make the viewer ugly; it invalidates the result.

The line is not "no detail" — it is **showing the city versus showing measurements of the city.**

| This is the city | This is instrumentation |
| --- | --- |
| A road drawn with visible potholes | `road quality: 34%` |
| Buildings going dark during a shortfall | An outage counter, or a red warning icon |
| A derelict, weed-grown lot | `vacancy: 12%` |
| Cars backed up along a street | A congestion index |
| Fewer people on the streets year over year | A population figure, or a trend line |

The player should be able to watch for thirty seconds, say something true about how the city is
doing, and not be able to point at a single number on screen. Anything more precise than that, they
ask the Analytics Agent — which is exactly the channel the `agent_datahub` mode has, which is what
makes the two comparable.

**Lever positions are exempt.** Those are the player's own inputs, not the simulation's state. A
slider has to show where it is set.

## Where the data comes from

`GET /scene` on the sim's FastAPI control surface returns everything to draw for the current tick,
shaped for rendering rather than analysis. Lever changes `POST` to `/lever`; stepping the
simulation `POST`s to `/advance`.

Lever names, ranges, and defaults come from `blindcity.levers` — the single source of truth. Do not
restate them here or hard-code them in the frontend.

## How it is drawn

One `index.html`, one 2D canvas, no build step and no framework. FastAPI serves it as a static file
from the same process that runs the simulation.

- Isometric grid of flat tiles, coloured by zoning.
- Buildings as extruded boxes. **Height encodes density, colour encodes type, shade encodes
  condition, and unpowered goes dark.** The colour keys are the `building_type` values `GET /scene`
  sends — `residential`, `commercial`, `industrial`, `civic` — and the swatches in the legend are
  the same colours, so a change to one is a change to both.
- Citizens as 2px dots on the tiles they occupy.
- Roads as lines that pale as they wear.
- The whole canvas redraws on each tick. No dirty rectangles, no interpolation between ticks.
- Lever panel built from `GET /state`, using plain `<input type="range">` — names, ranges and
  defaults all come from `blindcity.levers`, so the panel never restates them.
