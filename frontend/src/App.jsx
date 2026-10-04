import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, Bot, User, CheckCircle, XCircle } from 'lucide-react';
import './index.css';

const API_URL = 'http://127.0.0.1:5000/api/execute';

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    const userPrompt = input.trim();
    setInput('');
    setIsLoading(true);

    // Add user message
    setMessages(prev => [...prev, { role: 'user', content: userPrompt }]);

    // Add initial system message state
    setMessages(prev => [...prev, { 
      role: 'system', 
      content: 'Thinking...', 
      status: 'loading',
      steps: []
    }]);

    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: userPrompt })
      });

      const data = await response.json();

      setMessages(prev => {
        const newMessages = [...prev];
        const lastMsg = newMessages[newMessages.length - 1];
        
        lastMsg.status = data.status === 'COMPLETED' || data.status === 'success' ? 'completed' : 'failed';
        
        if (data.message) {
            lastMsg.content = data.message;
        } else {
            lastMsg.content = data.status === 'COMPLETED' 
              ? 'Task completed successfully!' 
              : 'Task failed during execution.';
        }
        
        lastMsg.steps = data.steps || [];
        
        return newMessages;
      });

    } catch (error) {
      setMessages(prev => {
        const newMessages = [...prev];
        const lastMsg = newMessages[newMessages.length - 1];
        lastMsg.status = 'failed';
        lastMsg.content = 'Failed to connect to AURA Backend API. Is it running?';
        return newMessages;
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', backgroundColor: 'var(--bg-primary)' }}>
      
      {/* Sarvam-style Navbar */}
      <header style={{ 
        padding: '16px 32px', 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'space-between',
        backgroundColor: 'var(--bg-primary)',
        position: 'sticky',
        top: 0,
        zIndex: 10
      }}>
        <div style={{ fontSize: '1.75rem', fontWeight: 600, letterSpacing: '-0.05em' }}>
          aura
        </div>
        
        <nav style={{ display: 'flex', gap: '32px', fontSize: '0.95rem', color: 'var(--text-secondary)' }}>
          <span style={{ cursor: 'pointer' }}>Products</span>
          <span style={{ cursor: 'pointer' }}>Developers</span>
          <span style={{ cursor: 'pointer' }}>Resources</span>
          <span style={{ cursor: 'pointer' }}>Company</span>
        </nav>

        <div style={{ display: 'flex', gap: '16px' }}>
          <button style={{ 
            padding: '8px 24px', 
            borderRadius: '24px', 
            backgroundColor: '#1f2937', 
            color: 'white',
            fontWeight: 500
          }}>
            Log In
          </button>
          <button style={{ 
            padding: '8px 24px', 
            borderRadius: '24px', 
            backgroundColor: '#f3f4f6', 
            color: '#1f2937',
            fontWeight: 500
          }}>
            Contact Us
          </button>
        </div>
      </header>

      {/* Main Content Area */}
      <div style={{ flex: 1, overflowY: 'auto', paddingBottom: '120px' }}>
        
        {/* Hero Section (only shown if no messages) */}
        {messages.length === 0 && (
          <div style={{ 
            display: 'flex', 
            flexDirection: 'column', 
            alignItems: 'center', 
            justifyContent: 'center',
            marginTop: '15vh',
            textAlign: 'center'
          }}>
            <h1 className="serif-text" style={{ 
              fontSize: '3.5rem', 
              lineHeight: '1.2', 
              color: 'var(--text-primary)',
              margin: 0
            }}>
              The AI Platform<br/>Your Desktop Builds On
            </h1>
            <p style={{ 
              marginTop: '24px', 
              color: 'var(--text-secondary)', 
              fontSize: '1.1rem',
              maxWidth: '600px'
            }}>
              AURA understands natural language and automates Windows applications with precision. Start typing below to orchestrate your workflow.
            </p>
          </div>
        )}

        {/* Chat History */}
        <div style={{ maxWidth: '800px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '40px', padding: '40px 24px' }}>
          {messages.map((msg, idx) => (
            <div key={idx} className="animate-fade-in" style={{ display: 'flex', gap: '20px' }}>
              
              {/* Avatar */}
              <div style={{ 
                flexShrink: 0, 
                width: 36, 
                height: 36, 
                borderRadius: '50%', 
                background: msg.role === 'user' ? '#f3f4f6' : '#1f2937', 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'center',
                boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
              }}>
                {msg.role === 'user' ? <User size={18} color="#4b5563" /> : <Bot size={18} color="#fff" />}
              </div>

              {/* Message Content */}
              <div style={{ flex: 1, paddingTop: '6px' }}>
                <div style={{ fontWeight: 600, marginBottom: '8px', color: 'var(--text-primary)' }}>
                  {msg.role === 'user' ? 'You' : 'aura'}
                </div>
                
                <div style={{ 
                  color: 'var(--text-primary)', 
                  fontSize: '1.1rem', 
                  lineHeight: '1.6',
                  fontFamily: msg.role === 'system' ? "'Playfair Display', serif" : "inherit"
                }}>
                  {msg.content}
                </div>

                {/* Steps / Execution Output */}
                {msg.steps && msg.steps.length > 0 && (
                  <div style={{ marginTop: '20px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {msg.steps.map((step, sIdx) => (
                      <div key={sIdx} style={{ 
                        background: '#ffffff', 
                        border: '1px solid var(--border-light)', 
                        borderRadius: '8px', 
                        padding: '16px',
                        display: 'flex',
                        gap: '16px',
                        alignItems: 'flex-start',
                        boxShadow: '0 1px 3px rgba(0,0,0,0.05)'
                      }}>
                        {step.status === 'success' ? (
                          <CheckCircle size={20} color="#10b981" style={{ marginTop: '2px', flexShrink: 0 }} />
                        ) : (
                          <XCircle size={20} color="#ef4444" style={{ marginTop: '2px', flexShrink: 0 }} />
                        )}
                        <div style={{ flex: 1 }}>
                          <div style={{ fontFamily: 'monospace', fontSize: '0.9rem', color: '#6b7280' }}>
                            {step.agent} <span style={{ color: '#d1d5db' }}>-&gt;</span> {step.action}
                          </div>
                          <div style={{ fontSize: '1rem', marginTop: '6px', color: step.status === 'success' ? 'var(--text-primary)' : '#ef4444' }}>
                            {step.details}
                          </div>
                          <div style={{ fontSize: '0.8rem', color: '#9ca3af', marginTop: '6px' }}>
                            {step.duration_ms}ms
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                
                {/* Loading indicator */}
                {msg.status === 'loading' && (
                  <div style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-secondary)' }}>
                    <Loader2 size={18} className="lucide-spin" style={{ animation: 'spin 1s linear infinite' }} />
                    <span style={{ fontSize: '0.95rem' }}>Executing workflow...</span>
                  </div>
                )}

              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Floating Input Area */}
      <div style={{ 
        position: 'fixed',
        bottom: '0',
        left: '0',
        right: '0',
        padding: '32px 24px', 
        background: 'linear-gradient(to top, var(--bg-primary) 70%, transparent)',
        pointerEvents: 'none'
      }}>
        <div style={{ maxWidth: '750px', margin: '0 auto', position: 'relative', pointerEvents: 'auto' }}>
          <form onSubmit={handleSubmit} style={{ 
            display: 'flex', 
            background: '#ffffff', 
            border: '1px solid var(--border-light)', 
            borderRadius: '100px', 
            padding: '12px 24px',
            paddingRight: '64px', 
            boxShadow: '0 10px 25px -5px rgba(0,0,0,0.05), 0 8px 10px -6px rgba(0,0,0,0.01)',
            transition: 'box-shadow 0.2s ease'
          }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask AURA to automate something..."
              disabled={isLoading}
              style={{
                width: '100%',
                background: 'transparent',
                border: 'none',
                outline: 'none',
                color: 'var(--text-primary)',
                fontSize: '1.05rem',
                fontFamily: 'inherit'
              }}
            />
            <button 
              type="submit" 
              disabled={!input.trim() || isLoading}
              style={{
                position: 'absolute',
                right: '12px',
                top: '50%',
                transform: 'translateY(-50%)',
                background: input.trim() && !isLoading ? '#1f2937' : '#f3f4f6',
                color: input.trim() && !isLoading ? '#ffffff' : '#9ca3af',
                borderRadius: '50%',
                width: '40px',
                height: '40px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.2s ease'
              }}
            >
              <Send size={18} style={{ marginLeft: '2px' }} />
            </button>
          </form>
          <div style={{ textAlign: 'center', fontSize: '0.8rem', color: '#9ca3af', marginTop: '16px' }}>
            AURA can make mistakes. Check important actions.
          </div>
        </div>
      </div>

    </div>
  );
}
