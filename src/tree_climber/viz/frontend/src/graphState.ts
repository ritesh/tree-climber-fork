import { createContext, useContext } from 'react';
import type { DirectedGraph } from 'graphology';
import type { Attributes } from 'graphology-types';

// Type definitions for our graph data
export interface CFGNode {
  id: number;
  node_type: string;
  start_index: number | null;
  end_index: number | null;
  source_text: string;
  successors: number[];
  predecessors: number[];
  edge_labels: { [key: number]: string };
  metadata: {
    function_calls: string[];
    variable_definitions: string[];
    variable_uses: string[];
  };
}

export interface GraphData {
  cfg: CFGData;
  dfg: DFGData;
}

export interface CFGData {
  function_name: string | null;
  entry_node_ids: number[];
  exit_node_ids: number[];
  nodes: { [key: number]: CFGNode };
}

export interface DFGEdge {
  source: number;
  target: number;
  label: string;
}

export interface DFGData {
  edges: DFGEdge[];
}

export interface PathStep {
  node: number;
  node_type: string;
  text: string;
  edge: string | null;
  variable: string | null;
}

export interface Finding {
  rule: string;
  source: number;
  sink: number;
  sink_call: string;
  argument: number;
  path: { steps: PathStep[] };
}

// Node attributes for Graphology
export interface NodeAttributes extends Attributes {
  node_type: string;
  start_index: number | null;
  end_index: number | null;
  source_text: string;
  metadata: {
    function_calls: string[];
    variable_definitions: string[];
    variable_uses: string[];
  };
}

// Edge attributes for Graphology
export interface EdgeAttributes extends Attributes {
  label: string;
}

// Context state type
export interface GraphContextState {
  graphologyGraph: DirectedGraph<NodeAttributes, EdgeAttributes> | null;
  cfgData: CFGData | null;
  currentLanguage: string;
  setGraphData: (cfgData: CFGData, language: string) => void;
  getNodeById: (nodeId: number) => CFGNode | null;
  getNodesInRange: (startIndex: number, endIndex: number) => CFGNode[];
  // Utility functions for graph operations
  getNodeNeighbors: (nodeId: string) => string[];
  getNodeAttribute: <K extends keyof NodeAttributes>(nodeId: string, attribute: K) => NodeAttributes[K] | null;
  getAllNodes: () => string[];
  getAllEdges: () => Array<{ source: string; target: string; attributes: EdgeAttributes }>;
  findings: Finding[];
  setFindings: (findings: Finding[]) => void;
  highlightedPath: PathStep[] | null;
  setHighlightedPath: (path: PathStep[] | null) => void;
}

// Create the context
export const GraphContext = createContext<GraphContextState | undefined>(undefined);

// Hook to use the graph context
export const useGraph = (): GraphContextState => {
  const context = useContext(GraphContext);
  if (context === undefined) {
    throw new Error('useGraph must be used within a GraphProvider');
  }
  return context;
};

// Add a callback ref for selecting nodes in Cytoscape
let selectGraphNode: ((nodeId?: string) => void) | null = null;

function setSelectGraphNodeCallback(cb: (nodeId?: string) => void) {
  selectGraphNode = cb;
}

function selectGraphNodeById(nodeId?: string) {
  if (selectGraphNode) selectGraphNode(nodeId);
}

export { setSelectGraphNodeCallback, selectGraphNodeById };

// Allow Editor to register a callback for node selection
let onGraphNodeSelect: ((nodeId?: string) => void) | null = null;

function setOnGraphNodeSelectCallback(cb: (nodeId?: string) => void) {
  onGraphNodeSelect = cb;
}

function notifyGraphNodeSelected(nodeId?: string) {
  if (onGraphNodeSelect) onGraphNodeSelect(nodeId);
}

export { setOnGraphNodeSelectCallback, notifyGraphNodeSelected };
