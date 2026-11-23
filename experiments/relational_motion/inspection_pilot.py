"""Offline-only frame inspection extension for the existing Verification agent."""
from security_augmented.agents import AgentRun, InspectionRejected
from security_augmented.contracts import VideoError
from security_augmented.gemini import GeminiAdapter
from security_augmented.workflow import InspectionPlan, _observe_video


class InspectionPilot(AgentRun):
    """Run scripted Verification decisions against real source media and local review."""

    def __init__(self, video, decide, review, budget, trace, *, media_limit, initial_inspections):
        super().__init__(video, self._scripted_decision, self._inspect, budget, trace, sampled_indices=set())
        if type(media_limit) is not int or media_limit < 0:
            raise ValueError("Media limit must be a nonnegative integer")
        self._script = decide
        self._review = review
        self._preflight = GeminiAdapter(single_request=True)
        for inspection in initial_inspections:
            if (inspection.video_id != video.id or inspection.modality != "frames"
                    or any(b - a != 500_000 for a, b in zip(
                        inspection.requested_times_us, inspection.requested_times_us[1:],
                    ))):
                raise ValueError("Expected initial 500 ms frame evidence for this source")
            self.sampled_indices.update(f.display_index for f in inspection.frames)
        self.media_limit = min(media_limit, budget.max_inspections)
        self.media_used = 0
        self.inspection_records = []

    def _scripted_decision(self, role, context):
        if role != "verification":
            return self._script(role, context)
        value = self._script(role, {**context, "remaining_media_requests": self.media_limit - self.media_used})
        if isinstance(value, dict) and value.get("action") == "inspect" and "question" in value:
            value = dict(value)
            value["visual_question"] = value.pop("question")
        return value

    def reinspect(self, finding, action, visible, *, publish=True, task=None):
        if task is not None:
            raise InspectionRejected("invalid_task", "This sampling pilot accepts individual candidates only.")
        if self.inspections < self.budget.max_inspections and self.media_used >= self.media_limit:
            raise InspectionRejected("media_budget", "Targeted media request budget exhausted.")
        return super().reinspect(finding, action, visible, publish=publish)

    def _inspect(self, interval, modality, *, sampling_step_ms=500, visual_question=None):
        entry = _observe_video(self.video, self, interval, modality, "targeted", InspectionPlan(), model_guided=True,
                               sampling_step_ms=sampling_step_ms, visual_question=visual_question)
        self.inspection_records.append(entry)
        return (entry,)

    def infer(self, request):
        self._preflight.prepare(request)
        self.media_used += 1
        return self._review(request)
