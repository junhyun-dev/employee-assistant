(function () {
  "use strict";

  var QUESTION = "재택용 모니터와 느려진 회사 노트북을 같이 바꾸고 싶은데, 같은 경비 신청으로 처리하면 돼?";
  var draftStore = window.EmployeeAssistantDraftStore;
  var state = {
    mode: "conversation",
    demoState: "loading",
    panelTab: "evidence",
    activeDraft: "monitor",
    step: "4",
    conditions: { tenure: "", symptom: "", purchase: "" },
    drafts: { monitor: undefined, it: undefined },
    draftTouched: { monitor: false, it: false },
    draftInputRevision: { monitor: null, it: null },
    sourceRevision: { monitor: null, it: null },
    sourceProposalSignature: { monitor: null, it: null },
    proposals: { monitor: null, it: null },
    proposalInputRevision: { monitor: null, it: null },
    response: null,
    excludeLaptopEvidence: false,
    inputRevision: 0,
    branchInputRevision: { monitor: 0, it: 0 },
    requestSequence: 0,
    currentRequestId: 0,
    lastSettledDemoState: null,
    restoredDraft: { monitor: false, it: false },
    workspaceRevision: 0,
    storage: {
      status: "checking",
      revision: 0,
      savedAt: null,
      expiresAt: null,
      savedContentSignature: null,
      writableRevision: null,
      opaqueToken: null,
      busy: null,
      lastError: null
    },
    leaveProtection: {
      initialSignature: null,
      baselineSignature: null,
      baselineKind: null,
      storageRevision: null,
      userMutationRevision: 0,
      listening: false
    },
    restoreReview: null,
    deleteReview: null,
    newInquiryReview: null,
    copyReview: null,
    proposalReview: null,
    evidenceView: {
      scope: "all",
      branch: null,
      returnContext: null,
      responseSignature: null
    },
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

  function formatLocalTime(value) {
    var date = new Date(value);
    if (!Number.isFinite(date.getTime())) return "알 수 없는 시각";
    return new Intl.DateTimeFormat("ko-KR", {
      month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"
    }).format(date);
  }

  function draftSnapshot() {
    return {
      inquiry_type: "monitor_and_laptop_replacement",
      employee_input: {
        tenure: state.conditions.tenure,
        symptom: state.conditions.symptom,
        purchase: state.conditions.purchase
      },
      drafts: {
        monitor: state.drafts.monitor || "",
        it: state.drafts.it || ""
      },
      edit_meta: {
        monitor_touched: Boolean(state.draftTouched.monitor),
        it_touched: Boolean(state.draftTouched.it)
      },
      ui: {
        mode: state.mode,
        active_draft: state.activeDraft
      }
    };
  }

  function contentSignature(snapshot) {
    return JSON.stringify({ employee_input: snapshot.employee_input, drafts: snapshot.drafts });
  }

  function currentContentSignature() {
    return contentSignature(draftSnapshot());
  }

  function savedLeaveBaselineIsAvailable() {
    var leave = state.leaveProtection;
    if (leave.baselineKind !== "saved") return true;
    return state.storage.status === "available" &&
      state.storage.revision === leave.storageRevision;
  }

  function hasUnsavedContentChanges() {
    var leave = state.leaveProtection;
    var current = currentContentSignature();
    if (leave.initialSignature !== null && current === leave.initialSignature) return false;
    if (leave.baselineSignature === null) return leave.userMutationRevision > 0;
    if (current !== leave.baselineSignature) return true;
    return !savedLeaveBaselineIsAvailable();
  }

  function handleBeforeUnload(event) {
    if (!hasUnsavedContentChanges()) return;
    event.preventDefault();
    event.returnValue = "";
  }

  function syncBeforeUnloadProtection() {
    var shouldListen = hasUnsavedContentChanges();
    if (shouldListen && !state.leaveProtection.listening) {
      window.addEventListener("beforeunload", handleBeforeUnload);
      state.leaveProtection.listening = true;
    } else if (!shouldListen && state.leaveProtection.listening) {
      window.removeEventListener("beforeunload", handleBeforeUnload);
      state.leaveProtection.listening = false;
    }
  }

  function setLeaveBaseline(signature, kind, storageRevision) {
    state.leaveProtection.baselineSignature = signature;
    state.leaveProtection.baselineKind = kind;
    state.leaveProtection.storageRevision = kind === "saved" ? storageRevision : null;
    syncBeforeUnloadProtection();
  }

  function resetLeaveProtectionForNewInquiry() {
    state.leaveProtection.initialSignature = null;
    state.leaveProtection.baselineSignature = null;
    state.leaveProtection.baselineKind = null;
    state.leaveProtection.storageRevision = null;
    state.leaveProtection.userMutationRevision = 0;
    syncBeforeUnloadProtection();
  }

  function markWorkspaceChanged() {
    state.leaveProtection.userMutationRevision += 1;
    state.workspaceRevision += 1;
    syncStorageUI();
    syncActionDialogs();
  }

  function hasInitializedDrafts() {
    return typeof state.drafts.monitor === "string" && typeof state.drafts.it === "string";
  }

  function setStorageMetadata(metadata, options) {
    options = options || {};
    var priorRevision = state.storage.revision;
    state.storage.status = metadata.status;
    state.storage.revision = metadata.revision;
    state.storage.savedAt = metadata.saved_at;
    state.storage.expiresAt = metadata.expires_at;
    state.storage.opaqueToken = metadata.opaque_token || null;
    state.storage.lastError = options.error || null;
    if (metadata.status !== "available" || priorRevision !== metadata.revision) {
      state.storage.savedContentSignature = options.savedContentSignature || null;
    } else if (options.savedContentSignature) {
      state.storage.savedContentSignature = options.savedContentSignature;
    }
    if (Object.prototype.hasOwnProperty.call(options, "writableRevision")) {
      state.storage.writableRevision = options.writableRevision;
    } else if (metadata.status === "available") {
      state.storage.writableRevision = null;
    } else {
      state.storage.writableRevision = metadata.revision;
    }
    syncStorageUI();
    syncActionDialogs();
  }

  function syncStorageUI() {
    var status = document.getElementById("draftStorageStatus");
    if (!status) return;
    var storage = state.storage;
    var message;
    var statusKind = storage.status;
    if (storage.status === "checking") {
      message = "저장본을 확인하고 있습니다.";
    } else if (storage.status === "unavailable") {
      message = storage.lastError || "임시 저장소를 사용할 수 없습니다. 현재 글과 복사 기능은 그대로 사용할 수 있습니다.";
      statusKind = "error";
    } else if (storage.busy === "saving") {
      message = "현재 입력과 글을 임시 저장하고 있습니다.";
    } else if (storage.busy === "loading") {
      message = "저장한 글을 불러오고 있습니다. 그동안 화면을 바꾸면 불러오기를 중단합니다.";
    } else if (storage.busy === "deleting") {
      message = "저장본만 삭제하고 있습니다. 현재 화면의 글은 유지합니다.";
    } else if (storage.lastError) {
      message = storage.lastError + " 현재 화면의 글은 남아 있지만 새로고침하면 저장하지 않은 변경은 사라집니다.";
      statusKind = "error";
    } else if (storage.status === "available") {
      var saved = formatLocalTime(storage.savedAt);
      var expires = formatLocalTime(storage.expiresAt);
      if (storage.savedContentSignature && storage.savedContentSignature !== currentContentSignature()) {
        message = saved + " 저장 · 저장 이후 입력이나 글이 바뀌었습니다. 새로고침하면 마지막 저장 뒤 변경은 사라집니다.";
        statusKind = "changed";
      } else if (state.restoredDraft.monitor || state.restoredDraft.it) {
        message = saved + " 저장본을 불러왔습니다 · " + expires + "까지. 현재 문서로 다시 확인한 뒤 새 제안을 따로 반영할 수 있습니다.";
      } else if (storage.writableRevision !== storage.revision) {
        message = saved + " 저장본이 있습니다 · " + expires + "까지. 자동으로 열거나 덮어쓰지 않습니다. 먼저 불러오거나 삭제해 주세요.";
      } else {
        message = saved + " 저장 · " + expires + "까지. 현재 화면은 마지막 저장본과 같습니다.";
      }
    } else if (storage.status === "expired") {
      message = "24시간이 지난 저장 내용은 이 브라우저에서 지웠습니다. 현재 화면은 새로 저장할 수 있습니다.";
    } else if (storage.status === "unreadable") {
      message = "이 버전에서 읽을 수 없는 저장본이 남아 있습니다. 현재 글에는 섞지 않았습니다. 저장하거나 불러오려면 먼저 저장본 삭제를 선택해 주세요.";
      statusKind = "error";
    } else if (storage.writableRevision !== storage.revision) {
      message = "다른 탭에서 저장본이 바뀌거나 삭제되었습니다. 현재의 오래된 글을 새 저장본으로 되살리지 않습니다. 필요하면 새 문의로 시작해 다시 저장해 주세요.";
      statusKind = "changed";
    } else {
      message = "임시 저장본이 없습니다. 버튼을 눌렀을 때만 현재 입력과 두 문의 글을 저장합니다.";
    }
    status.dataset.state = statusKind;
    status.textContent = message;
    var unavailable = storage.status === "checking" || storage.status === "unavailable" || Boolean(storage.busy);
    var maySave = !unavailable && hasInitializedDrafts() && storage.writableRevision === storage.revision;
    all("[data-save-draft]").forEach(function (button) { button.disabled = !maySave; });
    all("[data-restore-draft]").forEach(function (button) { button.disabled = unavailable || storage.status !== "available"; });
    all("[data-delete-saved]").forEach(function (button) {
      button.disabled = unavailable || !["available", "unreadable"].includes(storage.status);
    });
    syncBeforeUnloadProtection();
  }

  function syncRestoredDraftAccess() {
    all('[data-restored-draft-access="it"]').forEach(function (node) { node.hidden = !state.restoredDraft.it; });
    all('[data-withheld-draft="it"]').forEach(function (node) { node.hidden = state.restoredDraft.it; });
  }

  function syncActionDialogs() {
    var restoreDialog = document.getElementById("restoreDraftDialog");
    if (restoreDialog && restoreDialog.open && state.restoreReview) {
      var restoreChanged = state.restoreReview.workspaceRevision !== state.workspaceRevision ||
        state.restoreReview.storageRevision !== state.storage.revision;
      var restoreStatus = document.getElementById("restoreDraftStatus");
      restoreStatus.dataset.state = restoreChanged ? "changed" : "current";
      restoreStatus.textContent = restoreChanged
        ? "확인창을 연 뒤 현재 글이나 저장본이 바뀌었습니다. 닫고 다시 확인해 주세요."
        : "현재 화면과 저장본 판본을 확인했습니다.";
      restoreDialog.querySelector("[data-restore-confirm]").disabled = restoreChanged || Boolean(state.storage.busy);
    }
    var deleteDialog = document.getElementById("deleteSavedDialog");
    if (deleteDialog && deleteDialog.open && state.deleteReview) {
      var deleteChanged = state.deleteReview.storageRevision !== state.storage.revision ||
        state.deleteReview.storageStatus !== state.storage.status ||
        state.deleteReview.opaqueToken !== state.storage.opaqueToken;
      var deleteStatus = document.getElementById("deleteSavedStatus");
      deleteStatus.dataset.state = deleteChanged ? "changed" : "current";
      deleteStatus.textContent = deleteChanged
        ? "확인창을 연 뒤 저장본이 바뀌었습니다. 새 저장본은 삭제하지 않습니다."
        : "현재 화면의 글은 유지하고 이 판본의 저장 내용만 삭제합니다.";
      deleteDialog.querySelector("[data-delete-confirm]").disabled = deleteChanged || Boolean(state.storage.busy);
    }
    var newDialog = document.getElementById("newInquiryDialog");
    if (newDialog && newDialog.open && state.newInquiryReview) {
      var newChanged = state.newInquiryReview.workspaceRevision !== state.workspaceRevision;
      var newStatus = document.getElementById("newInquiryStatus");
      newStatus.dataset.state = newChanged ? "changed" : "current";
      newStatus.textContent = newChanged
        ? "확인창을 연 뒤 입력이나 글이 바뀌었습니다. 닫고 현재 내용으로 다시 확인해 주세요."
        : "저장하지 않은 변경은 다시 불러올 수 없습니다. 임시 저장본은 삭제하지 않습니다.";
      newDialog.querySelector("[data-new-inquiry-confirm]").disabled = newChanged;
    }
    syncProposalReview();
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
    var contentState = state.demoState;
    if ((contentState === "loading" || contentState === "error") && state.lastSettledDemoState) {
      contentState = state.lastSettledDemoState;
    }
    document.body.dataset.contentState = contentState;
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
    syncProposalButtons();
    syncProposalReview();
    syncCopyReview();
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

  function evidenceBranchLabel(branchName) {
    return branchName === "laptop" ? "노트북" : "모니터";
  }

  function answerEvidenceRelation(branchName) {
    if (!state.response || !state.response.branches[branchName]) {
      return { status: "unavailable", answer: null, evidenceIds: [], sections: [], unresolvedIds: [] };
    }
    var answer = state.response.branches[branchName].answer;
    if (!answer || !answer.text || !Array.isArray(answer.evidence_ids) || !answer.evidence_ids.length) {
      return { status: "withheld", answer: answer, evidenceIds: [], sections: [], unresolvedIds: [] };
    }
    var sectionById = {};
    state.response.material.evidence.forEach(function (section) { sectionById[section.id] = section; });
    var sections = [];
    var unresolvedIds = [];
    answer.evidence_ids.forEach(function (id) {
      if (sectionById[id]) sections.push(sectionById[id]);
      else unresolvedIds.push(id);
    });
    return {
      status: unresolvedIds.length ? "unresolved" : "linked",
      answer: answer,
      evidenceIds: answer.evidence_ids.slice(),
      sections: sections,
      unresolvedIds: unresolvedIds
    };
  }

  function answerEvidenceSignature(branchName) {
    var relation = answerEvidenceRelation(branchName);
    return JSON.stringify({
      requestId: state.currentRequestId,
      inputRevision: state.inputRevision,
      branch: branchName,
      answerText: relation.answer ? relation.answer.text : null,
      answerEvidenceIds: relation.evidenceIds,
      materialEvidenceIds: state.response ? state.response.material.evidence_ids : []
    });
  }

  function resetEvidenceView() {
    state.evidenceView = {
      scope: "all",
      branch: null,
      returnContext: null,
      responseSignature: null
    };
  }

  function syncAnswerEvidenceButtons() {
    all("[data-open-answer-evidence]").forEach(function (button) {
      var relation = answerEvidenceRelation(button.dataset.openAnswerEvidence);
      var available = relation.status === "linked" || relation.status === "unresolved";
      button.hidden = !available;
      button.disabled = !available || state.demoState === "loading" || state.demoState === "error";
    });
  }

  function focusEvidenceView() {
    var heading = document.querySelector("[data-evidence-view-title]");
    if (!heading || heading.offsetParent === null) return;
    try { heading.focus({ preventScroll: true }); }
    catch (error) { heading.focus(); }
    heading.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function openAnswerEvidence(branchName, trigger) {
    var relation = answerEvidenceRelation(branchName);
    if (state.demoState === "loading" || state.demoState === "error" ||
        !["linked", "unresolved"].includes(relation.status)) {
      showToast("이 답에 연결된 참고 문서를 현재 결과에서 확인할 수 없습니다.");
      return;
    }
    state.evidenceView = {
      scope: "branch",
      branch: branchName,
      returnContext: {
        mode: state.mode,
        panelTab: state.panelTab,
        step: state.step,
        trigger: trigger
      },
      responseSignature: answerEvidenceSignature(branchName)
    };
    state.mode = "conversation";
    state.panelTab = "evidence";
    syncMode();
    syncPanel();
    renderEvidence();
    window.requestAnimationFrame(focusEvidenceView);
  }

  function showAllEvidence() {
    state.evidenceView.scope = "all";
    state.evidenceView.branch = null;
    state.evidenceView.responseSignature = null;
    renderEvidence();
    window.requestAnimationFrame(focusEvidenceView);
  }

  function returnToAnswer() {
    var context = state.evidenceView.returnContext;
    if (!context) return;
    var trigger = context.trigger;
    resetEvidenceView();
    state.mode = context.mode;
    state.panelTab = context.panelTab;
    state.step = context.step;
    syncMode();
    syncPanel();
    syncSteps();
    renderEvidence();
    window.requestAnimationFrame(function () {
      if (!trigger || !trigger.isConnected || trigger.offsetParent === null) return;
      try { trigger.focus({ preventScroll: true }); }
      catch (error) { trigger.focus(); }
      trigger.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
    if (state.restoredDraft[branchName]) {
      if (!proposal) {
        return { kind: "review", text: "임시 저장에서 불러온 글입니다. 현재 참고 문서로는 이 갈래의 새 제안을 만들지 않았지만, 불러온 글은 계속 고치거나 복사할 수 있습니다." };
      }
      return { kind: "review", text: "임시 저장에서 불러온 글입니다. 현재 검색 결과로 만든 새 제안과 자동으로 같다고 보지 않습니다. 내용을 확인한 뒤 새 제안을 명시적으로 반영할 수 있습니다." };
    }
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
      if (area.closest("[data-restored-draft-access]") && !state.restoredDraft[key]) {
        var hiddenNote = area.parentNode.querySelector('[data-proposal-note="' + key + '"]');
        if (hiddenNote) hiddenNote.remove();
        return;
      }
      var status = draftStatus(key);
      var note = ensureProposalNote(area);
      note.dataset.status = status.kind;
      note.textContent = status.text;
    });
    syncProposalButtons();
    syncProposalReview();
    syncCopyReview();
  }

  function branchLabel(key) {
    return key === "it" ? "IT 문의 글" : "모니터 문의 글";
  }

  function proposalSourceSignature(proposal) {
    if (!proposal || !state.response) return null;
    var evidenceById = {};
    state.response.material.evidence.forEach(function (section) { evidenceById[section.id] = section; });
    return JSON.stringify({
      text: proposal.text,
      evidence: proposal.evidence_ids.map(function (id) { return evidenceById[id]; })
    });
  }

  function proposalCanBeReviewed(key) {
    return Boolean(state.proposals[key]) &&
      ["normal", "missing"].includes(state.demoState) &&
      state.proposalInputRevision[key] === state.inputRevision;
  }

  function syncProposalButtons() {
    all("[data-reset-draft]").forEach(function (button) {
      button.disabled = !proposalCanBeReviewed(button.dataset.resetDraft);
    });
  }

  function proposalReviewFingerprint(key) {
    var proposal = state.proposals[key];
    var evidenceIds = state.response ? state.response.material.evidence_ids : [];
    return JSON.stringify({
      key: key,
      currentDraft: state.drafts[key] || "",
      draftTouched: state.draftTouched[key],
      restoredDraft: state.restoredDraft[key],
      draftInputRevision: state.draftInputRevision[key],
      sourceRevision: state.sourceRevision[key],
      sourceProposalSignature: state.sourceProposalSignature[key],
      inputRevision: state.inputRevision,
      branchInputRevision: state.branchInputRevision[key],
      proposalInputRevision: state.proposalInputRevision[key],
      proposalText: proposal ? proposal.text : null,
      proposalRevision: proposal ? proposal.revision : null,
      proposalSourceSignature: proposalSourceSignature(proposal),
      demoState: state.demoState,
      requestId: state.currentRequestId,
      excludeLaptopEvidence: state.excludeLaptopEvidence,
      evidenceIds: evidenceIds
    });
  }

  function syncProposalReview() {
    var dialog = document.getElementById("proposalReviewDialog");
    if (!dialog || !dialog.open || !state.proposalReview) return;
    var review = state.proposalReview;
    var changed = !proposalCanBeReviewed(review.key) ||
      review.fingerprint !== proposalReviewFingerprint(review.key);
    var status = document.getElementById("proposalReviewStatus");
    var confirm = dialog.querySelector("[data-proposal-review-confirm]");
    confirm.disabled = changed;
    status.dataset.state = changed ? "changed" : "current";
    status.textContent = changed
      ? "비교창을 연 뒤 입력·문의 글·검색 결과 또는 제안이 바뀌었습니다. 현재 상태에서 다시 비교해 주세요."
      : "현재 화면과 같은 글과 제안입니다. 새 제안으로 바꾸면 현재 글 전체가 교체됩니다.";
  }

  function proposalUnavailableMessage(key) {
    if (state.demoState === "loading") return "문서를 확인하는 중입니다. 확인이 끝난 뒤 새 제안을 비교해 주세요.";
    if (state.demoState === "error") return "최근 문서 확인 결과를 받지 못해 새 제안을 비교할 수 없습니다.";
    if (!state.proposals[key]) return "현재 참고 문서로는 이 문의 글의 새 제안을 만들 수 없습니다.";
    return "입력한 내용이 바뀌었습니다. 현재 입력으로 새 제안을 만든 뒤 비교해 주세요.";
  }

  function appendProposalDiff(node, segments, markedKind) {
    node.replaceChildren();
    segments.forEach(function (segment) {
      if (segment.kind !== markedKind) {
        node.appendChild(document.createTextNode(segment.text));
        return;
      }
      var marker = document.createElement(markedKind === "removed" ? "del" : "ins");
      marker.className = "proposal-diff-" + markedKind;
      marker.textContent = segment.text;
      node.appendChild(marker);
    });
  }

  function renderProposalComparison(review) {
    var comparison = review.comparison;
    var current = document.getElementById("proposalReviewCurrent");
    var proposed = document.getElementById("proposalReviewProposed");
    var summary = document.getElementById("proposalReviewDiffSummary");
    var legend = document.getElementById("proposalReviewDiffLegend");
    appendProposalDiff(current, comparison.current, "removed");
    appendProposalDiff(proposed, comparison.proposed, "added");
    if (comparison.status === "identical") {
      legend.hidden = true;
      summary.textContent = "두 글의 문자가 같습니다. 참고 문서와 제안 판본을 새로 채택하려면 같은 비교 경로에서 바꿀 수 있습니다.";
    } else if (comparison.status === "fallback") {
      legend.hidden = true;
      summary.textContent = "글이 길어 세부 차이 표시는 생략했습니다. 잘리지 않은 두 전체 글을 직접 비교해 주세요.";
    } else {
      legend.hidden = false;
      summary.textContent = "취소선은 현재 글에서 빠질 문자이고, 밑줄은 새 제안에 더해질 문자입니다.";
    }
  }

  function openProposalReview(key) {
    if (!proposalCanBeReviewed(key)) {
      showToast(proposalUnavailableMessage(key));
      return;
    }
    var proposal = state.proposals[key];
    state.proposalReview = {
      key: key,
      currentDraft: state.drafts[key] || "",
      proposalText: proposal.text,
      proposalRevision: proposal.revision,
      proposalSourceSignature: proposalSourceSignature(proposal),
      fingerprint: proposalReviewFingerprint(key),
      comparison: window.EmployeeAssistantTextDiff.compare(state.drafts[key] || "", proposal.text)
    };
    document.getElementById("proposalReviewTitle").textContent = branchLabel(key) + "의 두 글을 비교해 보세요";
    renderProposalComparison(state.proposalReview);
    document.getElementById("proposalReviewDialog").showModal();
    syncProposalReview();
  }

  function closeProposalReview() {
    var dialog = document.getElementById("proposalReviewDialog");
    if (dialog.open) dialog.close();
    state.proposalReview = null;
  }

  function copyReviewReasons(key) {
    var reasons = [];
    if (state.restoredDraft[key]) {
      reasons.push("임시 저장에서 불러온 글이며, 현재 참고 문서로 만든 새 제안을 아직 반영하지 않았습니다.");
    }
    if (state.draftInputRevision[key] !== null && state.draftInputRevision[key] !== state.branchInputRevision[key]) {
      reasons.push("입력한 내용이 이 글의 바탕이 된 제안 이후 바뀌었습니다.");
    }
    if (state.demoState === "loading") {
      reasons.push("현재 입력과 자료로 문서를 다시 확인하는 중입니다.");
    } else if (state.demoState === "error") {
      reasons.push("최근 문서 확인 요청의 결과를 받지 못했습니다.");
    }
    var proposal = state.proposals[key];
    if (!proposal) {
      reasons.push(key === "it"
        ? "노트북 문의에 필요한 핵심 문서를 현재 확인하지 못했습니다."
        : "모니터 문의에 필요한 핵심 문서를 현재 확인하지 못했습니다.");
    } else if (state.sourceProposalSignature[key] !== proposalSourceSignature(proposal)) {
      reasons.push("검색 결과가 바뀐 뒤 현재 글에 새 제안을 반영하지 않았습니다.");
    }
    return reasons;
  }

  function copyFingerprint(key) {
    var proposal = state.proposals[key];
    var evidenceIds = state.response ? state.response.material.evidence_ids : [];
    return JSON.stringify({
      key: key,
      text: state.drafts[key] || "",
      inputRevision: state.inputRevision,
      branchInputRevision: state.branchInputRevision[key],
      draftInputRevision: state.draftInputRevision[key],
      demoState: state.demoState,
      requestId: state.currentRequestId,
      excludeLaptopEvidence: state.excludeLaptopEvidence,
      proposalRevision: proposal ? proposal.revision : null,
      proposalInputRevision: state.proposalInputRevision[key],
      sourceRevision: state.sourceRevision[key],
      sourceProposalSignature: state.sourceProposalSignature[key],
      currentProposalSignature: proposalSourceSignature(proposal),
      evidenceIds: evidenceIds
    });
  }

  function syncCopyReview() {
    var dialog = document.getElementById("copyReviewDialog");
    if (!dialog || !dialog.open || !state.copyReview) return;
    var changed = state.copyReview.fingerprint !== copyFingerprint(state.copyReview.key);
    var status = document.getElementById("copyReviewStatus");
    var confirm = dialog.querySelector("[data-copy-review-confirm]");
    confirm.disabled = changed;
    status.dataset.state = changed ? "changed" : "current";
    status.textContent = changed
      ? "확인창을 연 뒤 입력·문의 글·검색 상태가 바뀌었습니다. 돌아가서 현재 상태로 다시 확인해 주세요."
      : "현재 화면과 같은 글입니다. 그대로 복사할지 선택해 주세요.";
  }

  function openCopyReview(key, reasons) {
    var dialog = document.getElementById("copyReviewDialog");
    state.copyReview = {
      key: key,
      text: state.drafts[key] || "",
      fingerprint: copyFingerprint(key)
    };
    document.getElementById("copyReviewTitle").textContent = branchLabel(key) + "을 복사하기 전에 확인해 주세요";
    var reasonList = document.getElementById("copyReviewReasons");
    reasonList.replaceChildren();
    reasons.forEach(function (reason) {
      var item = document.createElement("li");
      item.textContent = reason;
      reasonList.appendChild(item);
    });
    document.getElementById("copyReviewFacts").textContent = statedFactsText();
    document.getElementById("copyReviewDraft").textContent = state.copyReview.text;
    dialog.showModal();
    syncCopyReview();
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
    if (state.evidenceView.scope === "branch" &&
        state.evidenceView.responseSignature !== answerEvidenceSignature(state.evidenceView.branch)) {
      resetEvidenceView();
    }
    var relation = state.evidenceView.scope === "branch"
      ? answerEvidenceRelation(state.evidenceView.branch)
      : null;
    var sections = relation ? relation.sections : material.evidence;
    var title = document.querySelector("[data-evidence-view-title]");
    var summary = document.querySelector("[data-evidence-view-summary]");
    var showAll = document.querySelector("[data-show-all-evidence]");
    var returnButton = document.querySelector("[data-return-to-answer]");
    if (title) {
      title.textContent = relation
        ? evidenceBranchLabel(state.evidenceView.branch) + " 답에 사용한 참고 문서"
        : (state.demoState === "loading" || state.demoState === "error"
          ? "마지막으로 회수한 전체 문서"
          : "이번 검색에서 회수한 전체 문서");
    }
    if (summary) {
      summary.textContent = relation
        ? "현재 규칙이 이 답에 연결한 문서만 보여 줍니다. 문장별 의미 정확성이나 개인 자격을 확인했다는 표시는 아닙니다."
        : (state.demoState === "loading" || state.demoState === "error"
          ? "새 확인이 끝나기 전에는 이전의 특정 답과 문서를 최신 연결로 표시하지 않습니다."
          : "이번 요청에서 회수한 문서 전체입니다. 특정 답에 실제로 사용한 문서와는 구별합니다.");
    }
    if (showAll) showAll.hidden = !relation;
    if (returnButton) returnButton.hidden = !state.evidenceView.returnContext;
    var targets = all('.panel-content[data-panel-content="evidence"] .state-normal, .panel-content[data-panel-content="evidence"] .state-missing');
    targets.forEach(function (target) {
      target.replaceChildren();
      sections.forEach(function (section) { target.appendChild(makeSourceCard(section, material.source)); });
      if (relation && relation.unresolvedIds.length) {
        var unresolved = document.createElement("article");
        unresolved.className = "source-card missing";
        var unresolvedTitle = document.createElement("h3");
        unresolvedTitle.textContent = "답과 참고 문서 연결 미확인";
        var unresolvedBody = document.createElement("p");
        unresolvedBody.textContent = "답에 연결된 문서 ID가 이번 검색 결과에 없어 표시하지 않았습니다. 전체 목록이나 다른 갈래 문서로 대신 채우지 않습니다.";
        unresolved.append(unresolvedTitle, unresolvedBody);
        target.appendChild(unresolved);
      }
      if (!relation && state.demoState === "missing" && target.classList.contains("state-missing")) {
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
    syncAnswerEvidenceButtons();
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
        var branchName = entry[0] === "노트북" ? "laptop" : "monitor";
        var item = document.createElement("li");
        var mark = document.createElement("span");
        mark.className = "check";
        mark.textContent = entry[1].answer.text ? "✓" : "?";
        var text = document.createElement("span");
        var strong = document.createElement("strong");
        strong.textContent = entry[0] + ": ";
        text.append(strong, document.createTextNode(entry[1].answer.text || "필수 근거가 부족해 새 답과 문의 글 제안을 보류했습니다."));
        if (entry[1].answer.text && entry[1].answer.evidence_ids.length) {
          var evidenceButton = document.createElement("button");
          evidenceButton.type = "button";
          evidenceButton.className = "button ghost result-evidence-button";
          evidenceButton.dataset.openAnswerEvidence = branchName;
          evidenceButton.textContent = "이 답의 참고 문서 보기";
          text.appendChild(evidenceButton);
        }
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
    syncAnswerEvidenceButtons();
  }

  function render() {
    syncMode();
    syncDemoState();
    syncPanel();
    syncDraftTabs();
    syncSteps();
    syncConditions();
    syncDrafts();
    syncRestoredDraftAccess();
    syncStorageUI();
    syncActionDialogs();
    syncInputChangedNotice();
    renderEvidence();
    renderAnswers();
  }

  function acceptResponse(apiResponse, inputRevision) {
    var initializesNewInquiry = state.drafts.monitor === undefined && state.drafts.it === undefined;
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
        state.sourceProposalSignature[key] = proposalSourceSignature(state.proposals[key]);
        state.draftInputRevision[key] = state.branchInputRevision[key];
        state.draftTouched[key] = false;
        state.workspaceRevision += 1;
      } else if (state.drafts[key] === undefined) {
        state.drafts[key] = "";
        state.workspaceRevision += 1;
      }
    });
    state.lastSettledDemoState = state.demoState;
    if (state.demoState === "missing" && state.activeDraft === "it" && !state.restoredDraft.it) {
      state.activeDraft = "monitor";
    }
    if (initializesNewInquiry && state.leaveProtection.initialSignature === null &&
        state.leaveProtection.userMutationRevision === 0) {
      state.leaveProtection.initialSignature = currentContentSignature();
      setLeaveBaseline(state.leaveProtection.initialSignature, "initial");
    }
    render();
  }

  async function refreshWorkspace(options) {
    options = options || {};
    if (Object.prototype.hasOwnProperty.call(options, "excludeLaptop")) state.excludeLaptopEvidence = options.excludeLaptop;
    resetEvidenceView();
    var requestId = ++state.requestSequence;
    var requestInputRevision = state.inputRevision;
    state.currentRequestId = requestId;
    state.demoState = "loading";
    if (state.response) renderEvidence();
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

  function confirmProposalReview() {
    var review = state.proposalReview;
    if (!review || !proposalCanBeReviewed(review.key) ||
        review.fingerprint !== proposalReviewFingerprint(review.key)) {
      syncProposalReview();
      return;
    }
    var proposal = state.proposals[review.key];
    if (proposal.text !== review.proposalText ||
        proposal.revision !== review.proposalRevision ||
        proposalSourceSignature(proposal) !== review.proposalSourceSignature) {
      syncProposalReview();
      return;
    }
    var key = review.key;
    closeProposalReview();
    state.drafts[key] = review.proposalText;
    state.sourceRevision[key] = review.proposalRevision;
    state.sourceProposalSignature[key] = review.proposalSourceSignature;
    state.draftInputRevision[key] = state.branchInputRevision[key];
    state.draftTouched[key] = false;
    state.restoredDraft[key] = false;
    markWorkspaceChanged();
    syncDrafts();
    syncRestoredDraftAccess();
    showToast("비교한 새 제안으로 문의 글을 바꿨습니다.");
  }

  function visibleDraftArea(key) {
    var areas = all('[data-draft-area="' + key + '"]');
    return areas.find(function (area) { return area.offsetParent !== null; }) || areas[0];
  }

  function focusRestoredDraftArea() {
    var restoredArea = visibleDraftArea(state.activeDraft);
    if (!restoredArea || restoredArea.offsetParent === null) return;
    try { restoredArea.focus({ preventScroll: true }); }
    catch (error) { restoredArea.focus(); }
    restoredArea.scrollIntoView({ block: "center", inline: "nearest" });
  }

  function restoredFocusCheckpoint() {
    return {
      area: visibleDraftArea(state.activeDraft),
      inputRevision: state.inputRevision,
      workspaceRevision: state.workspaceRevision,
      mode: state.mode,
      panelTab: state.panelTab,
      step: state.step,
      activeDraft: state.activeDraft
    };
  }

  function mayRefocusRestoredDraft(checkpoint) {
    return checkpoint &&
      checkpoint.area === document.activeElement &&
      checkpoint.area === visibleDraftArea(state.activeDraft) &&
      checkpoint.inputRevision === state.inputRevision &&
      checkpoint.workspaceRevision === state.workspaceRevision &&
      checkpoint.mode === state.mode &&
      checkpoint.panelTab === state.panelTab &&
      checkpoint.step === state.step &&
      checkpoint.activeDraft === state.activeDraft;
  }

  async function writeDraftToClipboard(key, text) {
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

  function copyDraft(key) {
    var reasons = copyReviewReasons(key);
    if (reasons.length) {
      openCopyReview(key, reasons);
      return;
    }
    writeDraftToClipboard(key, state.drafts[key] || "");
  }

  function closeCopyReview() {
    var dialog = document.getElementById("copyReviewDialog");
    if (dialog.open) dialog.close();
    state.copyReview = null;
  }

  function confirmCopyReview() {
    if (!state.copyReview) return;
    if (state.copyReview.fingerprint !== copyFingerprint(state.copyReview.key)) {
      syncCopyReview();
      return;
    }
    var review = state.copyReview;
    closeCopyReview();
    writeDraftToClipboard(review.key, review.text);
  }

  function storageFailureMessage(error, action) {
    if (error && error.code === "conflict") return "다른 탭에서 저장본이 먼저 바뀌어 " + action + "하지 않았습니다. 현재 글은 그대로입니다.";
    if (error && (error.code === "expired" || error.code === "empty")) return "불러올 저장본이 없거나 24시간이 지나 삭제되었습니다.";
    if (error && error.code === "unreadable") return "이 버전에서 읽을 수 없는 저장본이 남아 있어 " + action + "하지 않았습니다.";
    if (error && error.code === "invalid") return "저장 내용의 형식이 맞지 않아 현재 글에 섞지 않았습니다.";
    return "임시 저장소 오류로 " + action + "하지 못했습니다.";
  }

  async function refreshStorageMetadata(options) {
    options = options || {};
    if (!draftStore) {
      state.storage.status = "unavailable";
      state.storage.lastError = "이 브라우저에서 임시 저장 기능을 시작하지 못했습니다.";
      syncStorageUI();
      return;
    }
    try {
      var metadata = await draftStore.inspect();
      var writableRevision = ["empty", "expired"].includes(metadata.status) ? metadata.revision : null;
      setStorageMetadata(metadata, {
        error: options.error || null,
        writableRevision: options.lockWritable ? null : writableRevision
      });
    } catch (error) {
      state.storage.status = "unavailable";
      state.storage.busy = null;
      state.storage.lastError = "이 브라우저에서 임시 저장소를 사용할 수 없습니다. 화면의 글과 복사는 계속 사용할 수 있습니다.";
      syncStorageUI();
    }
  }

  async function saveCurrentDraft() {
    if (!draftStore || state.storage.busy || !hasInitializedDrafts()) return;
    if (state.storage.status === "available" && state.storage.writableRevision !== state.storage.revision) {
      showToast("기존 저장본을 먼저 불러오거나 삭제한 뒤 현재 글을 저장해 주세요.");
      return;
    }
    var snapshot = draftSnapshot();
    var signature = contentSignature(snapshot);
    var expectedRevision = state.storage.revision;
    state.storage.busy = "saving";
    state.storage.lastError = null;
    syncStorageUI();
    try {
      var metadata = await draftStore.save(expectedRevision, snapshot);
      state.storage.busy = null;
      setStorageMetadata(metadata, {
        savedContentSignature: signature,
        writableRevision: metadata.revision
      });
      setLeaveBaseline(signature, "saved", metadata.revision);
      if (signature === currentContentSignature()) {
        showToast("현재 입력과 문의 글을 이 브라우저에 24시간 임시 저장했습니다.");
      } else {
        showToast("저장은 완료됐지만 저장 버튼을 누른 뒤 바꾼 내용은 포함되지 않았습니다.");
      }
    } catch (error) {
      state.storage.busy = null;
      var message = storageFailureMessage(error, "저장");
      await refreshStorageMetadata({ error: message, lockWritable: Boolean(error && error.code === "conflict") });
      showToast(message);
    }
  }

  function openRestoreDialog() {
    if (state.storage.status !== "available" || state.storage.busy) return;
    state.restoreReview = {
      storageRevision: state.storage.revision,
      workspaceRevision: state.workspaceRevision
    };
    document.getElementById("restoreDraftSavedAt").textContent = formatLocalTime(state.storage.savedAt) + "에 저장한 한 건을 불러옵니다.";
    document.getElementById("restoreDraftDialog").showModal();
    syncActionDialogs();
  }

  function closeRestoreDialog() {
    var dialog = document.getElementById("restoreDraftDialog");
    if (dialog.open) dialog.close();
    state.restoreReview = null;
  }

  function applyRestoredPayload(payload) {
    state.currentRequestId = ++state.requestSequence;
    state.conditions = {
      tenure: payload.employee_input.tenure,
      symptom: payload.employee_input.symptom,
      purchase: payload.employee_input.purchase
    };
    state.drafts = { monitor: payload.drafts.monitor, it: payload.drafts.it };
    state.draftTouched = {
      monitor: payload.edit_meta.monitor_touched,
      it: payload.edit_meta.it_touched
    };
    state.mode = payload.ui.mode;
    state.activeDraft = payload.ui.active_draft;
    if (state.mode === "conversation") state.panelTab = "draft";
    if (state.mode === "workflow") state.step = "4";
    state.inputRevision += 1;
    state.branchInputRevision.it += 1;
    state.draftInputRevision = {
      monitor: state.branchInputRevision.monitor,
      it: state.branchInputRevision.it
    };
    state.sourceRevision = { monitor: null, it: null };
    state.sourceProposalSignature = { monitor: null, it: null };
    state.proposals = { monitor: null, it: null };
    state.proposalInputRevision = { monitor: null, it: null };
    state.restoredDraft = { monitor: true, it: true };
    state.workspaceRevision += 1;
    if (!state.lastSettledDemoState) state.lastSettledDemoState = "normal";
    render();
    focusRestoredDraftArea();
  }

  async function confirmRestoreDraft() {
    var review = state.restoreReview;
    if (!review || review.workspaceRevision !== state.workspaceRevision || review.storageRevision !== state.storage.revision) {
      syncActionDialogs();
      return;
    }
    closeRestoreDialog();
    state.storage.busy = "loading";
    state.storage.lastError = null;
    syncStorageUI();
    try {
      var loaded = await draftStore.load(review.storageRevision);
      if (review.workspaceRevision !== state.workspaceRevision) {
        state.storage.busy = null;
        setStorageMetadata(loaded.metadata, { writableRevision: null });
        showToast("불러오는 동안 현재 글이 바뀌어 저장본을 덮어쓰지 않았습니다. 다시 불러오기를 선택해 주세요.");
        return;
      }
      applyRestoredPayload(loaded.payload);
      var focusCheckpoint = restoredFocusCheckpoint();
      state.storage.busy = null;
      setLeaveBaseline(contentSignature(loaded.payload), "saved", loaded.metadata.revision);
      setStorageMetadata(loaded.metadata, {
        savedContentSignature: contentSignature(loaded.payload),
        writableRevision: loaded.metadata.revision
      });
      showToast("저장한 글을 불러왔습니다. 현재 참고 문서는 다시 확인하며 글을 자동으로 바꾸지 않습니다.");
      await refreshWorkspace();
      if (mayRefocusRestoredDraft(focusCheckpoint)) focusRestoredDraftArea();
    } catch (error) {
      state.storage.busy = null;
      var message = storageFailureMessage(error, "불러오기");
      await refreshStorageMetadata({ error: message, lockWritable: Boolean(error && error.code === "conflict") });
      showToast(message);
    }
  }

  function openDeleteDialog() {
    if (!["available", "unreadable"].includes(state.storage.status) || state.storage.busy) return;
    state.deleteReview = {
      storageRevision: state.storage.revision,
      storageStatus: state.storage.status,
      opaqueToken: state.storage.opaqueToken
    };
    var unreadable = state.storage.status === "unreadable";
    document.getElementById("deleteSavedTitle").textContent = unreadable
      ? "읽을 수 없는 저장본을 삭제할까요?"
      : "이 브라우저의 저장본을 삭제할까요?";
    document.getElementById("deleteSavedIntro").textContent = unreadable
      ? "이 버전에서는 내용을 불러올 수 없습니다. 현재 화면에서 작성 중인 글은 그대로 두고, 저장본만 삭제합니다."
      : "현재 화면에서 작성 중인 글은 그대로 두고, 다시 불러올 저장본만 삭제합니다.";
    document.getElementById("deleteSavedDialog").showModal();
    syncActionDialogs();
  }

  function closeDeleteDialog() {
    var dialog = document.getElementById("deleteSavedDialog");
    if (dialog.open) dialog.close();
    state.deleteReview = null;
  }

  async function confirmDeleteSaved() {
    var review = state.deleteReview;
    if (!review || review.storageRevision !== state.storage.revision ||
        review.storageStatus !== state.storage.status || review.opaqueToken !== state.storage.opaqueToken) {
      syncActionDialogs();
      return;
    }
    closeDeleteDialog();
    state.storage.busy = "deleting";
    state.storage.lastError = null;
    syncStorageUI();
    try {
      var metadata = await draftStore.remove(review.storageRevision, review.opaqueToken);
      state.storage.busy = null;
      setStorageMetadata(metadata, { writableRevision: metadata.revision });
      showToast("임시 저장본만 삭제했습니다. 현재 화면의 글은 그대로입니다.");
    } catch (error) {
      state.storage.busy = null;
      var message = storageFailureMessage(error, "삭제");
      await refreshStorageMetadata({ error: message, lockWritable: Boolean(error && error.code === "conflict") });
      showToast(message);
    }
  }

  function openNewInquiryDialog() {
    state.newInquiryReview = { workspaceRevision: state.workspaceRevision };
    document.getElementById("newInquiryDialog").showModal();
    syncActionDialogs();
  }

  function closeNewInquiryDialog() {
    var dialog = document.getElementById("newInquiryDialog");
    if (dialog.open) dialog.close();
    state.newInquiryReview = null;
  }

  function resetCurrentInquiry() {
    var review = state.newInquiryReview;
    if (!review || review.workspaceRevision !== state.workspaceRevision) {
      syncActionDialogs();
      return;
    }
    closeNewInquiryDialog();
    state.currentRequestId = ++state.requestSequence;
    state.mode = "conversation";
    state.panelTab = "evidence";
    state.activeDraft = "monitor";
    state.step = "4";
    state.conditions = { tenure: "", symptom: "", purchase: "" };
    state.drafts = { monitor: undefined, it: undefined };
    state.draftTouched = { monitor: false, it: false };
    state.draftInputRevision = { monitor: null, it: null };
    state.sourceRevision = { monitor: null, it: null };
    state.sourceProposalSignature = { monitor: null, it: null };
    state.proposals = { monitor: null, it: null };
    state.proposalInputRevision = { monitor: null, it: null };
    resetEvidenceView();
    state.response = null;
    state.excludeLaptopEvidence = false;
    state.inputRevision += 1;
    state.branchInputRevision.it += 1;
    state.lastSettledDemoState = null;
    state.restoredDraft = { monitor: false, it: false };
    state.workspaceRevision += 1;
    state.demoState = "loading";
    resetLeaveProtectionForNewInquiry();
    if (["empty", "expired"].includes(state.storage.status)) {
      state.storage.writableRevision = state.storage.revision;
      state.storage.lastError = null;
    }
    render();
    showToast("현재 화면을 초기화했습니다. 임시 저장본은 그대로 두었습니다.");
    refreshWorkspace();
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
      if (state.panelTab === "evidence") {
        resetEvidenceView();
        renderEvidence();
      }
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
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-open-answer-evidence]");
    if (!button) return;
    openAnswerEvidence(button.dataset.openAnswerEvidence, button);
  });
  document.querySelector("[data-show-all-evidence]").addEventListener("click", showAllEvidence);
  document.querySelector("[data-return-to-answer]").addEventListener("click", returnToAnswer);
  all("[data-field]").forEach(function (field) {
    field.addEventListener("input", function () {
      var key = field.dataset.field;
      if (state.conditions[key] === field.value) return;
      state.conditions[key] = field.value;
      state.inputRevision += 1;
      state.branchInputRevision.it += 1;
      markWorkspaceChanged();
      syncConditions();
      syncDrafts();
      syncInputChangedNotice();
    });
  });
  all("[data-fill-conditions]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.conditions = { tenure: "4년", symptom: "지난주부터 화상회의 중", purchase: "not-purchased" };
      state.inputRevision += 1;
      state.branchInputRevision.it += 1;
      markWorkspaceChanged();
      syncConditions();
      refreshWorkspace({ message: "예시 정보로 새 제안을 만들었습니다. 작성 중인 글은 아직 바꾸지 않았습니다." });
    });
  });
  all("[data-clear-conditions]").forEach(function (button) {
    button.addEventListener("click", function () {
      state.conditions = { tenure: "", symptom: "", purchase: "" };
      state.inputRevision += 1;
      state.branchInputRevision.it += 1;
      markWorkspaceChanged();
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
      markWorkspaceChanged();
      syncDrafts(area);
    });
  });
  all("[data-reset-draft]").forEach(function (button) {
    button.addEventListener("click", function () { openProposalReview(button.dataset.resetDraft); });
  });
  document.querySelector("[data-proposal-review-cancel]").addEventListener("click", closeProposalReview);
  document.querySelector("[data-proposal-review-confirm]").addEventListener("click", confirmProposalReview);
  document.getElementById("proposalReviewDialog").addEventListener("cancel", function (event) {
    event.preventDefault();
    closeProposalReview();
  });
  all("[data-copy-draft]").forEach(function (button) {
    button.addEventListener("click", function () { copyDraft(button.dataset.copyDraft); });
  });
  document.querySelector("[data-copy-review-cancel]").addEventListener("click", closeCopyReview);
  document.querySelector("[data-copy-review-confirm]").addEventListener("click", confirmCopyReview);
  document.getElementById("copyReviewDialog").addEventListener("cancel", function (event) {
    event.preventDefault();
    closeCopyReview();
  });
  all("[data-retry]").forEach(function (button) {
    button.addEventListener("click", function () { refreshWorkspace({ excludeLaptop: false, message: "검색 자료를 되돌려 다시 확인했습니다." }); });
  });
  all("[data-new-inquiry]").forEach(function (button) {
    button.addEventListener("click", openNewInquiryDialog);
  });

  all("[data-save-draft]").forEach(function (button) { button.addEventListener("click", saveCurrentDraft); });
  all("[data-restore-draft]").forEach(function (button) { button.addEventListener("click", openRestoreDialog); });
  all("[data-delete-saved]").forEach(function (button) { button.addEventListener("click", openDeleteDialog); });
  document.querySelector("[data-restore-cancel]").addEventListener("click", closeRestoreDialog);
  document.querySelector("[data-restore-confirm]").addEventListener("click", confirmRestoreDraft);
  document.getElementById("restoreDraftDialog").addEventListener("cancel", function (event) {
    event.preventDefault();
    closeRestoreDialog();
  });
  document.querySelector("[data-delete-cancel]").addEventListener("click", closeDeleteDialog);
  document.querySelector("[data-delete-confirm]").addEventListener("click", confirmDeleteSaved);
  document.getElementById("deleteSavedDialog").addEventListener("cancel", function (event) {
    event.preventDefault();
    closeDeleteDialog();
  });
  document.querySelector("[data-new-inquiry-cancel]").addEventListener("click", closeNewInquiryDialog);
  document.querySelector("[data-new-inquiry-confirm]").addEventListener("click", resetCurrentInquiry);
  document.getElementById("newInquiryDialog").addEventListener("cancel", function (event) {
    event.preventDefault();
    closeNewInquiryDialog();
  });

  render();
  refreshStorageMetadata();
  refreshWorkspace();
})();
