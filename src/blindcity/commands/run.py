"""`blindcity run` — play one mode of one scenario. The only runner.

There were two of these until 2026-08-10: `uv run agent` and `uv run eval --live`, each a
hand-written wrapper around `agent/run.py::run_mode`. They drifted three times -- the eval path
lost transcripts, lost `--force-clean`, and never printed the query-error count or the DEGRADED
block -- so a twelve-run batch could report a clean table while runs were losing queries to
timeouts. One runner means a flag added here is a flag every run gets, and diagnostics cannot be
missing from the path that produces the published numbers.

Repeats are deliberately not a flag. `for i in 1 2 3; do blindcity run ...; done` needs no feature,
and every parameter stays available inside the loop.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


def run(args: Any) -> int:
    from blindcity.agent.controller import DEFAULT_TOOL_BUDGET
    from blindcity.agent.lever_review import LeverParseFailure
    from blindcity.agent.llm import LLMError, build_llm
    from blindcity.agent.run import FREE_MODES, HUMAN_MODE, SCRIPTED_MODES, run_mode
    from blindcity.benchmark.scenario import INFRASTRUCTURE_CRISIS
    from blindcity.catalog.apply import apply_catalog

    scripted = args.mode in SCRIPTED_MODES
    # Calls no model, so needs no key and produces no transcript. Wider than `scripted`: the human
    # mode is free too, but unlike the scripted policies it does need the catalog published, because
    # the Analytics Agent it asks questions of reads the catalog.
    free = args.mode in FREE_MODES

    # On by default whenever results are being written: the runs that mattered were the ones
    # nobody thought to record.
    transcript_path = args.transcript
    if transcript_path is None and args.out and not free:
        transcript_path = str(Path(args.out).with_suffix(".transcript.jsonl"))

    # The catalog is published before the scenario is played, so the metadata the agent reads
    # matches the commit it is being played from. Skipped for the scripted reference policies,
    # which read no catalog and must stay runnable with no DataHub at all.
    catalog_provenance: dict[str, Any] = {"applied": False, "source": "none"}
    if not scripted:
        try:
            applied, _, drift = apply_catalog(args.gms, overwrite=args.overwrite_datahub)
        except Exception as exc:  # noqa: BLE001 — CLI surface
            print(f"run: {exc}", file=sys.stderr)
            return 1
        catalog_provenance = {
            "applied": applied,
            # Which copy of the guidance this run acted on. Once DataHub is editable a score
            # cannot be read without it: "published snapshot" and "someone's edits" are different
            # experiments and must not look alike in a result file.
            "source": "snapshot" if applied else "datahub",
            "drift_items": len(drift.lines()),
        }

    try:
        run_result = run_mode(
            args.mode,
            llm=None if free else build_llm(args.model),
            turns=args.turns,
            tool_budget=args.tool_budget or DEFAULT_TOOL_BUDGET,
            keep_views=args.keep_views,
            clean_warehouse=not args.keep_warehouse,
            force_clean=args.force_clean,
            transcript=transcript_path,
            advisor_url=args.advisor_url,
        )
    except LeverParseFailure as exc:
        # The advisor's decision could not be read, so this run measured our parser rather than the
        # catalog and its score means nothing. Finishing would be worse than stopping: it would
        # produce a plausible number indistinguishable from a real one. The transcript is already
        # on disk from the controller, and the result file is deliberately never written, so a
        # later `blindcity compare "results/*.json"` cannot sweep a void run into a table.
        print(f"run: ABANDONED -- {exc}", file=sys.stderr)
        print(f"run: levers left unreadable: {', '.join(exc.vague) or '(none named)'}", file=sys.stderr)
        for i, attempt in enumerate(exc.attempts):
            label = "answer" if i == 0 else f"clarification {i}"
            print(f"run: --- {label} ---\n{attempt.strip()[:800]}", file=sys.stderr)
        if transcript_path:
            print(f"run: full exchange at {transcript_path}", file=sys.stderr)
        print("run: no result file written; this run must not be scored.", file=sys.stderr)
        return 1
    except LLMError as exc:
        print(f"run: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — CLI surface
        print(f"run: failed: {exc}", file=sys.stderr)
        return 1

    result, report = run_result.result, run_result.report
    report["catalog_source"] = catalog_provenance
    _record_guidance(report, args.mode)

    played = len(result.turns)
    print(
        f"run: mode={result.mode} model={report['model']} catalog={report['catalog']} "
        f"turns={played} recovered={result.recovered} green_turn={result.green_turn} "
        f"final_index={result.final_index:.4f}"
    )
    usage = report["usage"]
    print(
        f"run: tokens prompt={usage['prompt_tokens']:,} output={usage['output_tokens']:,} "
        f"total={usage['total_tokens']:,} llm_calls={usage['calls']} "
        f"llm_seconds={usage['seconds']} wall_seconds={run_result.wall_seconds:.1f}"
    )

    if played and played < INFRASTRUCTURE_CRISIS.turn_budget:
        from blindcity.agent.run import estimate_full_run

        est = estimate_full_run(report, played, INFRASTRUCTURE_CRISIS.turn_budget)
        print(
            f"run: extrapolated full run ({est['turn_budget']} turns) "
            f"total_tokens={est['total_tokens']:,} llm_calls={est['llm_calls']} "
            f"llm_seconds={est['llm_seconds']}"
        )

    _print_diagnostics(report)

    if args.out:
        result.write_json(args.out)
        side = Path(args.out).with_suffix(".agent.json")
        side.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"run: wrote {args.out} and {side}")
    if transcript_path:
        print(f"run: transcript at {transcript_path}")

    if args.mode == HUMAN_MODE and run_result.server is not None:
        _hold_open(run_result.server)
    return 0


def _hold_open(server: Any) -> None:
    """Keep the finished city on screen until the player is done looking at it.

    The score is already written by the time this is called, so nothing is at risk here. A browser
    that goes blank the instant the last quarter lands is just a worse way to end a game.
    """
    print(f"\nrun: the run is over. The final city is still at {server.url}")
    print("run: press Ctrl+C when you are finished.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nrun: stopping the control surface.")
    finally:
        server.stop()


def _record_guidance(report: dict[str, Any], mode: str) -> None:
    """Fingerprint the guidance the run actually used, for modes that read it."""
    if mode != "agent_datahub_live":
        return
    try:
        from blindcity.agent.guidance import fetch_guidance
        from blindcity.catalog.apply import guidance_fingerprint

        guidance = fetch_guidance()
        report["catalog_source"].update(
            {
                "guidance_fingerprint": guidance_fingerprint(guidance),
                "levers": len(guidance.levers),
                "outcomes": len(guidance.outcomes),
                "lags": len(guidance.lags),
            }
        )
    except Exception as exc:  # noqa: BLE001 — provenance must never cost a finished run
        report["catalog_source"]["guidance_fingerprint_error"] = str(exc)[:200]


def _print_diagnostics(report: dict[str, Any]) -> None:
    """Everything that went wrong without failing the run.

    This block is why there is only one runner. The eval path never printed it, so a batch of
    twelve runs could show a clean comparison table while queries were being lost to timeouts.
    """
    failed = [t for t in report["turns"] if t.get("error")]
    if failed:
        print(f"run: {len(failed)} turn(s) hit an LLM error; first: {failed[0]['error'][:200]}")

    # A model asking for a table that does not exist is exploration, not damage — report it flatly.
    query_errors = report.get("tool_failures", 0) - report.get("infrastructure_failures", 0)
    if query_errors:
        print(f"run: {query_errors} query error(s) the model recovered from (bad table or column)")

    # Degradation is different and must never read as a clean run: these do not fail the turn, the
    # model adapts and carries on, so this is the only trace that a diagnosis it asked for never
    # came back. One live run lost four queries and three minutes and printed "0 errors".
    infra = report.get("infrastructure_failures", 0)
    if infra:
        turns_hit = [t["turn"] for t in report["turns"] if t.get("infrastructure_errors")]
        print(
            f"run: DEGRADED -- {infra} query/queries lost to timeouts or a dead warehouse "
            f"on turn(s) {turns_hit}"
        )
        print("run: the score stands, but the model was denied data it asked for.")

    # Whether the advisor actually got the guidance it was sent for. A run that asked twenty-five
    # times and was refused every time scores like a run that never asked, and until this line
    # existed it also *read* like one -- the mode's whole claim is that it acted on what DataHub
    # holds, so a silent zero here invalidates the number rather than merely annotating it.
    if "guidance_reads" in report:
        turns = report["turns_reading_guidance"]
        lookups = report["guidance_lookups"]
        if turns:
            print(
                f"run: read the catalog guidance on {turns} of {len(report['turns'])} turn(s) "
                f"({report['guidance_reads']} of {lookups} catalog call(s) returned it)"
            )
        elif lookups:
            # Looked and came back empty. A different diagnosis from never having looked, and it
            # needs a different fix -- the search terms, not the instruction to search.
            print(
                f"run: NO GUIDANCE -- {lookups} catalog call(s) succeeded and none returned a "
                "guidance property."
            )
            print("run: the advisor went looking and found nothing; check what it searched for.")
        else:
            print("run: NO GUIDANCE -- every attempt to read the catalog failed or was never made.")
            print("run: this mode scores on what DataHub told it; it was told nothing.")
        for name, count in (report.get("failed_tool_calls") or {}).items():
            print(f"run: {count} failed call(s) to {name}")

    # Whether the backoff earned its wait. Retries with no lost turn means it did; retries beside a
    # lost turn means the wait is still shorter than the window it is waiting out.
    retried = report.get("rate_limited")
    if retried:
        print(f"run: {retried} question(s) re-put after a rate limit")

    advisor_errors = report.get("advisor_errors") or []
    if advisor_errors:
        print(f"run: {len(advisor_errors)} turn(s) got no advice; first: {advisor_errors[0][:200]}")

    # How the advisor's decisions had to be read. A run entirely on the contract is the quiet
    # case and says nothing; anything else is a fact about using this agent, and the reason the
    # numbers are trustworthy at all.
    parsing = report.get("parsing")
    if parsing and (parsing["needed_reviewer"] or parsing["needed_clarifying"]):
        print(
            f"run: {parsing['on_contract']} turn(s) followed the output contract; "
            f"{parsing['needed_reviewer']} needed the reviewer, "
            f"{parsing['needed_clarifying']} needed clarifying "
            f"({parsing['clarification_rounds']} round(s))"
        )
        if parsing["vague_levers"]:
            print(f"run: levers the advisor left vague: {', '.join(parsing['vague_levers'])}")
