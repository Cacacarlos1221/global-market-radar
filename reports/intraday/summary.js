"use strict";

// This file reads only a separately reviewed public summary in GitHub Pages.
fetch("approved-summary.json", { cache: "no-cache" })
  .then(response => response.ok ? response.json() : null)
  .then(summary => {
    if (!summary || typeof summary !== "object") return;
    for (const field of ["market", "metrics", "candidates", "evaluation", "updated", "status"]) {
      const text = summary[field];
      if (typeof text === "string" && text.trim()) {
        document.getElementById(field).textContent = text.trim();
      }
    }
  })
  .catch(() => {});
