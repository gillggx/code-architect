/**
 * Main App component — Code Architect Agent v2
 *
 * Home view (no project) or Workspace view (project active).
 */

import React from 'react';
import { useAppStore, useUI } from './store/app';

import TopBar from './components/TopBar';
import FileTree from './components/FileTree';
import AgentActivityFeed from './components/AgentActivityFeed';
import MemoryPanel from './components/MemoryPanel';
import ChatBar from './components/ChatBar';
import HomeView from './components/HomeView';

import './App.css';
import './components/components.css';

class ErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { error: Error | null }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: '2rem', color: '#c0392b', fontFamily: 'monospace' }}>
          <h2>App Error</h2>
          <pre style={{ whiteSpace: 'pre-wrap', fontSize: '0.85rem' }}>
            {this.state.error.message}
            {'\n'}
            {this.state.error.stack}
          </pre>
          <button onClick={() => window.location.reload()} style={{ marginTop: '1rem', padding: '0.5rem 1rem' }}>
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

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

function AppWithBoundary() {
  return (
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  );
}

export default AppWithBoundary;
