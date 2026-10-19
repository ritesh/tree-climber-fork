import React, { useState } from 'react';
import type { ReactNode } from 'react';
import { DirectedGraph } from 'graphology';
import { GraphContext } from './graphState';
import type {
  CFGData,
  CFGNode,
  EdgeAttributes,
  Finding,
  GraphContextState,
  NodeAttributes,
  PathStep,
} from './graphState';

// Provider component
export const GraphProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [graphologyGraph, setGraphologyGraph] = useState<DirectedGraph<NodeAttributes, EdgeAttributes> | null>(null);
  const [cfgData, setCfgData] = useState<CFGData | null>(null);
  const [currentLanguage, setCurrentLanguage] = useState<string>('c');
  const [findings, setFindings] = useState<Finding[]>([]);
  const [highlightedPath, setHighlightedPath] = useState<PathStep[] | null>(null);

  const setGraphData = (newCfgData: CFGData, language: string) => {
    setCfgData(newCfgData);
    setCurrentLanguage(language);
    
    // Create new Graphology graph
    const graph = new DirectedGraph<NodeAttributes, EdgeAttributes>();
    
    // Add nodes to the graph
    Object.values(newCfgData.nodes).forEach(node => {
      graph.addNode(node.id.toString(), {
        node_type: node.node_type,
        start_index: node.start_index,
        end_index: node.end_index,
        source_text: node.source_text,
        metadata: node.metadata,
      });
    });
    
    // Add edges to the graph
    Object.values(newCfgData.nodes).forEach(node => {
      node.successors.forEach(successorId => {
        const edgeLabel = node.edge_labels[successorId] || '';
        graph.addEdge(node.id.toString(), successorId.toString(), {
          label: edgeLabel,
        });
      });
    });
    
    setGraphologyGraph(graph);
  };

  const getNodeById = (nodeId: number): CFGNode | null => {
    if (!cfgData) return null;
    return cfgData.nodes[nodeId] || null;
  };

  const getNodesInRange = (startIndex: number, endIndex: number): CFGNode[] => {
    if (!cfgData) return [];
    
    // TODO: This is a simplified implementation - in a real scenario, you'd need
    // to map source code positions to CFG nodes more precisely based on the
    // CFG builder's source position metadata
    
    // For now, return all nodes that have source text within the range
    // This will need to be enhanced with proper source mapping
    return Object.values(cfgData.nodes).filter(node => {
      // Placeholder implementation - would need actual source position mapping
      // Parameters startIndex and endIndex would be used for proper range checking
      const hasSourceText = node.source_text && node.source_text.length > 0;
      const isInRange = startIndex <= endIndex; // Basic range validation
      return hasSourceText && isInRange;
    });
  };

  const getNodeNeighbors = (nodeId: string): string[] => {
    if (!graphologyGraph) return [];
    try {
      return graphologyGraph.neighbors(nodeId);
    } catch {
      return [];
    }
  };

  const getNodeAttribute = <K extends keyof NodeAttributes>(nodeId: string, attribute: K): NodeAttributes[K] | null => {
    if (!graphologyGraph) return null;
    try {
      return graphologyGraph.getNodeAttribute(nodeId, attribute);
    } catch {
      return null;
    }
  };

  const getAllNodes = (): string[] => {
    if (!graphologyGraph) return [];
    return graphologyGraph.nodes();
  };

  const getAllEdges = (): Array<{ source: string; target: string; attributes: EdgeAttributes }> => {
    if (!graphologyGraph) return [];
    return graphologyGraph.mapEdges((_edge, attributes, source, target) => ({
      source,
      target,
      attributes,
    }));
  };

  const contextValue: GraphContextState = {
    graphologyGraph,
    cfgData,
    currentLanguage,
    setGraphData,
    getNodeById,
    getNodesInRange,
    getNodeNeighbors,
    getNodeAttribute,
    getAllNodes,
    getAllEdges,
    findings,
    setFindings,
    highlightedPath,
    setHighlightedPath,
  };

  return (
    <GraphContext.Provider value={contextValue}>
      {children}
    </GraphContext.Provider>
  );
};
