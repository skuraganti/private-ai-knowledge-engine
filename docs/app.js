const $ = id => document.getElementById(id), el = (tag, text = '', parent) => { const node = document.createElement(tag); node.textContent = text; parent.append(node); return node; }, clear = node => node.replaceChildren();
const controls = $('controls'), workspace = $('workspace');
let data, hidden = new Set(), matches = [];
function panel(title, id, wide = false) { const section = el('section', '', workspace); section.className = `panel${wide ? ' wide' : ''}`; const h = el('h2', title, section); h.id = `${id}-title`; section.setAttribute('aria-labelledby', h.id); return section; }
function button(label, id, parent, action) { const b = el('button', label, parent); b.type = 'button'; b.id = id; if (action)
    b.addEventListener('click', action); return b; }
function setup() { controls.className = 'controls'; const query = el('label', 'Search NIST text', controls); const input = el('input', '', query); input.id = 'query'; input.type = 'search'; input.maxLength = 160; input.placeholder = 'e.g. risk management'; const doc = el('label', 'Document', controls), select = el('select', '', doc); select.id = 'document'; select.add(new Option('All documents', 'all')); button('Search passages', 'search', controls, search); button('Create extractive answer', 'answer', controls, answer); const out = panel('Extractive browser answer', 'answer-output', true); const region = el('div', 'Search and choose Create extractive answer.', out); region.id = 'answer-output'; region.setAttribute('role', 'region'); region.setAttribute('aria-label', 'Extractive answer'); region.setAttribute('aria-live', 'polite'); const results = panel('Passage matches', 'results'); const resultRegion = el('div', 'Enter a search term to begin.', results); resultRegion.id = 'results'; resultRegion.setAttribute('role', 'region'); resultRegion.setAttribute('aria-label', 'Search results'); resultRegion.setAttribute('aria-live', 'polite'); const shelf = panel('Document shelf', 'documents'); el('div', '', shelf).id = 'documents'; const row = el('div', '', shelf); row.className = 'controls'; button('Hide selected document', 'remove-document', row, removeDocument); button('Restore all', 'restore', row, restore); el('p', '', shelf).id = 'shelf-status'; const evaluation = panel('Recorded full-application evaluation', 'metrics', true); el('p', 'Saved benchmark results, separate from browser search; no hybrid superiority claim.', evaluation); el('div', '', evaluation).id = 'metrics'; input.addEventListener('input', () => { $('answer-output').textContent = 'Query changed. Create a new extractive answer.'; matches = []; clear($('results')); }); input.addEventListener('keydown', e => { if (e.key === 'Enter')
    search(); }); select.addEventListener('change', search); }
function renderShelf() { const root = $('documents'); clear(root); for (const doc of data.documents) {
    const row = el('p', '', root), label = el('label', '', row), input = el('input', '', label);
    input.type = 'checkbox';
    input.checked = hidden.has(doc.id);
    input.setAttribute('aria-label', `${hidden.has(doc.id) ? 'Hidden' : 'Visible'}: ${doc.title}`);
    input.addEventListener('change', () => { if (input.checked)
        hidden.add(doc.id);
    else
        hidden.delete(doc.id); updateVisibility(); renderShelf(); });
    const link = el('a', doc.title, label);
    link.href = doc.url;
    link.target = '_blank';
    link.rel = 'noreferrer';
    el('small', ` · SHA-256 ${doc.sha256}`, row);
    const toggle = button(hidden.has(doc.id) ? 'Show' : 'Hide', `toggle-${doc.id}`, row, () => { hidden.has(doc.id) ? hidden.delete(doc.id) : hidden.add(doc.id); updateVisibility(); renderShelf(); });
    toggle.className = 'secondary';
} }
function updateVisibility() { if ($('document').value !== 'all' && hidden.has($('document').value))
    $('document').value = 'all'; search(); }
