const UNIT_URL = "../../data/curriculum/audio/02-advanced.json";
const AUDIO_URL = "../../data/assets/audio/task4-segmentation-alignment.wav";
const TARGET_UNIT_ID = "TU-AUDIO-SEGMENTATION-ALIGNMENT-001";
const TARGET_ERROR_TYPE = "boundary_alignment_mismatch";

const state = {
  unit: null,
  exercise: null,
  hasFailed: false,
};

const elements = {
  form: document.querySelector("#alignment-form"),
  audio: document.querySelector("audio"),
  unitId: document.querySelector("#unit-id"),
  unitTitle: document.querySelector("#unit-title"),
  projectPolicy: document.querySelector("#project-policy"),
  ruleRefs: document.querySelector("#rule-refs"),
  intervalConvention: document.querySelector("#interval-convention"),
  anchorTrack: document.querySelector("#anchor-track"),
  submissionTrack: document.querySelector("#submission-track"),
  feedbackPanel: document.querySelector("#feedback-panel"),
  feedbackHeading: document.querySelector("#feedback-heading"),
  feedbackMessage: document.querySelector("#feedback-message"),
  errorType: document.querySelector("#error-type"),
  feedbackRule: document.querySelector("#feedback-rule"),
  feedbackCapability: document.querySelector("#feedback-capability"),
  feedbackActions: document.querySelector("#feedback-actions"),
  remediationPanel: document.querySelector("#remediation-panel"),
  remediationResource: document.querySelector("#remediation-resource"),
  remediationCopy: document.querySelector("#remediation-copy"),
  openRemediation: document.querySelector('[data-testid="open-remediation"]'),
  applyRemediation: document.querySelector('[data-testid="apply-remediation"]'),
  retryAttempt: document.querySelector('[data-testid="retry-attempt"]'),
  loadError: document.querySelector("#load-error"),
  inputs: {
    firstStart: document.querySelector("#segment-one-start"),
    firstEnd: document.querySelector("#segment-one-end"),
    firstText: document.querySelector("#segment-one-text"),
    secondStart: document.querySelector("#segment-two-start"),
    secondEnd: document.querySelector("#segment-two-end"),
    secondText: document.querySelector("#segment-two-text"),
  },
};

