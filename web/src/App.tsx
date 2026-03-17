/**
 * Main App component — Code Architect Agent v2
 *
 * 3-panel layout: FileTree | AgentActivityFeed | MemoryPanel
 * with a fixed TopBar and ChatBar.
 */

import { useUI } from './store/app';

import TopBar from './components/TopBar';
import FileTree from './components/FileTree';
import AgentActivityFeed from './components/AgentActivityFeed';
import MemoryPanel from './components/MemoryPanel';
import ChatBar from './components/ChatBar';

import './App.css';
import './components/components.css';

function App() {
  const { darkMode } = useUI();

  return (
    <div className={`app${darkMode ? ' dark-mode' : ''}`}>
      <TopBar />
      <div className="app-body">
        <FileTree />
        <AgentActivityFeed />
        <MemoryPanel />
      </div>
      <ChatBar />
    </div>
  );
}

export default App;
