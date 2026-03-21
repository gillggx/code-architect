/**
 * Main App component — Code Architect Agent v2
 *
 * Home view (no project) or Workspace view (project active).
 */

import { useAppStore, useUI } from './store/app';

import TopBar from './components/TopBar';
import FileTree from './components/FileTree';
import AgentActivityFeed from './components/AgentActivityFeed';
import MemoryPanel from './components/MemoryPanel';
import ChatBar from './components/ChatBar';
import HomeView from './components/HomeView';

import './App.css';
import './components/components.css';

function App() {
  const { darkMode } = useUI();
  const appView = useAppStore(s => s.appView);

  return (
    <div className={`app${darkMode ? ' dark-mode' : ''}`}>
      <TopBar />
      {appView === 'home' ? (
        <HomeView />
      ) : (
        <>
          <div className="app-body">
            <FileTree />
            <AgentActivityFeed />
            <MemoryPanel />
          </div>
          <ChatBar />
        </>
      )}
    </div>
  );
}

export default App;
