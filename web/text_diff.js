(function (root, factory) {
  "use strict";

  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.EmployeeAssistantTextDiff = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var LIMITS = Object.freeze({
    maxTotalCodeUnits: 8000,
    maxTokensPerSide: 500,
    maxMatrixCells: 60000
  });

  function tokenize(text) {
    return text.match(/\s*\S+|\s+/g) || [];
  }

  function mergeSegments(operations) {
    return operations.reduce(function (segments, operation) {
      var previous = segments[segments.length - 1];
      if (previous && previous.kind === operation.kind) {
        previous.text += operation.text;
      } else {
        segments.push({ kind: operation.kind, text: operation.text });
      }
      return segments;
    }, []);
  }

  function fallback(currentText, proposedText, reason) {
    return {
      status: "fallback",
      reason: reason,
      current: [{ kind: "plain", text: currentText }],
      proposed: [{ kind: "plain", text: proposedText }]
    };
  }

  function compare(currentText, proposedText) {
    if (typeof currentText !== "string" || typeof proposedText !== "string") {
      throw new TypeError("comparison inputs must be strings");
    }
    if (currentText === proposedText) {
      return {
        status: "identical",
        reason: null,
        current: [{ kind: "equal", text: currentText }],
        proposed: [{ kind: "equal", text: proposedText }]
      };
    }
    if (currentText.length + proposedText.length > LIMITS.maxTotalCodeUnits) {
      return fallback(currentText, proposedText, "text-length");
    }

    var currentTokens = tokenize(currentText);
    var proposedTokens = tokenize(proposedText);
    var matrixCells = (currentTokens.length + 1) * (proposedTokens.length + 1);
    if (currentTokens.length > LIMITS.maxTokensPerSide ||
        proposedTokens.length > LIMITS.maxTokensPerSide ||
        matrixCells > LIMITS.maxMatrixCells) {
      return fallback(currentText, proposedText, "comparison-size");
    }

    var matrix = Array.from({ length: currentTokens.length + 1 }, function () {
      return new Uint16Array(proposedTokens.length + 1);
    });
    for (var currentIndex = currentTokens.length - 1; currentIndex >= 0; currentIndex -= 1) {
      for (var proposedIndex = proposedTokens.length - 1; proposedIndex >= 0; proposedIndex -= 1) {
        matrix[currentIndex][proposedIndex] =
          currentTokens[currentIndex] === proposedTokens[proposedIndex]
            ? matrix[currentIndex + 1][proposedIndex + 1] + 1
            : Math.max(matrix[currentIndex + 1][proposedIndex], matrix[currentIndex][proposedIndex + 1]);
      }
    }

    var operations = [];
    var currentCursor = 0;
    var proposedCursor = 0;
    while (currentCursor < currentTokens.length || proposedCursor < proposedTokens.length) {
      if (currentCursor < currentTokens.length && proposedCursor < proposedTokens.length &&
          currentTokens[currentCursor] === proposedTokens[proposedCursor]) {
        operations.push({ kind: "equal", text: currentTokens[currentCursor] });
        currentCursor += 1;
        proposedCursor += 1;
      } else if (currentCursor < currentTokens.length &&
          (proposedCursor === proposedTokens.length ||
           matrix[currentCursor + 1][proposedCursor] >= matrix[currentCursor][proposedCursor + 1])) {
        operations.push({ kind: "removed", text: currentTokens[currentCursor] });
        currentCursor += 1;
      } else {
        operations.push({ kind: "added", text: proposedTokens[proposedCursor] });
        proposedCursor += 1;
      }
    }

    var currentSegments = mergeSegments(operations.filter(function (operation) {
      return operation.kind !== "added";
    }));
    var proposedSegments = mergeSegments(operations.filter(function (operation) {
      return operation.kind !== "removed";
    }));
    if (currentSegments.map(function (segment) { return segment.text; }).join("") !== currentText ||
        proposedSegments.map(function (segment) { return segment.text; }).join("") !== proposedText) {
      return fallback(currentText, proposedText, "reconstruction");
    }
    return {
      status: "changed",
      reason: null,
      current: currentSegments,
      proposed: proposedSegments
    };
  }

  return Object.freeze({ compare: compare, limits: LIMITS });
});
