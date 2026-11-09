"""Development traces in the user's own MLflow Experiment (dbx edition).

One trace per turn: a root `agent.turn` span (prompt, answer, harness, tokens) with a child span for the
handoff and for each tool or skill the harness used. Traces of one aops session share the MLflow session
metadata, so switching harness shows as Claude and Codex traces in the same session. The default
destination is `/Users/<me>/aops/<project>`; `[dbx] experiment` changes it, `[dbx] trace = false` turns
it off. A failure here never fails the turn.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any

from .project import Project


def enabled(project: Project) -> bool:
    return project.edition != "local" and project.dbx.get("trace", True) is not False


def _ns(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1_000_000_000)


def token_usage(usage: dict[str, Any]) -> dict[str, int] | None:
    """This turn's tokens in MLflow's `mlflow.chat.tokenUsage` form (input counts cache reads and writes).

    Claude reports the turn in Anthropic form, where input_tokens leaves the cache out. Codex reports
    camelCase counts where input already holds the cached part; aops keeps this turn's share in `turn`.
    """
    codex = usage.get("turn") or usage.get("last")
    if isinstance(codex, dict) or "inputTokens" in usage:
        part = codex if isinstance(codex, dict) else usage
        given = int(part.get("inputTokens") or 0), int(part.get("outputTokens") or 0)
        out = {"input_tokens": given[0], "output_tokens": given[1], "total_tokens": int(part.get("totalTokens") or sum(given))}
        extra = {"cache_read_input_tokens": part.get("cachedInputTokens"), "cache_creation_input_tokens": part.get("cacheWriteInputTokens")}
    else:
        read, made = int(usage.get("cache_read_input_tokens") or 0), int(usage.get("cache_creation_input_tokens") or 0)
        given = int(usage.get("input_tokens") or 0) + read + made, int(usage.get("output_tokens") or 0)
        out = {"input_tokens": given[0], "output_tokens": given[1], "total_tokens": sum(given)}
        extra = {"cache_read_input_tokens": read, "cache_creation_input_tokens": made,
                 "cache_creation_input_tokens_above_1hr": (usage.get("cache_creation") or {}).get("ephemeral_1h_input_tokens")}
    out.update({k: int(v) for k, v in extra.items() if v})
    return out if out["total_tokens"] else None


def price_name(model: str | None) -> str | None:
    """The model name MLflow prices by: Databricks system models drop their `system.ai.` prefix."""
    return model.removeprefix("system.ai.") if model else None


def _experiment(client: Any, path: str) -> str:
    """The id of the Experiment at `path`, made (or taken out of the trash) when needed."""
    found = client.get_experiment_by_name(path)
    if found is None:
        return client.create_experiment(path)
    if found.lifecycle_stage == "deleted":
        client.restore_experiment(found.experiment_id)
    return found.experiment_id


def export_turn(project: Project, turn: dict[str, Any]) -> dict[str, str] | None:
    if not enabled(project):
        return None
    profile = os.environ.get("AOPS_PROFILE") or project.dbx.get("profile") or None
    try:
        os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
        if profile:
            os.environ.setdefault("DATABRICKS_CONFIG_PROFILE", profile)
        import logging

        import mlflow
        from databricks.sdk import WorkspaceClient

        logging.getLogger("mlflow").setLevel(logging.ERROR)
        w = WorkspaceClient(profile=profile)
        me = w.current_user.me().user_name
        path = project.dbx.get("experiment") or f"/Users/{me}/aops/{project.name}"
        w.workspace.mkdirs(path.rsplit("/", 1)[0])
        mlflow.set_tracking_uri(f"databricks://{profile}" if profile else "databricks")
        experiment_id = _experiment(mlflow.MlflowClient(), path)

        tools: list[str] = turn["tools"]
        skills = [t.split(":", 1)[1] for t in tools if t.startswith("skill:")]
        usage = token_usage(turn.get("usage") or {})
        model = turn.get("model")
        start, end = _ns(turn["started_at"]), _ns(turn["ended_at"])
        root = mlflow.start_span_no_context(
            name="agent.turn", span_type="AGENT", experiment_id=experiment_id, start_time_ns=start,
            inputs={"prompt": turn["prompt"]},
            attributes={"agentops.harness": turn["harness"], "agentops.harness_version": turn["harness_version"],
                        "agentops.handoff_turns": turn["handoff_turns"], "agentops.model": model or "-"},
            tags={"agentops.agent_id": project.name or "", "agentops.session_id": turn["session"],
                  "agentops.turn_id": str(turn["turn"]), "agentops.harness": turn["harness"],
                  "agentops.skills": ",".join(dict.fromkeys(skills)) or "-", "agentops.handoff_turns": str(turn["handoff_turns"]),
                  "agentops.model": model or "-"},
            metadata={"mlflow.trace.session": turn["session"], "mlflow.trace.user": me},
        )
        if usage or model:
            # The model calls of the turn. MLflow reads tokens from here and prices them by model name.
            llm = mlflow.start_span_no_context(
                name=f"llm.{price_name(model) or turn['harness']}", span_type="LLM", parent_span=root,
                start_time_ns=start, inputs={"model": model},
                attributes={k: v for k, v in {"mlflow.llm.model": price_name(model), "mlflow.chat.tokenUsage": usage,
                                              "agentops.model": model}.items() if v})
            llm.end(outputs={"tokens": usage}, end_time_ns=end)
        children = (["handoff"] if turn["handoff_turns"] else []) + tools
        step = (end - start) // (len(children) + 1) if children else 0
        at = start
        for item in children:
            if item == "handoff":
                name, kind, inputs = "aops.handoff", "CHAIN", {"turns": turn["handoff_turns"], "from": "earlier harness"}
            elif item.startswith("skill:"):
                name, kind, inputs = f"tool.skill.{item.split(':', 1)[1]}", "TOOL", {"skill": item.split(":", 1)[1]}
            else:
                name, kind, inputs = f"tool.{item}", "TOOL", {"tool": item}
            span = mlflow.start_span_no_context(name=name, span_type=kind, parent_span=root, start_time_ns=at, inputs=inputs,
                                                attributes={"agentops.tool_category": "skill" if item.startswith("skill:") else
                                                            "handoff" if item == "handoff" else "tool"})
            at += step
            span.end(end_time_ns=at)
        root.end(outputs={"response": turn["response"]}, end_time_ns=end)
        host = w.config.host.rstrip("/")
        return {"trace_id": root.trace_id, "experiment": path,
                "url": f"{host}/ml/experiments/{experiment_id}/traces?selectedEvaluationId={root.trace_id}",
                "experiment_url": f"{host}/ml/experiments/{experiment_id}/traces"}
    except Exception as error:  # the turn itself already succeeded
        print(f"aops: MLflow trace를 남기지 못했습니다 ({type(error).__name__}: {str(error)[:160]})", file=sys.stderr)
        return None


def dumps(info: dict[str, str]) -> str:
    return json.dumps(info, ensure_ascii=False)