function terms(value) { return value.toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) || []; }
function search() { if (!data)
    return; $('answer-output').textContent = 'Search updated. Create a new extractive answer.'; const query = $('query').value.trim(), words = [...new Set(terms(query))], doc = $('document').value; matches = []; if (!words.length) {
    $('results').textContent = 'Enter one or more words to search the supplied passages.';
    $('answer-output').textContent = 'No query selected.';
    return;
} matches = data.passages.filter(p => !hidden.has(p.document) && (doc === 'all' || p.document === doc)).map(p => ({ passage: p, score: words.reduce((sum, w) => sum + (p.text.toLocaleLowerCase().match(new RegExp(w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length, 0) })).filter(row => row.score > 0).sort((a, b) => b.score - a.score || a.passage.page - b.passage.page).slice(0, 20); renderMatches(); }
function citation(p, parent) { const link = el('a', `${p.title} · physical page ${p.page}`, parent); link.href = `${p.source_url}#page=${p.page}`; link.target = '_blank'; link.rel = 'noreferrer'; link.addEventListener('click', () => { const card = $(`passage-${CSS.escape(p.id)}`); if (card) {
    card.tabIndex = -1;
    card.focus();
} }); return link; }
function renderMatches() { const root = $('results'); clear(root); if (!matches.length) {
    root.textContent = 'No matching passage. No answer inferred.';
    return;
} matches.forEach(({ passage: p, score }, index) => { const card = el('article', '', root); card.id = `passage-${p.id}`; card.className = 'panel'; el('p', `Lexical match ${index + 1} · ${score} query term occurrences`, card); el('blockquote', p.text, card); citation(p, card); }); }
function answer() { if (!data)
    return; search(); const root = $('answer-output'); clear(root); if (!matches.length) {
    el('p', 'No matching supplied passage. Abstaining; no answer was generated.', root);
    return;
} el('p', 'Extractive browser answer — quoted source text only; not generated or verified synthesis.', root); matches.slice(0, 3).forEach(({ passage: p }) => { const quote = el('blockquote', p.text, root); quote.tabIndex = 0; citation(p, root); }); }
function removeDocument() { const id = $('document').value; if (id === 'all') {
    $('shelf-status').textContent = 'Choose a document in the filter to hide it.';
    return;
} hidden.add(id); updateVisibility(); renderShelf(); $('shelf-status').textContent = 'Document hidden locally; matching results and answer removed.'; }
function restore() { hidden.clear(); $('document').value = 'all'; $('shelf-status').textContent = 'All fixture documents restored.'; renderShelf(); search(); }
function renderMetrics() { const root = $('metrics'); clear(root); const table = el('table', '', root), caption = el('caption', 'Recorded full-app retrieval metrics', table); caption.className = 'visually-hidden'; const head = el('thead', '', table), tr = el('tr', '', head); ['Mode', 'n', 'Hit@5', 'MRR', 'Page recall@5', 'Mean ms', 'Median ms'].forEach(name => { const th = el('th', name, tr); th.scope = 'col'; }); const body = el('tbody', '', table); data.retrieval_metrics.forEach(row => { const tr = el('tr', '', body); [row.mode, row.n, String(row.hit_at_5), String(row.mrr), String(row.designated_page_recall_at_5), String(row.mean_ms), String(row.median_ms)].forEach(value => el('td', value, tr)); }); }
setup();
fetch('./demo-data.json').then(response => { if (!response.ok)
    throw Error('Fixture unavailable'); return response.json(); }).then(json => { if (!Array.isArray(json.documents) || json.documents.length !== 3 || !Array.isArray(json.passages) || !Array.isArray(json.retrieval_metrics) || !json.passages.every(p => typeof p.text === 'string' && Number.isFinite(p.page) && typeof p.source_url === 'string'))
    throw Error('Unexpected NIST fixture structure'); data = json; json.documents.forEach(doc => $('document').add(new Option(doc.title, doc.id))); renderShelf(); renderMetrics(); const attribution = $('source-attribution'); clear(attribution); json.documents.forEach((doc, index) => { if (index)
    attribution.append(document.createTextNode(' · ')); el('span', `${doc.title}, `, attribution); const link = el('a', doc.url, attribution); link.href = doc.url; link.target = '_blank'; link.rel = 'noreferrer'; }); $('status').textContent = `${json.passages.length} original passages across ${json.documents.length} NIST documents loaded. Browser lexical search only.`; }).catch(error => { $('status').textContent = `Cannot load NIST passage fixture: ${error.message}. Reload to try again.`; $('status').className = 'status error'; });
function labelScrollableContent() {
    document.querySelectorAll('.scroll, pre').forEach(node => {
        node.tabIndex = 0;
        if (!node.hasAttribute('role'))
            node.setAttribute('role', 'region');
        if (!node.hasAttribute('aria-label'))
            node.setAttribute('aria-label', `${node.closest('section')?.querySelector('h2')?.textContent || 'Recorded'} scrollable content`);
    });
}
new MutationObserver(labelScrollableContent).observe(document.getElementById('main'), { childList: true, subtree: true });
labelScrollableContent();
