'use client';

import React, { useState, useRef, useEffect } from 'react';
import {
  Menu,
  X,
  Plus,
  Send,
  FileUp,
  Trash2,
  Edit2,
  LogOut,
  Eye,
  EyeOff,
  Loader,
  AlertCircle,
  CheckCircle,
  Clock,
  Heart,
} from 'lucide-react';

interface User {
  id: string;
  email: string;
  name: string;
}

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

interface RetrievedChunk {
  source: string;
  text: string;
  similarity_score: number;
}

interface MemoryEntry {
  id: string;
  category: string;
  fact: string;
  created_at: string;
  updated_at?: string;
  source: string;
}

interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  // assistant-only enrichment
  retrieved_chunks?: RetrievedChunk[];
  new_memory_entries?: MemoryEntry[];
  chunks_retrieved?: number;
}

interface Document {
  id: string;
  filename: string;
  uploaded_at: string;
  chunk_count: number;
  char_count: number;
  summary: {
    core_content: string;
    doctor_concerned: string;
    date_time: string;
    document_type: string;
  };
  faiss_indices: number[];
}

interface HealthMemory {
  id: string;
  category: string;
  fact: string;
  created_at: string;
  updated_at?: string;
  source: string;
}

const API_BASE = process.env.NEXT_PUBLIC_SERVER_URL || 'http://localhost:8000';

export default function MedicalRAGApp() {
  // Auth state
  const [authState, setAuthState] = useState<'login' | 'register' | 'otp' | 'app'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [otp, setOtp] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [authError, setAuthError] = useState('');
  const [loading, setLoading] = useState(false);
  const [viewingDocument, setViewingDocument] = useState<Document | null>(null);

  // App state
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activePage, setActivePage] = useState<'chat' | 'documents' | 'memory' | 'settings'>('chat');
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  // Chat state
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentInput, setCurrentInput] = useState('');
  const [sendingMessage, setSendingMessage] = useState(false);
  const [selectedDocuments, setSelectedDocuments] = useState<string[]>([]);

  // Documents state
  const [documents, setDocuments] = useState<Document[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  // Health Memory state
  const [memories, setMemories] = useState<HealthMemory[]>([]);
  const [editingMemory, setEditingMemory] = useState<HealthMemory | null>(null);
  const [newMemory, setNewMemory] = useState({
    category: 'GENERAL',
    fact: '',
  });
  const [showMemoryForm, setShowMemoryForm] = useState(false);

  // Modals
  const [confirmModal, setConfirmModal] = useState<{
    title: string;
    message: string;
    onConfirm: () => void;
  } | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Add this useEffect near the top, after all useState declarations
useEffect(() => {
  const restoreSession = async () => {
    const token = localStorage.getItem('token');
    if (!token) return;

    try {
      const res = await fetch(`${API_BASE}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.ok) {
        const data = await res.json();
        setUser({ id: data.user_id, email: data.email, name: data.email });
        setAuthState('app');
        await loadInitialData();
      } else {
        // Token invalid or expired — clear it
        localStorage.removeItem('token');
      }
    } catch {
      localStorage.removeItem('token');
    }
  };

  restoreSession();
}, []); // eslint-disable-line react-hooks/exhaustive-deps

  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auth functions
const handleLogin = async (e: React.FormEvent) => {
  e.preventDefault();
  setLoading(true);
  setAuthError('');
  try {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Login failed');
    }
    const data = await res.json();
    localStorage.setItem('token', data.access_token);
    setUser({ id: data.user_id, email: data.email, name: data.email });
    setAuthState('app');
    await loadInitialData();
  } catch (err) {
    setAuthError(err instanceof Error ? err.message : 'Login failed');
  } finally {
    setLoading(false);
  }
};

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setAuthError('');
    try {
      const res = await fetch(`${API_BASE}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password}),
      });
      console.log(email,password)
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Registration failed');
      }
      await res.json();
      setOtp('');
      setAuthState('otp');
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

 const handleVerifyOtp = async (e: React.FormEvent) => {
  e.preventDefault();
  setLoading(true);
  setAuthError('');
  try {
    // Step 1: verify OTP
    const verifyRes = await fetch(`${API_BASE}/api/auth/verify-otp`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, otp }),
    });
    if (!verifyRes.ok) {
      const err = await verifyRes.json();
      throw new Error(err.detail || 'OTP verification failed');
    }

    // Step 2: log in to get the JWT
    const loginRes = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!loginRes.ok) {
      const err = await loginRes.json();
      throw new Error(err.detail || 'Login after verification failed');
    }
    const data = await loginRes.json();

    localStorage.setItem('token', data.access_token);
    setUser({ id: data.user_id, email: data.email, name: data.email });
    setAuthState('app');
    await loadInitialData();
  } catch (err) {
    setAuthError(err instanceof Error ? err.message : 'Verification failed');
  } finally {
    setLoading(false);
  }
};

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    setUser(null);
    setAuthState('login');
    setEmail('');
    setPassword('');
    setOtp('');
    setSessions([]);
    setMessages([]);
    setDocuments([]);
    setMemories([]);
  };

  // Chat functions
  const loadInitialData = async () => {
    try {
      const token = localStorage.getItem('token');
      const [sessionsRes, docsRes, memoriesRes] = await Promise.all([
        fetch(`${API_BASE}/api/chat/sessions`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_BASE}/api/documents`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
        fetch(`${API_BASE}/api/health/memory/list`, {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ]);

      if (sessionsRes.ok) {
        const data = await sessionsRes.json();
        setSessions(data.sessions || []);
        if (data.sessions && data.sessions.length > 0) {
          setActiveSessionId(data.sessions[0].id);
          await loadMessages(data.sessions[0].id);
        }
      }

      if (docsRes.ok) {
        const data = await docsRes.json();
        setDocuments(data.documents || []);
      }

      if (memoriesRes.ok) {
        const data = await memoriesRes.json();
        setMemories(data.entries || []);
      }
    } catch (err) {
      console.error('Failed to load initial data:', err);
    }
  };

const createSession = async () => {
  try {
    const token = localStorage.getItem('token');
    const res = await fetch(`${API_BASE}/api/chat/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ title: 'New Chat' }),
    });

    if (res.ok) {
      const session = await res.json(); // backend returns the session directly, not {session: ...}
      setSessions(prev => [...prev, session]);
      setActiveSessionId(session.id);
      setMessages([]);
      setSelectedDocuments([]);
      showSuccess('Chat session created');
    }
  } catch (err) {
    showError('Failed to create session');
  }
};

