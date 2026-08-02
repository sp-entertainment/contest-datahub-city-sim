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

### Build this first, and stop

The first version is deliberately plain. Get it working, then leave it alone until everything else
in `TASKS.md` is done.

- Isometric grid of flat-coloured tiles. Colour by zoning; that is the whole terrain treatment.
- Buildings as extruded boxes. **Height encodes density, colour encodes type, shade encodes
  condition.** No textures, no windows, no roofs, no per-building art.
- Citizens as 2–3px dots that move along roads. No sprites, no animation frames, no pathing
  finesse — interpolating between endpoints is enough.
- Roads as lines that get visibly darker and more broken as they wear.
- Redraw the whole canvas on each tick. No dirty-rect optimisation, no interpolation between ticks.
- Lever panel as plain HTML `<input type="range">` and `<select>`. No custom controls.

That is a city sim. Three shades of grey on a street grid with moving dots reads as one instantly,
and it is maybe a day of work.

**Explicitly not in the first version**, and not worth arguing about until the submission is
otherwise complete: sprite art, animation, day/night, weather, camera pan and zoom, particle
effects, building variety, shadows, tile bevels, smooth movement between ticks.

If the first version looks flat and schematic, it is correct. The judged claim is that a catalog and
an agent can replace a game UI — not that we can draw.
