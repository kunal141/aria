import React, { useState } from 'react';
import ARIAMasterPlan from './ARIAMasterPlan';
import ARIADashboard from './ARIADashboard';
import ARIAVoice from './ARIAVoice';
import ROIDashboard from './ROIDashboard';

export default function App() {
  const [view, setView] = useState('dashboard');

  return (
    <div className="min-h-screen bg-gray-50">
      {view === 'dashboard' && <ARIADashboard />}
      {view === 'plan'      && <ARIAMasterPlan />}
      {view === 'voice'     && <ARIAVoice />}
      {view === 'roi'       && <ROIDashboard />}

      {/* View switcher — bottom right */}
      <div className="fixed bottom-5 right-5 flex gap-2 z-50 shadow-lg">
        <button
          onClick={() => setView('dashboard')}
          title="Operational Dashboard"
          className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium border transition-all ${
            view === 'dashboard'
              ? 'bg-violet-600 border-violet-600 text-white shadow-md'
              : 'bg-white border-gray-300 text-gray-600 hover:border-violet-400 hover:text-violet-600'
          }`}
        >
          ⚡ Dashboard
        </button>
        <button
          onClick={() => setView('roi')}
          title="ROI Dashboard — Week 29 Priority 2"
          className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium border transition-all ${
            view === 'roi'
              ? 'bg-violet-600 border-violet-600 text-white shadow-md'
              : 'bg-white border-gray-300 text-gray-600 hover:border-violet-400 hover:text-violet-600'
          }`}
        >
          📊 ROI
        </button>
        <button
          onClick={() => setView('plan')}
          title="30-Week Master Plan"
          className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium border transition-all ${
            view === 'plan'
              ? 'bg-violet-600 border-violet-600 text-white shadow-md'
              : 'bg-white border-gray-300 text-gray-600 hover:border-violet-400 hover:text-violet-600'
          }`}
        >
          🗺 Master Plan
        </button>
        <button
          onClick={() => setView('voice')}
          title="Voice Interface"
          className={`flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium border transition-all ${
            view === 'voice'
              ? 'bg-violet-600 border-violet-600 text-white shadow-md'
              : 'bg-white border-gray-300 text-gray-600 hover:border-violet-400 hover:text-violet-600'
          }`}
        >
          Voice
        </button>
      </div>
    </div>
  );
}