function sameValue(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function findUnit(documentData) {
  const matches = documentData.units.filter((unit) => unit.id === TARGET_UNIT_ID);
  if (matches.length !== 1) {
    throw new Error(`课程源中应有且仅有一个 ${TARGET_UNIT_ID}`);
  }
  return matches[0];
}

function createSegmentElement(segment, durationMs, label) {
  const node = document.createElement("div");
  node.className = "timeline-segment";
  node.style.left = `${(segment.start_ms / durationMs) * 100}%`;
  node.style.width = `${((segment.end_ms - segment.start_ms) / durationMs) * 100}%`;
  node.textContent = label;
  node.title = `${label}: [${segment.start_ms},${segment.end_ms})`;
  return node;
}

function drawSegments(target, segments, durationMs, labelPrefix) {
  target.replaceChildren(
    ...segments.map((segment, index) =>
      createSegmentElement(segment, durationMs, `${labelPrefix} ${index + 1}`),
    ),
  );
}

function submissionFromInputs() {
  const { exercise } = state;
  const recordingId = exercise.input.recording_id;
  return {
    segments: [
      {
        segment_id: "seg-001",
        recording_id: recordingId,
        start_ms: Number(elements.inputs.firstStart.value),
        end_ms: Number(elements.inputs.firstEnd.value),
        transcript: elements.inputs.firstText.value,
      },
      {
        segment_id: "seg-002",
        recording_id: recordingId,
        start_ms: Number(elements.inputs.secondStart.value),
        end_ms: Number(elements.inputs.secondEnd.value),
        transcript: elements.inputs.secondText.value,
      },
    ],
  };
}

function setInputs(submission) {
  const [first, second] = submission.segments;
  elements.inputs.firstStart.value = first.start_ms;
  elements.inputs.firstEnd.value = first.end_ms;
  elements.inputs.firstText.value = first.transcript;
  elements.inputs.secondStart.value = second.start_ms;
  elements.inputs.secondEnd.value = second.end_ms;
  elements.inputs.secondText.value = second.transcript;
  drawSegments(
    elements.submissionTrack,
    submission.segments,
    state.exercise.input.duration_ms,
    "提交",
  );
}

function updateSteps(activeStep, completedSteps = []) {
  document.querySelectorAll(".steps li").forEach((item) => {
    const key = item.dataset.step;
    item.classList.toggle("is-active", key === activeStep);
    item.classList.toggle("is-complete", completedSteps.includes(key));
  });
}

function mappingFor(errorType) {
  return state.unit.learning_path.error_mappings.find(
    (mapping) => mapping.error_type === errorType,
  );
}

function showFailure(diagnostic) {
  const mapping = mappingFor(diagnostic.error_type);
  state.hasFailed = true;
  elements.feedbackPanel.dataset.state = "failed";
  elements.feedbackHeading.textContent = "边界未贴合语音锚点";
  elements.feedbackMessage.textContent = diagnostic.feedback;
  elements.errorType.textContent = diagnostic.error_type;
  elements.feedbackRule.textContent = mapping.rule_refs.join(", ");
  elements.feedbackCapability.textContent = mapping.capability_refs.join(", ");
  elements.remediationResource.textContent = mapping.remediation_resource_refs.join(", ");
  elements.remediationCopy.textContent = diagnostic.remediation.join(" ");
  elements.feedbackActions.hidden = false;
  elements.remediationPanel.hidden = true;
  updateSteps("feedback", ["rule", "attempt"]);
}

function showSuccess() {
  elements.feedbackPanel.dataset.state = "passed";
  elements.feedbackHeading.textContent = "对齐通过";
  elements.feedbackMessage.textContent = state.exercise.evaluation.correct_feedback;
  elements.errorType.textContent = "none";
  elements.feedbackRule.textContent = state.unit.rule_refs.join(", ");
  elements.feedbackCapability.textContent = state.exercise.capability_refs.join(", ");
  elements.feedbackActions.hidden = true;
  elements.remediationPanel.hidden = true;
  updateSteps("retry", ["rule", "attempt", "feedback", "retry"]);
}

function evaluate(submission) {
  if (sameValue(submission, state.exercise.answer)) {
    showSuccess();
    return;
  }
  const diagnostic = state.exercise.evaluation.diagnostic_rules.find((rule) =>
    sameValue(submission, rule.submission),
  );
  showFailure(diagnostic || state.exercise.evaluation.incorrect_feedback);
}

function renderUnit(unit) {
  state.unit = unit;
  state.exercise = unit.exercise;
  const { exercise } = state;
  const intendedFailure = exercise.evaluation.diagnostic_rules.find(
    (rule) => rule.error_type === TARGET_ERROR_TYPE,
  );
  if (!intendedFailure) {
    throw new Error(`课程练习缺少 ${TARGET_ERROR_TYPE} 诊断规则`);
  }

  elements.unitId.textContent = unit.id;
  elements.unitTitle.textContent = unit.title;
  elements.projectPolicy.textContent = unit.rule_explanation.project_policy.statement;
  elements.intervalConvention.textContent = `INTERVAL ${exercise.input.interval_convention}`;
  elements.ruleRefs.replaceChildren(
    ...unit.rule_refs.map((ruleRef) => {
      const tag = document.createElement("span");
      tag.textContent = ruleRef;
      return tag;
    }),
  );
  drawSegments(
    elements.anchorTrack,
    exercise.input.speech_anchors,
    exercise.input.duration_ms,
    "锚点",
  );
  setInputs(intendedFailure.submission);
  elements.audio.src = AUDIO_URL;
  window.__evidenceReady = true;
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  updateSteps("attempt", ["rule"]);
  evaluate(submissionFromInputs());
});

Object.values(elements.inputs).forEach((input) => {
  input.addEventListener("input", () => {
    if (!state.exercise) return;
    drawSegments(
      elements.submissionTrack,
      submissionFromInputs().segments,
      state.exercise.input.duration_ms,
      "提交",
    );
  });
});

elements.openRemediation.addEventListener("click", () => {
  elements.remediationPanel.hidden = false;
  elements.feedbackActions.hidden = true;
  updateSteps("feedback", ["rule", "attempt"]);
});

elements.applyRemediation.addEventListener("click", () => {
  setInputs(state.exercise.answer);
  elements.remediationCopy.textContent =
    "已按 speech_anchors 恢复 [400,1550) 与 [2100,3350)，请重新提交。";
  elements.feedbackActions.hidden = false;
  elements.openRemediation.hidden = true;
  updateSteps("retry", ["rule", "attempt", "feedback"]);
});

elements.retryAttempt.addEventListener("click", () => {
  evaluate(submissionFromInputs());
});

fetch(UNIT_URL)
  .then((response) => {
    if (!response.ok) throw new Error(`课程源加载失败: HTTP ${response.status}`);
    return response.json();
  })
  .then((documentData) => renderUnit(findUnit(documentData)))
  .catch((error) => {
    elements.loadError.hidden = false;
    elements.loadError.textContent = error.message;
    window.__evidenceError = error.message;
  });