const deleteSession = async (sessionId: string) => {
  try {
    const token = localStorage.getItem('token');
    const res = await fetch(`${API_BASE}/api/chat/sessions/${sessionId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    });

    if (res.ok) {
      setSessions(prev => prev.filter(s => s.id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
      }
      showSuccess('Chat deleted');
    }
  } catch (err) {
    showError('Failed to delete chat');
  }
};

const loadMessages = async (sessionId: string) => {
  try {
    const token = localStorage.getItem('token');
    const res = await fetch(`${API_BASE}/api/chat/sessions/${sessionId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (res.ok) {
      const data = await res.json();
      const mapped: ChatMessage[] = (data.history || []).map((entry: any) => {
        const meta = entry.metadata || {};
        return {
          id: entry.id,
          session_id: entry.session_id,
          role: entry.role,
          content: entry.content,
          created_at: entry.timestamp,
          // assistant messages carry enrichment in metadata
          retrieved_chunks: meta.retrieved_chunks || [],
          new_memory_entries: meta.new_memory_entries || [],
          chunks_retrieved: meta.chunks_retrieved ?? 0,
        };
      });
      setMessages(mapped);
    }
  } catch (err) {
    console.error('Failed to load messages:', err);
  }
};

const sendMessage = async (e: React.FormEvent) => {
  e.preventDefault();
  if (!currentInput.trim() || !activeSessionId) return;

  const userMessageText = currentInput;
  setCurrentInput('');

  const tempUserMsg: ChatMessage = {
    id: `temp-user-${Date.now()}`,
    session_id: activeSessionId,
    role: 'user',
    content: userMessageText,
    created_at: new Date().toISOString(),
  };
  setMessages(prev => [...prev, tempUserMsg]);
  scrollToBottom();

  setSendingMessage(true);
  try {
    const token = localStorage.getItem('token');
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        session_id: activeSessionId,
        query: userMessageText,
      }),
    });

    if (res.ok) {
      const data = await res.json();
      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        session_id: activeSessionId,
        role: 'assistant',
        content: data.answer,
        created_at: data.timestamp,
        retrieved_chunks: data.retrieved_chunks || [],
        new_memory_entries: data.new_memory_entries || [],
        chunks_retrieved: data.chunks_retrieved || 0,
      };
      setMessages(prev => [...prev, assistantMsg]);
      scrollToBottom();

      const currentSession = sessions.find(s => s.id === activeSessionId);
      if (currentSession?.title === 'New Chat') {
        const newTitle = userMessageText.length > 30
          ? userMessageText.slice(0, 30).trimEnd() + '…'
          : userMessageText;
        renameSession(activeSessionId, newTitle);
      }
    } else {
      setMessages(prev => prev.filter(m => m.id !== tempUserMsg.id));
      showError('Failed to send message');
    }
  } catch (err) {
    setMessages(prev => prev.filter(m => m.id !== tempUserMsg.id));
    showError('Failed to send message');
  } finally {
    setSendingMessage(false);
  }
};

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Document functions
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    setUploading(true);
    setUploadProgress(0);

    try {
      const token = localStorage.getItem('token');
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const formData = new FormData();
        formData.append('file', file);

        const res = await fetch(`${API_BASE}/api/documents/upload`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
        });

        if (res.ok) {
          const data = await res.json();
          const newDoc: Document = {
            id: data.document_id,
            filename: data.filename,
            chunk_count: data.chunk_count,
            summary: data.summary,
            uploaded_at: new Date().toISOString(),
          };
          setDocuments(prev => [...prev, newDoc]);
          setUploadProgress(((i + 1) / files.length) * 100);
        }
      }
      showSuccess('Documents uploaded successfully');
      if (fileInputRef.current) fileInputRef.current.value = '';
    } catch (err) {
      showError('Failed to upload documents');
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const deleteDocument = async (docId: string) => {
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_BASE}/api/documents/${docId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });

      if (res.ok) {
        setDocuments(documents.filter((d) => d.id !== docId));
        showSuccess('Document deleted');
      }
    } catch (err) {
      showError('Failed to delete document');
    }
  };

  // Health Memory functions
  const createMemory = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_BASE}/api/memory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(newMemory),
      });
      if (res.ok) {
        const data = await res.json();
        setMemories(prev => [...prev, data.entry]);
        setNewMemory({ category: 'GENERAL', fact: '' });
        setShowMemoryForm(false);
        showSuccess('Memory entry added');
      }
    } catch { showError('Failed to create memory'); }
  };

  const renameSession = async (sessionId: string, title: string) => {
  try {
    const token = localStorage.getItem('token');
    await fetch(`${API_BASE}/api/chat/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ title }),
    });
    setSessions(prev =>
      prev.map(s => s.id === sessionId ? { ...s, title } : s)
    );
  } catch {
    // non-critical, silently ignore
  }
};

  const updateMemory = async (e: React.FormEvent) => {
  e.preventDefault();
  if (!editingMemory) return;
  try {
    const token = localStorage.getItem('token');
    const res = await fetch(`${API_BASE}/api/memory/${editingMemory.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ category: editingMemory.category, fact: editingMemory.fact }),
    });
    if (res.ok) {
      const data = await res.json();
      setMemories(prev => prev.map(m => m.id === editingMemory.id ? data.entry : m));
      setEditingMemory(null);
      showSuccess('Memory updated');
    }
  } catch { showError('Failed to update memory'); }
  };

  const deleteMemory = async (memoryId: string) => {
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${API_BASE}/api/memory/${memoryId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setMemories(prev => prev.filter(m => m.id !== memoryId));
        showSuccess('Memory deleted');
      }
    } catch { showError('Failed to delete memory'); }
  };

  // Utility functions
  const showSuccess = (message: string) => {
    setSuccessMessage(message);
    setTimeout(() => setSuccessMessage(null), 3000);
  };

  const showError = (message: string) => {
    setAuthError(message);
    setTimeout(() => setAuthError(''), 3000);
  };

  // Render auth screens
  if (authState === 'login') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-blue-950 to-slate-900 flex items-center justify-center p-4">
        <div className="w-full max-w-md">
          <div className="bg-slate-900/50 backdrop-blur-xl border border-blue-500/20 rounded-2xl p-8 shadow-2xl">
            <h1 className="text-3xl font-bold text-white mb-2">MedicalAI</h1>
            <p className="text-slate-400 mb-8">Your intelligent medical assistant</p>

            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50"
                  placeholder="your@email.com"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Password</label>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50"
                    placeholder="••••••••"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              {authError && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 flex gap-2">
                  <AlertCircle size={18} className="text-red-500 flex-shrink-0" />
                  <span className="text-sm text-red-300">{authError}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white font-medium py-2 rounded-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? <Loader size={18} className="animate-spin" /> : null}
                Sign In
              </button>
            </form>

            <p className="text-center text-slate-400 mt-6">
              Don&apos;t have an account?{' '}
              <button
                onClick={() => {
                  setAuthState('register');
                  setAuthError('');
                }}
                className="text-blue-400 hover:text-blue-300"
              >
                Sign up
              </button>
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (authState === 'register') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-blue-950 to-slate-900 flex items-center justify-center p-4">
        <div className="w-full max-w-md">
          <div className="bg-slate-900/50 backdrop-blur-xl border border-blue-500/20 rounded-2xl p-8 shadow-2xl">
            <h1 className="text-3xl font-bold text-white mb-2">Create Account</h1>
            <p className="text-slate-400 mb-8">Join MedicalAI today</p>

            <form onSubmit={handleRegister} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Full Name</label>
                <input
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50"
                  placeholder="John Doe"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50"
                  placeholder="your@email.com"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Password</label>
                <div className="relative">
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50"
                    placeholder="••••••••"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                  >
                    {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              {authError && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 flex gap-2">
                  <AlertCircle size={18} className="text-red-500 flex-shrink-0" />
                  <span className="text-sm text-red-300">{authError}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white font-medium py-2 rounded-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? <Loader size={18} className="animate-spin" /> : null}
                Create Account
              </button>
            </form>

            <p className="text-center text-slate-400 mt-6">
              Already have an account?{' '}
              <button
                onClick={() => {
                  setAuthState('login');
                  setAuthError('');
                }}
                className="text-blue-400 hover:text-blue-300"
              >
                Sign in
              </button>
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (authState === 'otp') {
    return (
      <div className="min-h-screen bg-gradient-to-br from-slate-950 via-blue-950 to-slate-900 flex items-center justify-center p-4">
        <div className="w-full max-w-md">
          <div className="bg-slate-900/50 backdrop-blur-xl border border-blue-500/20 rounded-2xl p-8 shadow-2xl">
            <h1 className="text-3xl font-bold text-white mb-2">Verify Email</h1>
            <p className="text-slate-400 mb-8">Enter the code sent to {email}</p>

            <form onSubmit={handleVerifyOtp} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">OTP Code</label>
                <input
                  type="text"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 text-center text-lg tracking-widest"
                  placeholder="000000"
                  maxLength={6}
                  required
                />
              </div>

              {authError && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 flex gap-2">
                  <AlertCircle size={18} className="text-red-500 flex-shrink-0" />
                  <span className="text-sm text-red-300">{authError}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white font-medium py-2 rounded-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              >
                {loading ? <Loader size={18} className="animate-spin" /> : null}
                Verify
              </button>
            </form>
          </div>
        </div>
      </div>
    );
  }

  // Main app
  return (
    <div className="h-screen bg-gradient-to-br from-slate-950 via-blue-950 to-slate-900 flex overflow-hidden">
      {/* Sidebar */}
      <div
        className={`${
          sidebarOpen ? 'w-64' : 'w-0'
        } bg-slate-900/40 border-r border-blue-500/10 transition-all duration-300 flex flex-col overflow-hidden`}
      >
        {/* Fixed header */}
        <div className="p-4 border-b border-blue-500/10 flex-shrink-0">
          <h2 className="text-lg font-bold text-white">MedicalAI</h2>
        </div>

        {/* Fixed new chat button */}
        <div className="px-4 pt-4 flex-shrink-0">
          <button
            onClick={createSession}
            className="w-full bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white font-medium py-2 px-4 rounded-lg flex items-center justify-center gap-2 transition-all"
          >
            <Plus size={18} />
            New Chat
          </button>
        </div>

        {/* Scrollable sessions list */}
        <div className="flex-1 px-4 py-4 overflow-y-auto min-h-0">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
            Recent Chats
          </div>
          <div className="space-y-2">
            {sessions.map((session) => (
              <div key={session.id} className="relative group">
                <button
                  onClick={() => {
                    setActiveSessionId(session.id);
                    loadMessages(session.id);
                    setActivePage('chat');
                  }}
                  className={`w-full text-left px-3 py-2 rounded-lg transition-all text-sm pr-8 ${
                    activeSessionId === session.id
                      ? 'bg-blue-500/20 text-white border border-blue-500/30'
                      : 'text-slate-400 hover:text-slate-300 hover:bg-slate-800/20'
                  }`}
                >
                  <div className="truncate">{session.title}</div>
                  <div className="text-xs text-slate-500 mt-1">
                    {new Date(session.updated_at).toLocaleDateString()}
                  </div>
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirmModal({
                      title: 'Delete Chat',
                      message: `Delete "${session.title}"? This cannot be undone.`,
                      onConfirm: () => {
                        deleteSession(session.id);
                        setConfirmModal(null);
                      },
                    });
                  }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Fixed bottom nav */}
        <div className="border-t border-blue-500/10 p-4 space-y-2 flex-shrink-0">
          <button
            onClick={() => setActivePage('documents')}
            className={`w-full text-left px-3 py-2 rounded-lg transition-all text-sm font-medium flex items-center gap-2 ${
              activePage === 'documents'
                ? 'bg-blue-500/20 text-white border border-blue-500/30'
                : 'text-slate-400 hover:text-slate-300 hover:bg-slate-800/20'
            }`}
          >
            <FileUp size={18} />
            Documents
          </button>
          <button
            onClick={() => setActivePage('memory')}
            className={`w-full text-left px-3 py-2 rounded-lg transition-all text-sm font-medium flex items-center gap-2 ${
              activePage === 'memory'
                ? 'bg-blue-500/20 text-white border border-blue-500/30'
                : 'text-slate-400 hover:text-slate-300 hover:bg-slate-800/20'
            }`}
          >
            <Heart size={18} />
            Health Memory
          </button>
          <button
            onClick={handleLogout}
            className="w-full text-left px-3 py-2 rounded-lg transition-all text-sm font-medium flex items-center gap-2 text-slate-400 hover:text-slate-300 hover:bg-slate-800/20"
          >
            <LogOut size={18} />
            Logout
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {/* Header */}
        <div className="bg-slate-900/20 border-b border-blue-500/10 px-6 py-4 flex items-center justify-between">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="text-slate-400 hover:text-slate-300 transition-colors"
          >
            {sidebarOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
          <h1 className="text-xl font-bold text-white">
            {activePage === 'chat'
              ? 'Medical Chat'
              : activePage === 'documents'
                ? 'Documents'
                : activePage === 'memory'
                  ? 'Health Memory'
                  : 'Settings'}
          </h1>
          <div className="text-slate-400 text-sm">{user?.name}</div>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto">
          {successMessage && (
            <div className="m-4 bg-green-500/10 border border-green-500/30 rounded-lg p-4 flex items-center gap-3">
              <CheckCircle size={20} className="text-green-500 flex-shrink-0" />
              <span className="text-sm text-green-300">{successMessage}</span>
            </div>
          )}

          {activePage === 'chat' && (
            <div className="h-full flex flex-col p-6">
              {activeSessionId && messages.length > 0 ? (
                <div className="space-y-4 mb-4">
                  {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    {msg.role === 'user' ? (
                      <div className="max-w-xl px-4 py-3 rounded-2xl bg-blue-600/30 text-blue-100 border border-blue-500/30">
                        <p className="text-sm">{msg.content}</p>
                      </div>
                    ) : (
                      <div className="max-w-2xl w-full space-y-3">
                        {/* Answer block */}
                        <div className="px-4 py-4 rounded-2xl bg-slate-800/60 border border-slate-700/40">
                          <div className="flex items-center gap-2 mb-2">
                            <div className="w-2 h-2 rounded-full bg-cyan-400" />
                            <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">Answer</span>
                          </div>
                          <p className="text-sm text-slate-200 leading-relaxed">{msg.content}</p>
                        </div>

                        {/* Sources block */}
                        {msg.retrieved_chunks && msg.retrieved_chunks.length > 0 && (
                          <div className="px-4 py-3 rounded-2xl bg-slate-900/60 border border-violet-500/20">
                            <div className="flex items-center gap-2 mb-3">
                              <div className="w-2 h-2 rounded-full bg-violet-400" />
                              <span className="text-xs font-semibold text-violet-400 uppercase tracking-wider">
                                Sources · {msg.chunks_retrieved} chunk{msg.chunks_retrieved !== 1 ? 's' : ''} retrieved
                              </span>
                            </div>
                            <div className="space-y-2">
                              {msg.retrieved_chunks.map((chunk, i) => (
                                <div key={i} className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/30">
                                  <div className="flex items-center justify-between mb-1">
                                    <span className="text-xs font-medium text-violet-300 truncate max-w-xs">
                                      📄 {chunk.source}
                                    </span>
                                    <span
                                      className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                                        chunk.similarity_score >= 0.8
                                          ? 'bg-green-500/20 text-green-300'
                                          : chunk.similarity_score >= 0.5
                                            ? 'bg-yellow-500/20 text-yellow-300'
                                            : 'bg-red-500/20 text-red-300'
                                      }`}
                                    >
                                      {(chunk.similarity_score * 100).toFixed(1)}% match
                                    </span>
                                  </div>
                                  <p className="text-xs text-slate-400 leading-relaxed line-clamp-3">{chunk.text}</p>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* New memory entries block */}
                        {msg.new_memory_entries && msg.new_memory_entries.length > 0 && (
                          <div className="px-4 py-3 rounded-2xl bg-slate-900/60 border border-emerald-500/20">
                            <div className="flex items-center gap-2 mb-3">
                              <div className="w-2 h-2 rounded-full bg-emerald-400" />
                              <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">
                                Memory Extracted · {msg.new_memory_entries.length} new entr{msg.new_memory_entries.length !== 1 ? 'ies' : 'y'}
                              </span>
                            </div>
                            <div className="space-y-2">
                              {msg.new_memory_entries.map((entry) => (
                                <div key={entry.id} className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/30 flex items-start gap-3">
                                  <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 flex-shrink-0 mt-0.5">
                                    {entry.category.replace(/_/g, ' ')}
                                  </span>
                                  <p className="text-xs text-slate-300 leading-relaxed">{entry.fact}</p>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        <div className="text-xs text-slate-600 px-1">
                          {new Date(msg.created_at).toLocaleTimeString()}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
                  <div ref={messagesEndRef} />
                </div>
              ) : (
                <div className="flex items-center justify-center h-full text-center">
                  <div>
                    <div className="text-slate-500 text-lg mb-2">Start a conversation</div>
                    <p className="text-slate-600 text-sm max-w-md">
                      Ask any medical questions and I&apos;ll provide information based on your uploaded documents.
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}

          {activePage === 'documents' && (
            <div className="p-6">
              <div className="mb-6">
                <label className="block">
                  <div className="border-2 border-dashed border-blue-500/30 hover:border-blue-500/50 rounded-lg p-8 text-center cursor-pointer transition-all">
                    <FileUp size={32} className="mx-auto text-blue-400 mb-2" />
                    <p className="text-slate-300 font-medium">Upload Documents</p>
                    <p className="text-slate-500 text-sm">Click to select PDF files</p>
                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      accept=".pdf"
                      onChange={handleFileUpload}
                      className="hidden"
                      disabled={uploading}
                    />
                  </div>
                </label>
              </div>

              {uploading && uploadProgress > 0 && (
                <div className="mb-4">
                  <div className="bg-slate-800/50 rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm text-slate-300">Uploading...</span>
                      <span className="text-sm text-blue-400">{Math.round(uploadProgress)}%</span>
                    </div>
                    <div className="w-full bg-slate-700/50 rounded-full h-2">
                      <div
                        className="bg-gradient-to-r from-blue-600 to-cyan-600 h-2 rounded-full transition-all"
                        style={{ width: `${uploadProgress}%` }}
                      />
                    </div>
                  </div>
                </div>
              )}

              <div className="space-y-2">
                {documents.map((doc) => (
                  <div
                    key={doc.id}
                    onClick={() => setViewingDocument(doc)}
                    className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-4 flex items-center justify-between hover:bg-slate-800/50 transition-all cursor-pointer"
                  >
                    <div className="flex items-center gap-3 flex-1">
                      <FileUp size={20} className="text-blue-400 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white truncate">{doc.filename}</p>
                        <p className="text-xs text-slate-500">
                          {doc.chunk_count} chunks • {doc.summary?.document_type || 'Document'} •{' '}
                          {new Date(doc.uploaded_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setConfirmModal({
                          title: 'Delete Document',
                          message: `Are you sure you want to delete "${doc.filename}"?`,
                          onConfirm: () => {
                            deleteDocument(doc.id);
                            setConfirmModal(null);
                          },
                        });
                      }}
                      className="text-slate-500 hover:text-red-400 transition-colors ml-4 flex-shrink-0"
                    >
                      <Trash2 size={18} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

        {activePage === 'memory' && (
          <div className="p-6">
            {!showMemoryForm && !editingMemory && (
              <button
                onClick={() => setShowMemoryForm(true)}
                className="mb-6 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white font-medium py-2 px-4 rounded-lg flex items-center gap-2 transition-all"
              >
                <Plus size={18} />
                Add Memory Entry
              </button>
            )}

            {showMemoryForm && (
              <div className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-6 mb-6">
                <h3 className="text-lg font-bold text-white mb-4">Add Memory Entry</h3>
                <form onSubmit={createMemory} className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">Category</label>
                    <select
                      value={newMemory.category}
                      onChange={(e) => setNewMemory({ ...newMemory, category: e.target.value })}
                      className="w-full bg-slate-900/50 border border-slate-600 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-blue-500/50"
                    >
                      {['PRESCRIPTION','DIAGNOSIS','ALLERGY','SURGERY','LAB_RESULT',
                        'MEDICAL_COURSE_COMPLETED','VACCINATION','VITAL_STATS','FOLLOW_UP','GENERAL'
                      ].map(cat => (
                        <option key={cat} value={cat}>{cat.replace(/_/g, ' ')}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">Fact</label>
                    <textarea
                      value={newMemory.fact}
                      onChange={(e) => setNewMemory({ ...newMemory, fact: e.target.value })}
                      className="w-full bg-slate-900/50 border border-slate-600 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 resize-none"
                      placeholder="Describe the medical fact..."
                      rows={3}
                      required
                    />
                  </div>
                  <div className="flex gap-3">
                    <button type="submit"
                      className="flex-1 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white font-medium py-2 rounded-lg transition-all">
                      Create
                    </button>
                    <button type="button"
                      onClick={() => { setShowMemoryForm(false); setNewMemory({ category: 'GENERAL', fact: '' }); }}
                      className="flex-1 bg-slate-800/50 hover:bg-slate-700/50 text-white font-medium py-2 rounded-lg transition-all border border-slate-600">
                      Cancel
                    </button>
                  </div>
                </form>
              </div>
            )}

            <div className="space-y-3">
              {memories.map((memory) => (
                <div key={memory.id} className="bg-slate-800/30 border border-slate-700/30 rounded-lg p-4 hover:bg-slate-800/50 transition-all">
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex-1 min-w-0">
                      <span className="text-xs font-semibold px-2 py-1 rounded bg-blue-500/20 text-blue-300">
                        {memory.category.replace('_', ' ')}
                      </span>
                      <p className="text-sm text-slate-200 mt-2">{memory.fact}</p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between mt-3">
                    <span className="text-xs text-slate-500">
                      {new Date(memory.created_at).toLocaleDateString()}
                    </span>
                    <div className="flex gap-3">
                      <button onClick={() => setEditingMemory(memory)}
                        className="text-slate-500 hover:text-blue-400 transition-colors text-sm flex items-center gap-1">
                        <Edit2 size={14} /> Edit
                      </button>
                      <button
                        onClick={() => setConfirmModal({
                          title: 'Delete Memory',
                          message: `Delete this memory entry?`,
                          onConfirm: () => { deleteMemory(memory.id); setConfirmModal(null); },
                        })}
                        className="text-slate-500 hover:text-red-400 transition-colors text-sm flex items-center gap-1">
                        <Trash2 size={14} /> Delete
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        </div>

        {/* Message Input */}
        {activePage === 'chat' && activeSessionId && (
          <form
            onSubmit={sendMessage}
            className="border-t border-blue-500/10 bg-slate-900/20 p-6 flex gap-3"
          >
            <div className="flex-1">
              <input
                type="text"
                value={currentInput}
                onChange={(e) => setCurrentInput(e.target.value)}
                placeholder="Ask a medical question..."
                className="w-full bg-slate-800/50 border border-slate-700 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50"
                disabled={sendingMessage}
              />
            </div>
            <button
              type="submit"
              disabled={sendingMessage || !currentInput.trim()}
              className="bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white font-medium py-3 px-4 rounded-lg transition-all flex items-center justify-center disabled:opacity-50"
            >
              {sendingMessage ? <Loader size={20} className="animate-spin" /> : <Send size={20} />}
            </button>
          </form>
        )}
      </div>

      {/* Confirmation Modal */}
      {confirmModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-blue-500/30 rounded-2xl p-6 max-w-sm">
            <h2 className="text-xl font-bold text-white mb-2">{confirmModal.title}</h2>
            <p className="text-slate-400 mb-6">{confirmModal.message}</p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmModal(null)}
                className="flex-1 bg-slate-800/50 hover:bg-slate-700/50 text-white font-medium py-2 rounded-lg transition-all border border-slate-600"
              >
                Cancel
              </button>
              <button
                onClick={confirmModal.onConfirm}
                className="flex-1 bg-red-600 hover:bg-red-700 text-white font-medium py-2 rounded-lg transition-all"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
      {editingMemory && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-blue-500/20 rounded-2xl p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold text-white">Edit Memory Entry</h2>
              <button
                onClick={() => setEditingMemory(null)}
                className="text-slate-400 hover:text-white transition-colors"
              >
                <X size={20} />
              </button>
            </div>
            <form onSubmit={updateMemory} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Category</label>
                <select
                  value={editingMemory.category}
                  onChange={(e) => setEditingMemory({ ...editingMemory, category: e.target.value })}
                  className="w-full bg-slate-800/50 border border-slate-600 rounded-lg px-4 py-2 text-white focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50"
                >
                  {['PRESCRIPTION','DIAGNOSIS','ALLERGY','SURGERY','LAB_RESULT',
                    'MEDICAL_COURSE_COMPLETED','VACCINATION','VITAL_STATS','FOLLOW_UP','GENERAL'
                  ].map(cat => (
                    <option key={cat} value={cat}>{cat.replace(/_/g, ' ')}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Fact</label>
                <textarea
                  value={editingMemory.fact}
                  onChange={(e) => setEditingMemory({ ...editingMemory, fact: e.target.value })}
                  className="w-full bg-slate-800/50 border border-slate-600 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 resize-none"
                  rows={4}
                  required
                />
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => setEditingMemory(null)}
                  className="flex-1 bg-slate-800/50 hover:bg-slate-700/50 text-white font-medium py-2 rounded-lg transition-all border border-slate-600"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white font-medium py-2 rounded-lg transition-all"
                >
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {viewingDocument && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-slate-900 border border-blue-500/20 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden">
            
            {/* Header */}
            <div className="flex items-start justify-between p-6 border-b border-slate-700/50">
              <div className="flex items-center gap-3 flex-1 min-w-0">
                <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center flex-shrink-0">
                  <FileUp size={20} className="text-blue-400" />
                </div>
                <div className="min-w-0">
                  <h2 className="text-lg font-bold text-white truncate">{viewingDocument.filename}</h2>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Uploaded {new Date(viewingDocument.uploaded_at).toLocaleString()}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setViewingDocument(null)}
                className="text-slate-400 hover:text-white transition-colors ml-4 flex-shrink-0"
              >
                <X size={20} />
              </button>
            </div>

            {/* Stats row */}
            <div className="grid grid-cols-3 divide-x divide-slate-700/50 border-b border-slate-700/50">
              <div className="p-4 text-center">
                <p className="text-2xl font-bold text-blue-400">{viewingDocument.chunk_count}</p>
                <p className="text-xs text-slate-500 mt-1">Chunks</p>
              </div>
              <div className="p-4 text-center">
                <p className="text-2xl font-bold text-violet-400">
                  {viewingDocument.char_count >= 1000
                    ? `${(viewingDocument.char_count / 1000).toFixed(1)}k`
                    : viewingDocument.char_count}
                </p>
                <p className="text-xs text-slate-500 mt-1">Characters</p>
              </div>
              <div className="p-4 text-center">
                <p className="text-2xl font-bold text-emerald-400">{viewingDocument.faiss_indices?.length ?? 0}</p>
                <p className="text-xs text-slate-500 mt-1">Vectors</p>
              </div>
            </div>

            {/* Summary */}
            <div className="p-6 space-y-4 overflow-y-auto max-h-96">

              <div className="flex items-center gap-2 mb-1">
                <div className="w-2 h-2 rounded-full bg-cyan-400" />
                <span className="text-xs font-semibold text-cyan-400 uppercase tracking-wider">Document Type</span>
              </div>
              <div className="bg-slate-800/50 rounded-lg px-4 py-2 border border-slate-700/30">
                <p className="text-sm text-slate-200">{viewingDocument.summary.document_type || '—'}</p>
              </div>

              <div className="flex items-center gap-2 mb-1">
                <div className="w-2 h-2 rounded-full bg-violet-400" />
                <span className="text-xs font-semibold text-violet-400 uppercase tracking-wider">Doctor / Concerned Party</span>
              </div>
              <div className="bg-slate-800/50 rounded-lg px-4 py-2 border border-slate-700/30">
                <p className="text-sm text-slate-200">{viewingDocument.summary.doctor_concerned || '—'}</p>
              </div>

              <div className="flex items-center gap-2 mb-1">
                <div className="w-2 h-2 rounded-full bg-yellow-400" />
                <span className="text-xs font-semibold text-yellow-400 uppercase tracking-wider">Date / Time</span>
              </div>
              <div className="bg-slate-800/50 rounded-lg px-4 py-2 border border-slate-700/30">
                <p className="text-sm text-slate-200">{viewingDocument.summary.date_time || '—'}</p>
              </div>

              <div className="flex items-center gap-2 mb-1">
                <div className="w-2 h-2 rounded-full bg-emerald-400" />
                <span className="text-xs font-semibold text-emerald-400 uppercase tracking-wider">Core Content</span>
              </div>
              <div className="bg-slate-800/50 rounded-lg px-4 py-3 border border-slate-700/30">
                <p className="text-sm text-slate-200 leading-relaxed">
                  {viewingDocument.summary.core_content || '—'}
                </p>
              </div>
            </div>

            {/* Footer */}
            <div className="p-4 border-t border-slate-700/50">
              <button
                onClick={() => setViewingDocument(null)}
                className="w-full bg-slate-800/50 hover:bg-slate-700/50 text-white font-medium py-2 rounded-lg transition-all border border-slate-600 text-sm"
              >
                Close
              </button>
            </div>
          </div>
        </div>
)}
    </div>
  );
}
