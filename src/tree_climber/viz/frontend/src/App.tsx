import { useState, useRef, useCallback } from 'react'
import Editor from './Editor'
import Graph from './Graph'
import Findings from './Findings'
import { LanguageSelector } from './LanguageSelector'
import { GraphProvider } from './GraphContext'
import { loadLanguage } from './sampleCode'

// Define the interface for Graph component ref
interface GraphRef {
  updateGraph: (code: string, language: string) => Promise<void>;
}

function App() {
  const [language, setLanguage] = useState(loadLanguage());
  const graphRef = useRef<GraphRef>(null);

  // The editor calls this with the new language's code when the language changes
  const handleCodeChange = useCallback(async (code: string) => {
    // Call backend /parse and update the graph
    if (graphRef.current) {
      try {
        await graphRef.current.updateGraph(code, language);
      } catch (error) {
        console.error('Error updating graph:', error);
      }
    }
  }, [language]);

  return (
    <GraphProvider>
      <LanguageSelector language={language} onLanguageChange={setLanguage} />
      <div className="app-container">
        <Editor language={language} onTextChange={handleCodeChange} />
        <Graph ref={graphRef} />
      </div>
      <Findings />
    </GraphProvider>
  )
}

export default App
