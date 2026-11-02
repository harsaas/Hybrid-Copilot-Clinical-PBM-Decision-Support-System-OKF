import React, { useEffect, useState } from 'react';
import {
  ShieldCheck, Database, GitBranch, FileText, Activity, Terminal,
  Layers, RefreshCw, Code, Info, Download, Search, BookOpen, FileCode,
} from 'lucide-react';

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function App() {
  const [data, setData] = useState(null);
  const [selectedId, setSelectedId] = useState('');
  const [inspectedId, setInspectedId] = useState('');
  const [filter, setFilter] = useState('');
  const [tab, setTab] = useState('inspection');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function load(signal) {
    setLoading(true);
    setError('');
    try {
      const response = await fetch('/api/dashboard', { signal });
      if (!response.ok) {
        const detail = await response.json();
        throw new Error(detail.error || `Local server returned ${response.status}`);
      }
      const snapshot = await response.json();
      setData(snapshot);
      setSelectedId(previous => snapshot.nodes.some(node => node.id === previous)
        ? previous
        : (snapshot.nodes.find(node => node.id === 'drug_fluconazole_oral_tablet_150_mg')
          || snapshot.nodes.find(node => node.type === 'clinical_drug'))?.id || '');
      setInspectedId('');
    } catch (failure) {
      if (failure.name !== 'AbortError') setError(`${failure.message}. Start the Python dashboard server and retry.`);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, []);

  const drugs = (data?.nodes || []).filter(node => node.type === 'clinical_drug');
  const filtered = drugs.filter(node => node.title.toLowerCase().includes(filter.toLowerCase()));
  const active = drugs.find(node => node.id === selectedId);
  const edges = active ? data.edges.filter(edge => edge.source === active.id || edge.target === active.id) : [];
  const relatedIds = new Set([selectedId, ...edges.flatMap(edge => [edge.source, edge.target])]);
  const related = (data?.nodes || []).filter(node => relatedIds.has(node.id));
  const inspected = related.find(node => node.id === inspectedId) || active;
  const snippets = active ? data.chunks.filter(chunk =>
    chunk.source === active.provenance.source && active.provenance.pages?.includes(chunk.page)) : [];
  const titleText = active?.title.replace(/\s+/g, ' ').toLowerCase();
  const exactSnippets = snippets.filter(chunk => chunk.text.replace(/\s+/g, ' ').toLowerCase().includes(titleText));
  const shownSnippets = exactSnippets.length ? exactSnippets : snippets;
  const record = active ? {
    record_type: 'local_formulary_source_inspection',
    clinical_verification: false,
    fhir_resource: false,
    node_id: active.id,
    title: active.title,
    tier: active.tier,
    detected_codes: active.raw_codes_found,
    restrictions: active.restrictions,
    raw_requirements: active.raw_requirements,
    provenance: active.provenance,
    graph_edges: edges,
    matching_mode: 'source-and-page preview; no semantic search',
    pdf_chunks_on_source_pages: snippets.length,
    full_title_chunk_matches: exactSnippets.length,
    scope: 'First 15 PDF pages only',
  } : null;

  function choose(id) {
    setSelectedId(id);
    setInspectedId(id);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><div className="brand-icon"><ShieldCheck /></div>
          <div><h1>Clinical PBM Copilot <span className="badge purple">PDF + OKF knowledge explorer</span></h1>
            <p>Source-backed formulary inspection · NetworkX · Local demo</p></div>
        </div>
        <button className="secondary" onClick={() => load()} disabled={loading}>
          <RefreshCw size={15} className={loading ? 'spin' : ''} /> {loading ? 'Reading local data...' : 'Refresh local data'}
        </button>
      </header>

      <main>
        <div className="notice"><Info size={18} /><span><strong>Research demo, not clinical advice.</strong> Actual local PDF and Markdown data.
          Only the first 15 pages are parsed. No live Pinecone search, AI answers, or independently verified safety protocols.</span></div>
        {error && <div role="alert" className="error">{error} <button onClick={() => load()}>Retry</button></div>}
        {loading && !data && <div role="status" className="panel loading"><Activity className="spin" /> Loading PDF chunks and graph files...</div>}
        {data && <>
          {data.warnings.map(warning => <div role="status" className="notice" key={warning}>{warning}</div>)}
          <div className="metrics">
            {[
              ['Parsed PDF pages', data.stats.pages, 'pdfplumber', BookOpen, 'blue'],
              ['Local text chunks', data.stats.chunks, 'preview, not embedded', Database, 'cyan'],
              ['OKF Markdown files', data.stats.markdown_files, `${data.stats.drug_files} drug listings`, FileCode, 'green'],
              ['NetworkX graph edges', data.stats.edges, `${data.stats.graph_nodes} nodes`, GitBranch, 'purple'],
            ].map(([label, value, note, Icon, color]) => <div className="metric panel" key={label}>
              <div><p>{label}</p><strong className={color}>{value}</strong><small>{note}</small></div>
              <div className={`metric-icon ${color}`}><Icon size={23} /></div>
            </div>)}
          </div>

          <div className="workspace">
            <aside className="panel sidebar">
              <div className="section-title"><Search size={16} /><h2>Available drug listings</h2></div>
              <p>Choose an actual generated Markdown file.</p>
              <label className="sr-only" htmlFor="drug-search">Search drug listings</label>
              <input id="drug-search" placeholder="Search drugs..." value={filter} onChange={event => setFilter(event.target.value)} />
              <div className="drug-list">
                {filtered.map(node => <button key={node.id} className={`drug-button ${selectedId === node.id ? 'selected' : ''}`} onClick={() => choose(node.id)}>
                  <span>{node.title}</span><small>{node.tier || 'Unknown tier'} · {node.raw_codes_found.join(', ') || 'No PA/QL/ST codes detected'}</small>
                </button>)}
                {!filtered.length && <p>No matching drug listings.</p>}
              </div>
              <div className="stack"><h3>Local pipeline</h3>
                <p><FileText size={14} /> PDF extraction <span>pdfplumber</span></p>
                <p><Database size={14} /> Text splitting <span>500 / 50</span></p>
                <p><GitBranch size={14} /> Graph engine <span>NetworkX</span></p>
                <p className="muted">Pinecone + OpenAI are available through the separate CLI, not called by this demo.</p>
              </div>
            </aside>

            <section className="content">
              {!active ? <div className="panel">Generate drug Markdown using the existing pipeline to inspect a listing.</div> : <>
                <div className="panel query-panel">
                  <span className="eyebrow purple">Source-backed inspection</span>
                  <h2>What tier and requirements are listed for {active.title}?</h2>
                  <p>This question is a suggested CLI query, not an AI response. Selection displays the actual source record below.</p>
                  <div className="query-footer"><span className="badge green">Local files loaded</span><code>{active.filename}</code></div>
                </div>

                <nav className="tabs" aria-label="Inspection workspace">
                  {[
                    ['inspection', Layers, 'PDF vs. graph inspection'],
                    ['graph', GitBranch, 'Interactive OKF graph'],
                    ['audit', Code, 'JSON source record'],
                  ].map(([id, Icon, label]) => <button key={id} aria-pressed={tab === id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
                    <Icon size={16} />{label}
                  </button>)}
                </nav>

                {tab === 'inspection' && <>
                  <div className="engine-grid">
                    <article className="panel engine"><div className="section-title cyan"><Database size={18} /><h3>1. PDF text chunk context</h3></div>
                      <span className="badge cyan">Local split-text preview</span>
                      <p>{exactSnippets.length ? 'Complete drug title found in these chunks.' : 'Source-page context only; the complete title may cross chunk boundaries.'}</p>
                      <div className="snippet-list">
                        {shownSnippets.length ? shownSnippets.map(chunk => <div className="snippet" key={`${chunk.page}-${chunk.index}`}>
                          <small>PDF page {chunk.page} · chunk {chunk.index + 1} · {chunk.text.length} characters</small><pre>{chunk.text}</pre>
                        </div>) : <p>No matching source/page chunks available.</p>}
                      </div>
                      <div className="panel-footer">No fabricated similarity score · No vector search performed</div>
                    </article>
                    <article className="panel engine"><div className="section-title green"><GitBranch size={18} /><h3>2. OKF node and source metadata</h3></div>
                      <span className="badge green">Actual Markdown listing</span>
                      <h3 className="node-title">{active.title}</h3>
                      <div className="tier">{active.tier || 'Unknown tier'}</div>
                      <div className="flags">{[
                        ['PA', 'prior_authorization'], ['QL', 'quantity_limit'], ['ST', 'step_therapy'],
                      ].map(([label, field]) => <span className={`flag ${active.restrictions[field] === true ? 'detected' : ''}`} key={field}>
                        {label}: {active.restrictions[field] === true ? 'Detected' : active.restrictions[field] === false ? 'Not detected' : 'Unknown'}
                      </span>)}</div>
                      <p>Raw requirements: <strong>{active.raw_requirements || 'No codes listed'}</strong></p>
                      <dl><dt>Source</dt><dd>{active.provenance.source}</dd><dt>PDF pages</dt><dd>{active.provenance.pages?.join(', ') || 'Unknown'}</dd>
                        <dt>Parsed date</dt><dd>{active.provenance.parsed_date || 'Unknown'}</dd></dl>
                      <p className="muted">A code not detected is not a coverage guarantee. Parsed date is not a verification date.</p>
                      <button className="secondary" onClick={() => download(active.filename, active.markdown, 'text/markdown')}><Download size={15} /> Download Markdown</button>
                    </article>
                  </div>
                  <article className="panel"><div className="section-title purple"><FileCode size={18} /><h3>Original generated Markdown</h3></div>
                    <details><summary>Inspect YAML frontmatter and body</summary><pre className="code-block">{active.markdown}</pre></details>
                  </article>
                </>}

                {tab === 'graph' && <article className="panel">
                  <div className="section-title purple"><GitBranch size={18} /><h3>Interactive NetworkX neighborhood</h3></div>
                  <p>Selected drug and directly connected nodes only. Counts above describe the full graph.</p>
                  <div className="graph-grid">
                    <div className="graph-canvas">
                      <svg viewBox="0 0 640 360" role="img" aria-label="Selected drug graph neighborhood">
                        <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#818cf8" /></marker></defs>
                        {related.filter(node => node.id !== active.id).map((node, index, others) => {
                          const y = 55 + index * (250 / Math.max(others.length - 1, 1));
                          return <g key={node.id}>
                            {edges.some(edge => edge.source === active.id && edge.target === node.id) && <path d={`M225,180 Q325,${y} 420,${y}`} fill="none" stroke="#818cf8" strokeWidth="2" markerEnd="url(#arrow)" />}
                            {edges.some(edge => edge.source === node.id) && <path d={`M420,${y + 22} Q325,${y + 100} 225,202`} fill="none" stroke="#34d399" strokeWidth="1.5" markerEnd="url(#arrow)" />}
                          </g>;
                        })}
                        {related.map((node, index) => {
                          const others = related.filter(item => item.id !== active.id);
                          const otherIndex = others.findIndex(item => item.id === node.id);
                          const x = node.id === active.id ? 40 : 420;
                          const y = node.id === active.id ? 155 : 30 + otherIndex * (250 / Math.max(others.length - 1, 1));
                          return <g key={node.id} role="button" aria-label={`Inspect ${node.title}`} tabIndex="0"
                            onClick={() => setInspectedId(node.id)}
                            onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setInspectedId(node.id); } }}>
                            <rect x={x} y={y} width="185" height="52" rx="12" fill="#151d36" stroke={inspected.id === node.id ? '#a5b4fc' : '#475569'} strokeWidth="2" />
                            <text x={x + 12} y={y + 22} fill="#e2e8f0" fontSize="11">{node.title.length > 23 ? `${node.title.slice(0, 22)}...` : node.title}</text>
                            <text x={x + 12} y={y + 39} fill="#94a3b8" fontSize="9">{node.type}</text>
                          </g>;
                        })}
                      </svg>
                    </div>
                    <div className="graph-detail"><span className="badge purple">Selected graph node</span><h3>{inspected.title}</h3><code>{inspected.id}</code><pre>{inspected.content}</pre></div>
                  </div>
                  <div className="table-scroll"><table><thead><tr><th>Source</th><th>Relation</th><th>Target</th></tr></thead><tbody>
                    {edges.map(edge => <tr key={`${edge.source}-${edge.target}`}><td>{edge.source}</td><td>{edge.relation}</td><td>{edge.target}</td></tr>)}
                  </tbody></table></div>
                </article>}

                {tab === 'audit' && <article className="panel">
                  <div className="record-heading"><div className="section-title green"><Code size={18} /><h3>Structured JSON source record</h3></div>
                    <button className="secondary" onClick={() => download(`${active.id}.json`, JSON.stringify(record, null, 2), 'application/json')}><Download size={15} /> Export JSON</button></div>
                  <p>Source inspection only. Not a FHIR resource, clinical compliance audit, diagnosis, or treatment recommendation.</p>
                  <pre className="code-block">{JSON.stringify(record, null, 2)}</pre>
                </article>}

                <div className="panel trace"><div className="section-title"><Terminal size={16} /><h3>Data provenance trace</h3></div>
                  <p>1. Read {data.stats.markdown_files} generated Markdown files from docs/okf.</p>
                  <p>2. Load {data.stats.graph_nodes} NetworkX nodes and {data.stats.edges} directed links.</p>
                  <p>3. Split cached PDF text into {data.stats.chunks} local preview chunks.</p>
                  <p>4. Inspect {active.id} with {edges.length} directly connected links.</p>
                  <p className="muted">No timed simulation or fabricated LLM response. Refresh reads local files; it does not re-download, re-embed, or modify Pinecone.</p>
                </div>
              </>}
            </section>
          </div>
        </>}
      </main>
      <footer>Local research explorer · Source rows are evidence, not independently validated clinical protocols</footer>
    </div>
  );
}
