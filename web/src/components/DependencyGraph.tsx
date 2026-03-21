/**
 * DependencyGraph — Cytoscape.js dependency visualization.
 *
 * Features:
 * - Internal modules as nodes; external packages as grey smaller nodes
 * - Entry-point nodes (main.py etc.) with gold border
 * - Pattern color-coding via toolbar dropdown
 * - "Show external deps" toggle
 * - Click node → open in FileEditor
 * - Hover node → tooltip with purpose
 * - Double-click → highlight neighbors, dim others
 * - Layouts: dagre (DAG) and force (cose)
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';
import cytoscape from 'cytoscape';
// @ts-ignore — cytoscape-dagre has no bundled types
import dagre from 'cytoscape-dagre';
import { useAppStore } from '../store/app';

cytoscape.use(dagre);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface GraphNode {
  id: string;
  name: string;
  purpose: string;
  patterns: string[];
  is_entry: boolean;
  type: 'internal' | 'external';
}

interface GraphEdge {
  source: string;
  target: string;
  type: 'internal' | 'external';
}

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ---------------------------------------------------------------------------
// Pattern → colour mapping (repeating palette)
// ---------------------------------------------------------------------------
const PATTERN_COLORS = [
  '#4ecdc4', '#ff6b6b', '#a29bfe', '#fdcb6e',
  '#fd79a8', '#00b894', '#e17055', '#74b9ff',
];

function patternColor(pattern: string, allPatterns: string[]): string {
  const idx = allPatterns.indexOf(pattern);
  return idx >= 0 ? PATTERN_COLORS[idx % PATTERN_COLORS.length] : '#74b9ff';
}

// ---------------------------------------------------------------------------
// DependencyGraph component
// ---------------------------------------------------------------------------
const DependencyGraph: React.FC = () => {
  const selectedProject = useAppStore((s) => s.selectedProject);
  const setOpenedFile = useAppStore((s) => s.setOpenedFile);
  const setCenterTab = useAppStore((s) => s.setCenterTab);
  const darkMode = useAppStore((s) => s.darkMode);

  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);

  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showExternal, setShowExternal] = useState(false);
  const [layout, setLayout] = useState<'dagre' | 'cose'>('dagre');
  const [filterPattern, setFilterPattern] = useState('');
  const [highlightedNode, setHighlightedNode] = useState<string | null>(null);

  // Collect all unique patterns across the graph
  const allPatterns = graphData
    ? [...new Set(graphData.nodes.flatMap((n) => n.patterns))]
    : [];

  // Fetch graph data
  const fetchGraph = useCallback(async () => {
    if (!selectedProject) return;
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`/api/projects/${encodeURIComponent(selectedProject.id)}/graph`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: GraphData = await res.json();
      setGraphData(data);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [selectedProject?.id]);

  useEffect(() => { fetchGraph(); }, [fetchGraph]);

  // (Re)build Cytoscape instance whenever data / filters change
  useEffect(() => {
    if (!graphData || !containerRef.current) return;

    if (cyRef.current) {
      cyRef.current.destroy();
      cyRef.current = null;
    }

    const visibleNodes = graphData.nodes.filter(
      (n) => n.type === 'internal' || showExternal,
    );
    const visibleIds = new Set(visibleNodes.map((n) => n.id));
    const visibleEdges = graphData.edges.filter(
      (e) => visibleIds.has(e.source) && visibleIds.has(e.target),
    );

    const nodeBg = darkMode ? '#2d2d2d' : '#ffffff';
    const nodeColor = darkMode ? '#eeeeee' : '#333333';
    const edgeColor = darkMode ? '#555555' : '#cccccc';

    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...visibleNodes.map((n) => {
          // Determine node fill based on pattern filter
          let bgColor = nodeBg;
          if (filterPattern && n.patterns.includes(filterPattern)) {
            bgColor = patternColor(filterPattern, allPatterns);
          }
          return {
            data: {
              id: n.id,
              label: n.name,
              purpose: n.purpose,
              patterns: n.patterns,
              nodeType: n.type,
              isEntry: n.is_entry,
              bgColor,
            },
          };
        }),
        ...visibleEdges.map((e, i) => ({
          data: {
            id: `e${i}`,
            source: e.source,
            target: e.target,
            edgeType: e.type,
          },
        })),
      ],
      style: [
        {
          selector: 'node',
          style: {
            'background-color': 'data(bgColor)' as any,
            'label': 'data(label)',
            'color': nodeColor,
            'font-size': '11px',
            'text-valign': 'bottom',
            'text-halign': 'center',
            'text-margin-y': 4,
            'width': 36,
            'height': 36,
            'border-width': 2,
            'border-color': edgeColor,
          },
        },
        {
          selector: 'node[nodeType = "external"]',
          style: {
            'width': 24,
            'height': 24,
            'background-color': darkMode ? '#3a3a3a' : '#e9ecef',
            'border-color': darkMode ? '#555' : '#adb5bd',
            'color': darkMode ? '#888' : '#6c757d',
            'font-size': '9px',
          },
        },
        {
          selector: 'node[?isEntry]',
          style: {
            'border-color': '#f39c12',
            'border-width': 3,
          },
        },
        {
          selector: 'node:selected',
          style: {
            'border-color': '#3498db',
            'border-width': 3,
            'background-color': '#3498db',
            'color': '#fff',
          },
        },
        {
          selector: 'node.dimmed',
          style: { 'opacity': 0.2 },
        },
        {
          selector: 'node.highlighted',
          style: {
            'border-color': '#3498db',
            'border-width': 3,
            'opacity': 1,
          },
        },
        {
          selector: 'edge',
          style: {
            'width': 1.5,
            'line-color': edgeColor,
            'target-arrow-color': edgeColor,
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'opacity': 0.6,
          },
        },
        {
          selector: 'edge[edgeType = "internal"]',
          style: {
            'line-color': darkMode ? '#4a7fa5' : '#74b9ff',
            'target-arrow-color': darkMode ? '#4a7fa5' : '#74b9ff',
            'opacity': 0.7,
          },
        },
        {
          selector: 'edge.dimmed',
          style: { 'opacity': 0.05 },
        },
      ],
      layout: {
        name: layout,
        ...(layout === 'dagre' ? {
          rankDir: 'TB',
          nodeSep: 50,
          rankSep: 80,
          padding: 20,
        } : {
          name: 'cose',
          animate: false,
          padding: 30,
          nodeRepulsion: () => 8000,
          idealEdgeLength: () => 80,
        }),
      } as any,
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
    });

    cyRef.current = cy;

    // Click → open file in editor
    cy.on('tap', 'node[nodeType = "internal"]', (evt) => {
      const nodeId: string = evt.target.data('id');
      if (selectedProject && nodeId) {
        setOpenedFile({ path: nodeId, projectId: selectedProject.id });
        setCenterTab('file');
      }
    });

    // Hover → tooltip
    cy.on('mouseover', 'node', (evt) => {
      const purpose: string = evt.target.data('purpose');
      const label: string = evt.target.data('label');
      if (!tooltipRef.current || !purpose) return;
      tooltipRef.current.textContent = `${label}: ${purpose}`;
      tooltipRef.current.style.display = 'block';
    });
    cy.on('mousemove', (evt) => {
      if (!tooltipRef.current) return;
      const pos = evt.renderedPosition ?? { x: 0, y: 0 };
      tooltipRef.current.style.left = `${pos.x + 12}px`;
      tooltipRef.current.style.top = `${pos.y + 12}px`;
    });
    cy.on('mouseout', 'node', () => {
      if (tooltipRef.current) tooltipRef.current.style.display = 'none';
    });

    // Double-click → highlight neighbors
    cy.on('dblclick', 'node', (evt) => {
      const node = evt.target;
      const nodeId: string = node.data('id');
      setHighlightedNode((prev) => (prev === nodeId ? null : nodeId));
    });

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [graphData, showExternal, layout, filterPattern, darkMode]);

  // Apply highlight / dim when highlightedNode changes
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass('highlighted dimmed');
    if (!highlightedNode) return;
    const node = cy.getElementById(highlightedNode);
    if (!node.length) return;
    const neighborhood = node.closedNeighborhood();
    cy.elements().not(neighborhood).addClass('dimmed');
    neighborhood.addClass('highlighted');
  }, [highlightedNode]);

  if (!selectedProject) {
    return (
      <div className="graph-empty">
        <div className="empty-state-icon">🕸</div>
        <div className="empty-state-text">프로젝트를 선택하세요</div>
      </div>
    );
  }

  return (
    <div className="dependency-graph">
      {/* Toolbar */}
      <div className="graph-toolbar">
        <label className="graph-toolbar-toggle">
          <input
            type="checkbox"
            checked={showExternal}
            onChange={(e) => setShowExternal(e.target.checked)}
          />
          外部依賴
        </label>
        <select
          className="graph-toolbar-select"
          value={filterPattern}
          onChange={(e) => setFilterPattern(e.target.value)}
        >
          <option value="">Pattern 著色…</option>
          {allPatterns.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
        <select
          className="graph-toolbar-select"
          value={layout}
          onChange={(e) => setLayout(e.target.value as 'dagre' | 'cose')}
        >
          <option value="dagre">Layout: DAG</option>
          <option value="cose">Layout: Force</option>
        </select>
        {highlightedNode && (
          <button className="graph-toolbar-btn" onClick={() => setHighlightedNode(null)}>
            清除高亮
          </button>
        )}
        <button className="graph-toolbar-btn" onClick={fetchGraph} disabled={loading}>
          {loading ? '載入中…' : '重新整理'}
        </button>
        <span className="graph-toolbar-hint">點擊節點開啟檔案 · 雙擊高亮相鄰節點</span>
      </div>

      {/* Canvas */}
      {loading && (
        <div className="graph-loading">
          <span className="spinner" /> 建立依賴圖…
        </div>
      )}
      {error && <div className="graph-error">⚠ {error}</div>}
      {!loading && graphData?.nodes.length === 0 && (
        <div className="graph-empty">
          <div className="empty-state-icon">🕸</div>
          <div className="empty-state-text">尚無依賴資料，請先執行分析</div>
        </div>
      )}
      <div ref={containerRef} className="graph-canvas" />

      {/* Tooltip */}
      <div ref={tooltipRef} className="graph-tooltip" style={{ display: 'none' }} />
    </div>
  );
};

export default DependencyGraph;
