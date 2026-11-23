"""Experimental Investigation schema and task data. No production registration."""
from dataclasses import dataclass

from security_augmented.agents import AgentRun, GeminiDecider, RelationalTask
from security_augmented.contracts import VideoError


@dataclass(frozen=True, kw_only=True)
class QuestionTask(RelationalTask):
    visual_question: str


class QuestionDecider(GeminiDecider):
    def _request(self, call, **kwargs):
        config = kwargs["config"]
        for branch in config["response_json_schema"]["anyOf"]:
            tasks = branch["properties"].get("relational_tasks")
            if tasks:
                item = tasks["items"]
                item["properties"]["visual_question"] = {
                    "type": "string", "minLength": 1, "maxLength": 240,
                    "description": "Ask one open What, Where, Which or How question about visible evidence. "
                    "Allow no observable relationship. Do not presuppose an event, intention or persistent identity.",
                }
                item["required"].append("visual_question")
        return super()._request(call, **kwargs)


class QuestionRun(AgentRun):
    def _relation_delegations(self, rows, visible, dispositions, movement_count):
        if not isinstance(rows, list):
            raise VideoError("Expected a list of relational tasks")
        members, questions = [], []
        for row in rows:
            if not isinstance(row, dict) or row.keys() != {"observation_ids", "visual_question"}:
                raise VideoError("Expected observation IDs and one visual question")
            q = row["visual_question"]
            if (not isinstance(q, str) or not 1 <= len(q) <= 240 or not q.endswith("?")
                    or q.count("?") != 1 or not q.isprintable()
                    or not q.lower().startswith(("what ", "where ", "which ", "how "))):
                raise VideoError("Expected one bounded open visual question")
            members.append({"observation_ids": row["observation_ids"]})
            questions.append(q)
        tasks = super()._relation_delegations(members, visible, dispositions, movement_count)
        # Bind by canonical members, independently of the validator's return order.
        by_members = {tuple(sorted(m["observation_ids"])): q for m, q in zip(members, questions, strict=True)}
        return tuple(QuestionTask(task.id, task.observation_ids, task.video_id, task.interval, task.objective, visual_question=by_members[task.observation_ids]) for task in tasks)
