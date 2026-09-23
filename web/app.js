(function () {
  "use strict";

  var QUESTION = "재택용 모니터와 느려진 회사 노트북을 같이 바꾸고 싶은데, 같은 경비 신청으로 처리하면 돼?";
  var state = {
    mode: "conversation",
    demoState: "loading",
    panelTab: "evidence",
    activeDraft: "monitor",
    step: "4",
    conditions: { tenure: "", symptom: "", purchase: "" },
    drafts: { monitor: undefined, it: undefined },
    draftTouched: { monitor: false, it: false },
    sourceRevision: { monitor: null, it: null },
    proposals: { monitor: null, it: null },
    proposalInputRevision: { monitor: null, it: null },
    response: null,
    excludeLaptopEvidence: false,
    inputRevision: 0,
    requestSequence: 0,
    currentRequestId: 0,
    lastSettledDemoState: null,
    toastTimer: null
  };

  function all(selector) {
    return Array.prototype.slice.call(document.querySelectorAll(selector));
  }

  function showToast(message) {
    var toast = document.getElementById("toast");
    toast.textContent = message;
    toast.classList.add("show");
    window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(function () { toast.classList.remove("show"); }, 3600);
  }

  function purchaseForApi(value) {
    if (value === "not-purchased") return "not_purchased";
    return value;
  }

  function payload(requestId) {
    var facts = {};
    if (state.conditions.tenure) facts.tenure = state.conditions.tenure;
    if (state.conditions.symptom) facts.symptom = state.conditions.symptom;
    if (state.conditions.purchase) facts.purchase_status = purchaseForApi(state.conditions.purchase);
    return {
      client_request_id: requestId,
      inquiry_type: "monitor_and_laptop_replacement",
      user_text: QUESTION,
      employee_facts: facts,
      exclude_laptop_evidence: state.excludeLaptopEvidence
    };
  }

  function branchProposal(branchName) {
    if (!state.response) return null;
    var proposal = state.response.branches[branchName].draft_proposal;
    return proposal.status === "available_rule_composed" ? proposal : null;
  }

  function syncMode() {
    document.body.dataset.mode = state.mode;
    document.getElementById("conversationView").hidden = state.mode !== "conversation";
    document.getElementById("workflowView").hidden = state.mode !== "workflow";
    all(".mode-switch button[data-mode]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === state.mode));
    });
  }

  function syncDemoState() {
    document.body.dataset.demoState = state.demoState;
    var notice = document.getElementById("connectionNotice");
    notice.hidden = state.demoState !== "error";
    all("[data-demo-state-button]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.demoStateButton === state.demoState));
      button.disabled = state.demoState === "loading";
    });
    var summary = "모니터·노트북 문서";
    if (state.demoState === "loading") summary = "문서 확인 중";
    if (state.demoState === "missing") summary = "모니터 근거 확인 · 노트북 근거 부족";
    if (state.demoState === "error") summary = "로컬 연결 실패";
    all("[data-summary-evidence]").forEach(function (node) { node.textContent = summary; });
  }

  function hasCurrentInputProposal() {
    return ["monitor", "it"].some(function (key) {
      return state.proposals[key] && state.proposalInputRevision[key] === state.inputRevision;
    });
  }

  function syncInputChangedNotice() {
    var notice = document.getElementById("inputChangedNotice");
    notice.hidden = !state.response || hasCurrentInputProposal();
  }

  function syncPanel() {
    all("[data-panel-tab]").forEach(function (button) {
      button.setAttribute("aria-selected", String(button.dataset.panelTab === state.panelTab));
    });
    all("[data-panel-content]").forEach(function (panel) {
      panel.hidden = panel.dataset.panelContent !== state.panelTab;
    });
  }

  function syncDraftTabs() {
    all("[data-draft-tab]").forEach(function (button) {
      button.setAttribute("aria-selected", String(button.dataset.draftTab === state.activeDraft));
    });
    all("[data-draft-pane]").forEach(function (pane) {
      pane.hidden = pane.dataset.draftPane !== state.activeDraft;
    });
  }

  function syncSteps() {
    var titles = { "1": "04 · 질문 확인", "2": "03 · 내 상황", "3": "02 · 답변과 문서", "4": "01 · 문의 글 편집" };
    all("[data-step]").forEach(function (button) {
      if (button.dataset.step === state.step) button.setAttribute("aria-current", "step");
      else button.removeAttribute("aria-current");
    });
    all("[data-step-panel]").forEach(function (panel) { panel.hidden = panel.dataset.stepPanel !== state.step; });
    all("[data-stage-title]").forEach(function (node) { node.textContent = titles[state.step]; });
  }

  function statedFactsText() {
    var facts = [];
    if (state.conditions.tenure) facts.push("재직 " + state.conditions.tenure);
    if (state.conditions.symptom) facts.push(state.conditions.symptom + " 느려짐");
    if (state.conditions.purchase === "not-purchased") facts.push("미구매");
    if (state.conditions.purchase === "purchased") facts.push("구매 완료");
    if (state.conditions.purchase === "unknown") facts.push("구매 여부 확인 필요");
    return facts.length ? facts.join(" · ") + " — 직접 입력한 내용" : "재직 기간·느려진 상황·구매 상태를 아직 입력하지 않았습니다.";
  }

  function syncConditions() {
    all("[data-field]").forEach(function (field) {
      if (field.value !== state.conditions[field.dataset.field]) field.value = state.conditions[field.dataset.field];
    });
    var count = Object.keys(state.conditions).filter(function (key) { return Boolean(state.conditions[key]); }).length;
    all("[data-condition-count]").forEach(function (node) { node.textContent = count + "/3 입력"; });
    all("[data-stated-facts]").forEach(function (node) { node.textContent = statedFactsText(); });
  }

  function draftStatus(branchName) {
    var proposal = state.proposals[branchName];
    if (!proposal) return { kind: "withheld", text: "현재 검색 근거로 새 정책 기반 제안을 만들지 않았습니다. 작성 중인 글은 그대로 보존됩니다." };
    if (state.proposalInputRevision[branchName] !== state.inputRevision) {
      return { kind: "review", text: "입력한 내용이 이 제안을 만든 뒤 바뀌었습니다. 작성 중인 글은 유지했으며, 현재 입력으로 새 제안을 만들기 전에는 이 제안을 반영할 수 없습니다." };
    }
    if (state.sourceRevision[branchName] !== proposal.revision) {
      return { kind: "review", text: "입력이나 참고 문서가 바뀌어 새 제안이 생겼습니다. 작성 중인 글은 바꾸지 않았습니다.\n\n새 제안: " + proposal.text };
    }
    if (state.draftTouched[branchName]) {
      return { kind: "edited", text: "직접 고친 글입니다. 현재 참고 문서를 사용할 수 있지만 문장 의미가 맞는지는 자동 확인하지 않았습니다." };
    }
    return { kind: "current", text: "현재 검색 결과와 입력으로 만든 제안이 적용되어 있습니다." };
  }

  function ensureProposalNote(area) {
    var note = area.parentNode.querySelector('[data-proposal-note="' + area.dataset.draftArea + '"]');
    if (!note) {
      note = document.createElement("p");
      note.className = "proposal-note";
      note.dataset.proposalNote = area.dataset.draftArea;
      area.insertAdjacentElement("afterend", note);
    }
    return note;
  }

  function syncDrafts(source) {
    all("[data-draft-area]").forEach(function (area) {
      var key = area.dataset.draftArea;
      if (area !== source && state.drafts[key] !== undefined && area.value !== state.drafts[key]) area.value = state.drafts[key];
      var status = draftStatus(key);
      var note = ensureProposalNote(area);
      note.dataset.status = status.kind;
      note.textContent = status.text;
    });
    all("[data-reset-draft]").forEach(function (button) {
      var key = button.dataset.resetDraft;
      button.disabled = !state.proposals[key] || state.proposalInputRevision[key] !== state.inputRevision;
    });
  }

  function makeSourceCard(section, source) {
    var card = document.createElement("article");
    card.className = "source-card";
    var eyebrow = document.createElement("span");
    eyebrow.className = "eyebrow";
    eyebrow.textContent = "실제 회수 · " + section.id;
    var heading = document.createElement("h3");
    heading.textContent = section.heading_path.join(" · ");
    var excerpt = document.createElement("p");
    excerpt.className = "source-excerpt";
    excerpt.textContent = section.original_text;
    var meta = document.createElement("div");
    meta.className = "source-meta";
    var range = document.createElement("span");
    range.textContent = section.source_line_range + " · 열람 " + source.observed_at.slice(0, 10);
    var link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = "공개 문서 열기 ↗";
    meta.append(range, link);
    card.append(eyebrow, heading, excerpt, meta);
    return card;
  }

  function renderEvidence() {
    if (!state.response) return;
    var material = state.response.material;
    var targets = all('.panel-content[data-panel-content="evidence"] .state-normal, .panel-content[data-panel-content="evidence"] .state-missing');
    targets.forEach(function (target) {
      target.replaceChildren();
      material.evidence.forEach(function (section) { target.appendChild(makeSourceCard(section, material.source)); });
      if (state.demoState === "missing" && target.classList.contains("state-missing")) {
        var warning = document.createElement("article");
        warning.className = "source-card missing";
        var title = document.createElement("h3");
        title.textContent = "노트북 새 제안 보류";
        var body = document.createElement("p");
        body.textContent = "필수 역할을 맡은 표본이 검색 자료에 없어 새 IT 제안을 만들지 않았습니다. 정책이 없다는 판정은 아닙니다.";
        warning.append(title, body);
        target.appendChild(warning);
      }
    });
  }

  function renderAnswers() {
    if (!state.response) return;
    var monitor = state.response.branches.monitor;
    var laptop = state.response.branches.laptop;
    var pieces = [];
    if (monitor.answer.text) pieces.push("모니터: " + monitor.answer.text);
    if (laptop.answer.text) pieces.push("노트북: " + laptop.answer.text);
    all("[data-answer-text]").forEach(function (node) { node.textContent = pieces.join(" "); });
    all("[data-missing-monitor-answer]").forEach(function (node) {
      node.textContent = monitor.answer.text || "모니터 답변도 필요한 근거가 부족합니다.";
    });
    all(".result-list").forEach(function (list) {
      list.replaceChildren();
      [["모니터", monitor], ["노트북", laptop]].forEach(function (entry) {
        var item = document.createElement("li");
        var mark = document.createElement("span");
        mark.className = "check";
        mark.textContent = entry[1].answer.text ? "✓" : "?";
        var text = document.createElement("span");
        var strong = document.createElement("strong");
        strong.textContent = entry[0] + ": ";
        text.append(strong, document.createTextNode(entry[1].answer.text || "필수 근거가 부족해 새 답과 문의 글 제안을 보류했습니다."));
        item.append(mark, text);
        list.appendChild(item);
      });
      var boundaryItem = document.createElement("li");
      var boundaryMark = document.createElement("span");
      boundaryMark.className = "check";
      boundaryMark.textContent = "?";
      var boundaryText = document.createElement("span");
      var boundaryTitle = document.createElement("strong");
      boundaryTitle.textContent = "공개 표본으로 확인하지 못한 내용: ";
      boundaryText.append(
        boundaryTitle,
        document.createTextNode(
          "모니터와 노트북 요청을 같은 신청으로 묶을 수 있는지, 개인의 남은 수당과 실제 적용 여부는 확인하지 못했습니다."
        )
      );
      boundaryItem.append(boundaryMark, boundaryText);
      list.appendChild(boundaryItem);
    });
  }

  function render() {
    syncMode();
    syncDemoState();
    syncPanel();
    syncDraftTabs();
    syncSteps();
    syncConditions();
    syncDrafts();
    syncInputChangedNotice();
    renderEvidence();
    renderAnswers();
  }

  function acceptResponse(apiResponse, inputRevision) {
    state.response = apiResponse.result;
    state.demoState = apiResponse.ui_state;
    ["monitor", "it"].forEach(function (key) {
      var branchKey = key === "it" ? "laptop" : key;
      var proposal = state.response.branches[branchKey].draft_proposal;
      state.proposals[key] = proposal.status === "available_rule_composed" ? proposal : null;
      state.proposalInputRevision[key] = inputRevision;
      if (state.drafts[key] === undefined && state.proposals[key]) {
        state.drafts[key] = state.proposals[key].text;
        state.sourceRevision[key] = state.proposals[key].revision;
        state.draftTouched[key] = false;
      } else if (state.drafts[key] === undefined) {
        state.drafts[key] = "";
      }
    });
    state.lastSettledDemoState = state.demoState;
    if (state.demoState === "missing" && state.activeDraft === "it") state.activeDraft = "monitor";
    render();
  }

  async function refreshWorkspace(options) {
    options = options || {};
    if (Object.prototype.hasOwnProperty.call(options, "excludeLaptop")) state.excludeLaptopEvidence = options.excludeLaptop;
    var requestId = ++state.requestSequence;
    var requestInputRevision = state.inputRevision;
    state.currentRequestId = requestId;
    state.demoState = "loading";
    syncDemoState();
    try {
      var response = await fetch("/api/workspace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload(requestId))
      });
      var body = await response.json();
      if (requestId !== state.currentRequestId) return;
      if (!response.ok) throw new Error(body.error && body.error.message ? body.error.message : "요청 처리 실패");
      if (body.client_request_id !== requestId) throw new Error("요청 순서가 일치하지 않습니다.");
      if (requestInputRevision !== state.inputRevision) {
        state.demoState = state.lastSettledDemoState || "error";
        render();
        showToast("입력한 내용이 요청 중에 바뀌어 이전 응답을 사용하지 않았습니다. 현재 입력으로 새 제안을 만들어 주세요.");
        return;
      }
      acceptResponse(body, requestInputRevision);
      if (options.message) showToast(options.message);
    } catch (error) {
      if (requestId !== state.currentRequestId) return;
      state.demoState = "error";
      syncDemoState();
      showToast("연결에 실패했습니다. 작성 중인 글은 그대로 남겨 두었습니다.");
    }
  }

  function applyProposal(key) {
    var proposal = state.proposals[key];
    if (!proposal) {
      showToast("현재 참고 문서로는 이 문의 글의 새 제안을 만들 수 없습니다.");
      return;
    }
    if (state.proposalInputRevision[key] !== state.inputRevision) {
      showToast("입력한 내용이 바뀌었습니다. 현재 입력으로 새 제안을 만든 뒤 반영해 주세요.");
      return;
    }
    state.drafts[key] = proposal.text;
    state.sourceRevision[key] = proposal.revision;
    state.draftTouched[key] = false;
    syncDrafts();
    showToast("현재 제안을 문의 글에 반영했습니다.");
  }

  function visibleDraftArea(key) {
    var areas = all('[data-draft-area="' + key + '"]');
    return areas.find(function (area) { return area.offsetParent !== null; }) || areas[0];
  }

  async function copyDraft(key) {
    var text = state.drafts[key] || "";
    try {
      if (!navigator.clipboard || !window.isSecureContext) throw new Error("clipboard-unavailable");
      await navigator.clipboard.writeText(text);
      showToast("문의 글을 클립보드에 복사했습니다.");
    } catch (error) {
      var area = visibleDraftArea(key);
      area.focus();
      area.select();
      area.setSelectionRange(0, area.value.length);
      showToast("자동 복사가 허용되지 않았습니다. 글 전체를 선택했으니 Ctrl/Cmd+C로 복사해 주세요.");
    }
  }

  all(".mode-switch button[data-mode]").forEach(function (button) {
    button.addEventListener("click", function () { state.mode = button.dataset.mode; syncMode(); });
  });
  all("[data-demo-state-button]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (button.dataset.demoStateButton === "missing") refreshWorkspace({ excludeLaptop: true, message: "노트북 핵심 표본을 제외한 실제 처리 결과입니다." });
      else refreshWorkspace({ excludeLaptop: false, message: "현재 입력과 검색 자료로 다시 확인했습니다." });
    });
  });
  all("[data-open-panel]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.panelTab = button.dataset.openPanel;
      if (state.panelTab === "draft") state.activeDraft = "it";
      syncPanel(); syncDraftTabs();
      document.querySelector(".context-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });
  all("[data-panel-tab]").forEach(function (button) {
    button.addEventListener("click", function () { state.panelTab = button.dataset.panelTab; syncPanel(); });
  });
  all("[data-draft-tab]").forEach(function (button) {
    button.addEventListener("click", function () { state.activeDraft = button.dataset.draftTab; syncDraftTabs(); });
  });
  all("[data-step]").forEach(function (button) {
    button.addEventListener("click", function () { state.step = button.dataset.step; syncSteps(); });
  });
  all("[data-go-step]").forEach(function (button) {
    button.addEventListener("click", function () { state.step = button.dataset.goStep; syncSteps(); });
  });
  all("[data-field]").forEach(function (field) {
    field.addEventListener("input", function () {
      var key = field.dataset.field;
      if (state.conditions[key] === field.value) return;
      state.conditions[key] = field.value;
      state.inputRevision += 1;
      syncConditions();
      syncDrafts();
      syncInputChangedNotice();
    });
  });
  all("[data-fill-conditions]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.conditions = { tenure: "4년", symptom: "지난주부터 화상회의 중", purchase: "not-purchased" };
      state.inputRevision += 1;
      syncConditions();
      refreshWorkspace({ message: "예시 정보로 새 제안을 만들었습니다. 작성 중인 글은 아직 바꾸지 않았습니다." });
    });
  });
  all("[data-clear-conditions]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.conditions = { tenure: "", symptom: "", purchase: "" };
      state.inputRevision += 1;
      syncConditions();
      refreshWorkspace({ message: "입력 내용을 비우고 새 제안을 만들었습니다. 작성 중인 글은 유지했습니다." });
    });
  });
  all("[data-apply-conditions]").forEach(function (button) {
    button.addEventListener("click", function () { refreshWorkspace({ message: "현재 입력으로 새 제안을 만들었습니다. 적용 전 내용을 확인해 주세요." }); });
  });
  all("[data-draft-area]").forEach(function (area) {
    area.addEventListener("input", function () {
      var key = area.dataset.draftArea;
      state.drafts[key] = area.value;
      state.draftTouched[key] = true;
      syncDrafts(area);
    });
  });
  all("[data-reset-draft]").forEach(function (button) {
    button.addEventListener("click", function () { applyProposal(button.dataset.resetDraft); });
  });
  all("[data-copy-draft]").forEach(function (button) {
    button.addEventListener("click", function () { copyDraft(button.dataset.copyDraft); });
  });
  all("[data-retry]").forEach(function (button) {
    button.addEventListener("click", function () { refreshWorkspace({ excludeLaptop: false, message: "검색 자료를 되돌려 다시 확인했습니다." }); });
  });
  all("[data-new-inquiry]").forEach(function (button) {
    button.addEventListener("click", function () { showToast("현재 로컬 앱은 장비 문의 한 가지를 지원하며 새로고침하면 입력과 편집 내용이 초기화됩니다."); });
  });

  render();
  refreshWorkspace();
})();
