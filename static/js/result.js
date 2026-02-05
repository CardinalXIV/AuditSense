document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("graph-container");
  const graphPanel = document.querySelector(".graph-panel");
  const sidebarEl = document.getElementById("graph-sidebar");
  const infoEl = document.getElementById("graph-info");
  const searchInput = document.getElementById("graph-search");
  const searchBtn = document.getElementById("graph-search-btn");
  const resetBtn = document.getElementById("graph-reset-btn");
  const graphExpandBtn = document.getElementById("graph-expand-btn");
  const docFocusSelect = document.getElementById("doc-focus-select");
  const docFocusBtn = document.getElementById("doc-focus-btn");
  const layoutSpacingInput = document.getElementById("layout-spacing");
  const layoutSpacingValue = document.getElementById("layout-spacing-value");
  const layoutApplyBtn = document.getElementById("layout-apply-btn");
  const ignoreDimmedClicks = document.getElementById("ignore-dimmed-clicks");

  const evidenceMeta = document.getElementById("term-evidence-meta");
  const evidenceList = document.getElementById("term-evidence-list");

  if (!container) return;

  function escapeHtml(value) {
    if (!value && value !== 0) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function highlight(snippet, q) {
    const safe = escapeHtml(snippet || "");
    if (!q) return safe;
    const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`(${escaped})`, "ig");
    return safe.replace(re, "<mark>$1</mark>");
  }

  function setSidebarHtml(html) {
    if (!sidebarEl) return;
    sidebarEl.innerHTML = html;
  }

  function setEvidenceMeta(text) {
    if (evidenceMeta) evidenceMeta.textContent = text;
  }

  function clearEvidence() {
    setEvidenceMeta("Run a search to inspect chunk-level evidence.");
    if (evidenceList) evidenceList.innerHTML = "";
  }

  function setEvidenceLoading(q) {
    setEvidenceMeta(`Searching evidence for "${q}"...`);
    if (evidenceList) evidenceList.innerHTML = "";
  }

  function setEvidenceError(q) {
    setEvidenceMeta(`Could not load term evidence for "${q}".`);
    if (evidenceList) evidenceList.innerHTML = "";
  }

  function renderEvidence(q, matches) {
    if (!evidenceList) return;
    setEvidenceMeta(`Found ${matches.length} chunk hit(s) for "${q}".`);
    evidenceList.innerHTML = matches
      .slice(0, 12)
      .map((m) => {
        const doc = escapeHtml(m.document || m.source_file || "unknown");
        const chunk = escapeHtml(String(m.chunk || ""));
        const snippet = highlight(m.snippet || "", q);
        return (
          `<article class="evidence-item" data-doc="${doc}" data-chunk="${chunk}" data-chunkid="${escapeHtml(
            m.chunk_id || "",
          )}">` +
          '<div class="evidence-top">' +
          `<div>${doc} <span style="color:#6b7f99;">· ch ${chunk}</span></div>` +
          '<div><button type="button" class="evidence-btn evidence-focus" data-doc="' +
          doc +
          '" data-chunk="' +
          chunk +
          '">Focus</button></div>' +
          "</div>" +
          `<div class="evidence-snippet">${snippet}</div>` +
          "</article>"
        );
      })
      .join("");
  }

  function runTermEvidenceSearch(qRaw) {
    const q = (qRaw || "").trim();
    if (!q) {
      clearEvidence();
      return;
    }

    setEvidenceLoading(q);
    fetch(`/term-search?q=${encodeURIComponent(q)}`)
      .then((r) => r.json())
      .then((data) => {
        const matches = data && Array.isArray(data.matches) ? data.matches : [];
        if (!matches.length) {
          setEvidenceMeta(`No chunk evidence found for "${q}".`);
          if (evidenceList) evidenceList.innerHTML = "";
          return;
        }
        renderEvidence(q, matches);
      })
      .catch(() => setEvidenceError(q));
  }

  function truncate(value, max = 1200) {
    if (!value) return "";
    if (value.length <= max) return value;
    return `${value.slice(0, max)}...`;
  }

      function nodeSidebarHtml(node, docNames) {
    const type = node.data("type") || "Node";
    const label = node.data("label") || "(no label)";
    const context = node.data("context") || "";
    const sourceKind = node.data("source_kind") || "document";
    const docs = Array.from(new Set(docNames || []));

    let html = "";
    html += `<div style="font-weight:700;font-size:0.8rem;color:#556a83;">${escapeHtml(type)} node</div>`;
    html += `<div style="font-weight:700;font-size:0.98rem;margin-top:6px;word-break:break-word;">${escapeHtml(
      label,
    )}</div>`;

    if (type === "Document") {
      html += `<div style="margin-top:6px;font-size:0.75rem;color:#4f6178;">Source kind: ${escapeHtml(
        String(sourceKind).split("_").join(" "),
      )}</div>`;
    }

    if (type === "Chunk" && context) {
      html += '<div style="margin-top:10px;font-weight:600;">Context</div>';
      html += `<div style="margin-top:6px;background:#f7fbff;border:1px solid #e0e8f4;border-radius:8px;padding:8px;white-space:pre-wrap;font-size:0.75rem;line-height:1.35;">${escapeHtml(
        truncate(context),
      )}</div>`;
    }

    if (docs.length) {
      html += '<div style="margin-top:10px;font-weight:600;">Linked documents</div>';
      html += "<ul style='margin:6px 0 0 16px;padding:0;'>";
      docs.forEach((name) => {
        html += `<li style="margin-bottom:2px;">${escapeHtml(name)}</li>`;
      });
      html += "</ul>";
    }

        return html;
      }

      function documentFocusSidebarHtml(docNode, chunks, dateNodes, entityNodes) {
        const docLabel = docNode.data("label") || "Document";
        const topDates = Array.from(new Set(dateNodes.map((n) => n.data("label")))).slice(0, 8);
        const topEntities = Array.from(new Set(entityNodes.map((n) => n.data("label")))).slice(0, 8);

        let html = "";
        html += '<div style="font-size:0.82rem;font-weight:700;color:#4f6178;">Document focus</div>';
        html += `<div style="margin-top:5px;font-weight:700;font-size:0.95rem;word-break:break-word;">${escapeHtml(
          docLabel,
        )}</div>`;
        html += `<div style="margin-top:8px;color:#51657f;font-size:0.78rem;">Chunks: ${chunks.length} · Dates: ${dateNodes.length} · Entities: ${entityNodes.length}</div>`;

        if (topDates.length) {
          html += '<div style="margin-top:10px;font-weight:600;">Primary dates</div>';
          html += "<ul style='margin:6px 0 0 16px;padding:0;'>";
          topDates.forEach((name) => {
            html += `<li style="margin-bottom:2px;">${escapeHtml(name)}</li>`;
          });
          html += "</ul>";
        }

        if (topEntities.length) {
          html += '<div style="margin-top:10px;font-weight:600;">Primary entities</div>';
          html += "<ul style='margin:6px 0 0 16px;padding:0;'>";
          topEntities.forEach((name) => {
            html += `<li style="margin-bottom:2px;">${escapeHtml(name)}</li>`;
          });
          html += "</ul>";
        }

        return html;
      }

  fetch("/graph-data")
    .then((r) => r.json())
    .then((data) => {
      if (!data || data.disabled) {
        if (infoEl) infoEl.textContent = "Graph is disabled in the current configuration.";
        return;
      }

      if (!Array.isArray(data.nodes) || !Array.isArray(data.edges) || !data.nodes.length) {
        if (infoEl) infoEl.textContent = "No graph data available yet.";
        return;
      }

      if (typeof cytoscape === "undefined") {
        if (infoEl) infoEl.textContent = "Graph library failed to load.";
        return;
      }

      const elements = [];
      data.nodes.forEach((node) => {
        elements.push({
          data: {
            id: node.id,
            label: node.label || node.type,
            type: node.type || "Node",
            context: node.context || "",
            source_kind: node.source_kind || "document",
          },
        });
      });

      data.edges.forEach((edge) => {
        elements.push({
          data: {
            id: `${edge.source}-${edge.type}-${edge.target}`,
            source: edge.source,
            target: edge.target,
            type: edge.type || "",
          },
        });
      });

      function getLayoutScale() {
        const parsed = parseFloat(layoutSpacingInput ? layoutSpacingInput.value : "1.8");
        return Number.isFinite(parsed) ? parsed : 1.8;
      }

      function updateLayoutScaleLabel() {
        if (!layoutSpacingValue) return;
        layoutSpacingValue.textContent = `${getLayoutScale().toFixed(1)}x`;
      }

      function makeLayout(scale = getLayoutScale()) {
        return {
          name: "cose",
          animate: false,
          idealEdgeLength: 140 * scale,
          nodeRepulsion: 110000 * scale,
          componentSpacing: 120 * scale,
          padding: 60 * scale,
          spacingFactor: scale,
          randomize: true,
        };
      }

      const cy = cytoscape({
        container,
        elements,
        layout: makeLayout(),
        style: [
          {
            selector: "node",
            style: {
              label: "data(label)",
              color: "#10314c",
              "font-size": "9px",
              "min-zoomed-font-size": "8px",
              "text-valign": "center",
              "text-halign": "center",
              "text-wrap": "wrap",
              "text-max-width": "140px",
              "text-background-color": "rgba(255,255,255,0.95)",
              "text-background-opacity": 1,
              "text-background-padding": "3px",
              "text-border-color": "rgba(16,49,76,0.25)",
              "text-border-width": 0.5,
              width: "20px",
              height: "20px",
              "background-color": "#7b8ea8",
              opacity: 1,
            },
          },
          {
            selector: 'node[type = "Document"]',
            style: {
              shape: "round-rectangle",
              width: "220px",
              height: "label",
              "min-width": "140px",
              "min-height": "34px",
              "background-color": "#2a8f83",
              color: "#f3fffc",
              "text-wrap": "wrap",
              "text-max-width": "200px",
              "text-background-opacity": 0,
              "font-size": "8px",
            },
          },
          {
            selector: 'node[type = "Document"][source_kind = "bot_output"]',
            style: {
              "background-color": "#0369a1",
            },
          },
          {
            selector: 'node[type = "Chunk"]',
            style: {
              shape: "ellipse",
              "background-color": "#4f7da8",
            },
          },
          {
            selector: 'node[type = "Date"]',
            style: {
              shape: "diamond",
              "background-color": "#d97706",
              color: "#10243f",
            },
          },
          {
            selector: 'node[type = "Entity"]',
            style: {
              shape: "hexagon",
              "background-color": "#0e7490",
              color: "#10243f",
            },
          },
          {
            selector: "edge",
            style: {
              width: 1.1,
              "curve-style": "bezier",
              "line-color": "#8da0b8",
              "target-arrow-color": "#8da0b8",
              "target-arrow-shape": "triangle",
              opacity: 0.8,
            },
          },
          {
            selector: 'edge[type = "MENTIONS_DATE"]',
            style: {
              "line-color": "#d97706",
              "target-arrow-color": "#d97706",
              "line-style": "dashed",
              width: 1.4,
            },
          },
          {
            selector: 'edge[type = "MENTIONS"]',
            style: {
              "line-color": "#0f766e",
              "target-arrow-color": "#0f766e",
              width: 1.4,
            },
          },
          { selector: ".selected", style: { "border-width": 3, "border-color": "#f59e0b" } },
          { selector: ".highlighted", style: { opacity: 1 } },
        ],
      });

      cy.ready(() => cy.fit(cy.elements(":visible"), 50));

      let currentFocusNodes = cy.collection();

      function setDimmedInteractivity(focusCollection) {
        const disableDimmed = !ignoreDimmedClicks || ignoreDimmedClicks.checked;
        if (!disableDimmed) {
          cy.nodes().style("events", "yes");
          cy.edges().style("events", "yes");
          return;
        }

        cy.nodes().style("events", "no");
        cy.edges().style("events", "no");
        focusCollection.nodes().style("events", "yes");
        focusCollection.edges().style("events", "yes");
      }

      function resetFocus() {
        cy.elements().removeClass("selected");
        cy.elements().removeClass("highlighted");
        cy.nodes().style("opacity", 1);
        cy.edges().style("opacity", 0.8);
        cy.nodes().style("events", "yes");
        cy.edges().style("events", "yes");
        currentFocusNodes = cy.collection();

        if (infoEl) infoEl.textContent = "Type a term and press Enter to highlight related nodes.";
        setSidebarHtml('<p class="muted-copy">Select a graph node to inspect context and linked documents.</p>');
      }

      function applyFocus(focusNodes) {
        if (focusNodes.empty()) {
          resetFocus();
          return cy.collection();
        }

        currentFocusNodes = focusNodes;
        let focus = cy.collection();
        focusNodes.forEach((n) => {
          focus = focus.union(n.closedNeighborhood());
        });

        cy.nodes().style("opacity", 0.45);
        cy.edges().style("opacity", 0.25);
        focus.nodes().style("opacity", 1);
        focus.edges().style("opacity", 0.95);
        setDimmedInteractivity(focus);

        cy.elements().removeClass("selected");
        cy.elements().removeClass("highlighted");
        focusNodes.addClass("selected");
        focus.nodes().addClass("highlighted");
        focus.edges().addClass("highlighted");
        return focus;
      }

      function extendFocus(addNodes) {
        if (addNodes.empty()) return cy.collection();
        return applyFocus(currentFocusNodes.union(addNodes));
      }

      function applyTypeFilters() {
        const docsEl = document.getElementById("filter-docs");
        const chunksEl = document.getElementById("filter-chunks");
        const datesEl = document.getElementById("filter-dates");
        const entitiesEl = document.getElementById("filter-entities");
        if (!docsEl || !chunksEl || !datesEl || !entitiesEl) return;

        const byType = {
          Document: docsEl.checked,
          Chunk: chunksEl.checked,
          Date: datesEl.checked,
          Entity: entitiesEl.checked,
        };

        Object.entries(byType).forEach(([type, visible]) => {
          cy.nodes(`[type = "${type}"]`).style("display", visible ? "element" : "none");
        });

        cy.edges().forEach((edge) => {
          const srcVisible = edge.source().style("display") !== "none";
          const tgtVisible = edge.target().style("display") !== "none";
          edge.style("display", srcVisible && tgtVisible ? "element" : "none");
        });
      }

      function showNodeContext(node, extend) {
        const focus = extend ? extendFocus(cy.collection(node)) : applyFocus(cy.collection(node));
        const docs = node.closedNeighborhood().nodes('[type = "Document"]');
        const docLabels = Array.from(new Set(docs.map((d) => d.data("label"))));

        if (infoEl) {
          if (["Date", "Entity"].includes(node.data("type"))) {
            infoEl.textContent = `${node.data("type")} "${node.data("label")}" is linked to: ${
              docLabels.length ? docLabels.join(", ") : "none"
            }`;
          } else {
            infoEl.textContent = `Selected ${node.data("type")}: "${node.data("label")}"`;
          }
        }

        setSidebarHtml(nodeSidebarHtml(node, docLabels));
        if (!focus.empty()) cy.fit(focus, 60);
      }

      function populateDocumentFocusOptions() {
        if (!docFocusSelect) return;
        const docs = cy
          .nodes('[type = "Document"]')
          .map((n) => n.data("label") || "")
          .filter((label) => Boolean(label))
          .sort((a, b) => a.localeCompare(b));

        docFocusSelect.innerHTML = '<option value="">Select a document...</option>';
        docs.forEach((label) => {
          const option = document.createElement("option");
          option.value = label;
          option.textContent = label;
          docFocusSelect.appendChild(option);
        });
      }

      function focusDocumentConnections(selectedLabel) {
        const labelLower = String(selectedLabel || "").toLowerCase();
        if (!labelLower) return;

        const docMatches = cy.nodes('[type = "Document"]').filter((n) => {
          const label = (n.data("label") || "").toLowerCase();
          return label === labelLower;
        });

        if (!docMatches.length) {
          if (infoEl) infoEl.textContent = `No document node found for "${selectedLabel}".`;
          return;
        }

        const docNode = docMatches[0];
        const chunkNodes = docNode.neighborhood('node[type = "Chunk"]');
        let primary = cy.collection(docNode).union(chunkNodes);
        chunkNodes.forEach((chunkNode) => {
          const neighbors = chunkNode.neighborhood('node[type = "Date"], node[type = "Entity"]');
          primary = primary.union(neighbors);
        });

        const dateNodes = primary.nodes('[type = "Date"]');
        const entityNodes = primary.nodes('[type = "Entity"]');
        const focus = applyFocus(primary);
        if (!focus.empty()) cy.fit(focus, 60);

        if (infoEl) {
          infoEl.textContent = `Focused "${selectedLabel}": ${chunkNodes.length} chunk(s), ${dateNodes.length} date link(s), ${entityNodes.length} entity link(s).`;
        }
        setSidebarHtml(documentFocusSidebarHtml(docNode, chunkNodes, dateNodes, entityNodes));
      }

      function focusChunkNode(docName, chunkNum) {
        const queryChunk = `ch ${chunkNum}`;
        const matches = cy.nodes().filter((n) => {
          const label = (n.data("label") || "").toLowerCase();
          return label.includes(String(docName).toLowerCase()) && label.includes(queryChunk);
        });
        if (matches.length > 0) showNodeContext(matches[0], false);
      }

      function runSearch() {
        if (!searchInput) return;
        const qRaw = searchInput.value.trim();
        const q = qRaw.toLowerCase();

        if (!q) {
          resetFocus();
          cy.layout(makeLayout()).run();
          cy.fit(cy.elements(":visible"), 50);
          clearEvidence();
          return;
        }

        runTermEvidenceSearch(qRaw);
        const parts = q.split(/\s+/).filter(Boolean);

        const matches = cy.nodes().filter((n) => {
          const label = (n.data("label") || "").toLowerCase();
          const context = (n.data("context") || "").toLowerCase();
          const haystack = `${label} ${context}`;
          if (!haystack.trim()) return false;
          if (parts.length === 1) return haystack.includes(parts[0]);
          return parts.some((p) => haystack.includes(p));
        });

        if (!matches.length) {
          resetFocus();
          if (infoEl) infoEl.textContent = `No nodes match "${qRaw}".`;
          return;
        }

        const focus = applyFocus(matches);
        let docs = cy.collection();
        matches.forEach((node) => {
          docs = docs.union(node.closedNeighborhood().nodes('[type = "Document"]'));
        });

        const docLabels = Array.from(new Set(docs.map((d) => d.data("label"))));
        if (infoEl) {
          infoEl.textContent = `Found ${matches.length} node(s) for "${qRaw}". Linked documents: ${
            docLabels.length ? docLabels.join(", ") : "none"
          }`;
        }
        setSidebarHtml(nodeSidebarHtml(matches[0], docLabels));
        if (!focus.empty()) cy.fit(focus, 60);
      }

      cy.on("tap", "node", (evt) => {
        const shift = evt.originalEvent && evt.originalEvent.shiftKey;
        showNodeContext(evt.target, shift);
      });

      ["filter-docs", "filter-chunks", "filter-dates", "filter-entities"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("change", applyTypeFilters);
      });

      if (searchBtn) searchBtn.addEventListener("click", runSearch);
      if (searchInput) {
        searchInput.addEventListener("keydown", (evt) => {
          if (evt.key === "Enter") runSearch();
        });
      }

      if (docFocusBtn) {
        docFocusBtn.addEventListener("click", () => {
          if (!docFocusSelect) return;
          focusDocumentConnections(docFocusSelect.value);
        });
      }

      if (docFocusSelect) {
        docFocusSelect.addEventListener("change", () => {
          const selected = docFocusSelect.value;
          if (!selected) return;
          focusDocumentConnections(selected);
        });
      }

      function toggleGraphExpanded() {
        if (!graphPanel || !graphExpandBtn) return;
        graphPanel.classList.toggle("is-expanded");
        const expanded = graphPanel.classList.contains("is-expanded");
        graphExpandBtn.textContent = expanded ? "Collapse graph" : "Expand graph";

        setTimeout(() => {
          cy.resize();
          if (!currentFocusNodes.empty()) {
            const focus = applyFocus(currentFocusNodes);
            if (!focus.empty()) cy.fit(focus, 80);
          } else {
            cy.fit(cy.elements(":visible"), 80);
          }
        }, 50);
      }

      if (layoutSpacingInput) {
        layoutSpacingInput.addEventListener("input", updateLayoutScaleLabel);
      }

      if (layoutApplyBtn) {
        layoutApplyBtn.addEventListener("click", () => {
          cy.layout(makeLayout()).run();
          cy.fit(cy.elements(":visible"), 80);
        });
      }

      if (ignoreDimmedClicks) {
        ignoreDimmedClicks.addEventListener("change", () => {
          if (currentFocusNodes.empty()) {
            resetFocus();
            return;
          }
          applyFocus(currentFocusNodes);
        });
      }

      if (graphExpandBtn) {
        graphExpandBtn.addEventListener("click", toggleGraphExpanded);
      }

      if (resetBtn) {
        resetBtn.addEventListener("click", () => {
          if (searchInput) searchInput.value = "";
          if (docFocusSelect) docFocusSelect.value = "";
          resetFocus();
          cy.layout(makeLayout()).run();
          cy.fit(cy.elements(":visible"), 50);
          clearEvidence();
        });
      }

      document.addEventListener("click", (evt) => {
        const kwBtn = evt.target.closest(".kw-chip");
        if (kwBtn && searchInput) {
          searchInput.value = kwBtn.getAttribute("data-kw") || "";
          runSearch();
          return;
        }

        const focusBtn = evt.target.closest(".evidence-focus");
        if (focusBtn) {
          const doc = focusBtn.getAttribute("data-doc") || "";
          const chunk = parseInt(focusBtn.getAttribute("data-chunk") || "0", 10);
          if (doc && chunk) focusChunkNode(doc, chunk);
          evt.preventDefault();
          return;
        }

        const item = evt.target.closest(".evidence-item");
        if (!item || !sidebarEl) return;

        const doc = item.getAttribute("data-doc") || "";
        const chunk = item.getAttribute("data-chunk") || "";
        const snippetEl = item.querySelector(".evidence-snippet");

        sidebarEl.innerHTML =
          '<div style="font-size:0.82rem;font-weight:700;color:#4f6178;">Evidence</div>' +
          `<div style="margin-top:5px;color:#63758d;font-size:0.76rem;">Document: ${escapeHtml(
            doc,
          )} · chunk #${escapeHtml(chunk)}</div>` +
          `<div style="margin-top:8px;white-space:pre-wrap;font-size:0.79rem;line-height:1.4;">${
            snippetEl ? snippetEl.innerHTML : ""
          }</div>`;
      });

      applyTypeFilters();
      populateDocumentFocusOptions();
      updateLayoutScaleLabel();
      resetFocus();
      clearEvidence();
    })
    .catch((error) => {
      console.error("Failed to load graph data", error);
      if (infoEl) infoEl.textContent = "Could not load graph data.";
    });
});
