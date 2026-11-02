// 상품 등록: 카테고리 단계별 드롭다운 + 검색, 상품명 글자 수
(() => {
  const codeInput = document.getElementById('cat-code');
  if (!codeInput) return;
  const levels = document.getElementById('cat-levels');
  const selected = document.getElementById('cat-selected');
  const search = document.getElementById('cat-search');
  const results = document.getElementById('cat-results');
  const byCode = new Map(), kids = new Map();
  let leaves = [];

  const pathOf = (code) => {
    const names = [];
    for (let n = byCode.get(code); n; n = byCode.get(n.p)) names.unshift(n.n);
    return names;
  };
  const chainOf = (code) => {
    const chain = [];
    for (let n = byCode.get(code); n; n = byCode.get(n.p)) chain.unshift(n.c);
    return chain;
  };

  function setCode(code, silent = false) {
    const isLeaf = code && !kids.has(code) && byCode.has(code);
    codeInput.value = isLeaf ? code : '';
    selected.className = 'cat-selected ' + (isLeaf ? 'ok' : 'todo');
    selected.textContent = isLeaf
      ? `✔ ${pathOf(code).join(' > ')}  (코드 ${code})`
      : (code ? '▸ 하위 분류를 이어서 선택하세요' : '대분류부터 선택하거나 위에서 검색하세요');
    if (!silent) codeInput.dispatchEvent(new Event('input', { bubbles: true }));  // 임시저장 '변경 있음' 표시
  }

  function render(chain) {
    levels.replaceChildren();
    let parent = '0';
    for (let depth = 0; ; depth++) {
      const children = kids.get(parent);
      if (!children) break;
      const sel = document.createElement('select');
      sel.dataset.depth = depth;
      sel.append(new Option(depth === 0 ? '대분류 선택' : `${depth + 1}단계 선택`, ''));
      children.forEach((n) => sel.append(new Option(n.n + (kids.has(n.c) ? ' ›' : ''), n.c)));
      sel.value = chain[depth] || '';
      sel.addEventListener('change', () => {
        render(chainOf(sel.value || parent));
        setCode(sel.value);
      });
      levels.append(sel);
      if (!chain[depth]) break;
      parent = chain[depth];
    }
  }

  function showResults(q) {
    q = q.trim().toLowerCase();
    if (!q) { results.hidden = true; return; }
    const words = q.split(/\s+/);
    const scored = [];
    for (const c of leaves) {
      const names = pathOf(c);
      const lower = names.join(' > ').toLowerCase();
      if (c !== q && !words.every((w) => lower.includes(w))) continue;
      // 정렬: 코드 일치 → 마지막 단계 이름 일치 → 이름이 검색어로 시작 → 이름에 포함 → 상위 경로에만 포함
      const leaf = names[names.length - 1].toLowerCase(), parent = (names[names.length - 2] || '').toLowerCase();
      const score = c === q ? 0 : leaf === q ? 1 : parent === q ? 2 : leaf.startsWith(q) ? 3 : leaf.includes(q) ? 4 : 5;
      scored.push([score, names.length, c, names.join(' > ')]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[3].localeCompare(b[3], 'ko'));
    const hits = scored.slice(0, 50).map(([, , c, p]) => [c, p]);
    results.replaceChildren(...(hits.length ? hits.map(([c, p]) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'cat-hit';
      b.textContent = p;
      const code = document.createElement('small'); code.textContent = c;
      b.append(code);
      b.addEventListener('click', () => pick(c));
      return b;
    }) : [Object.assign(document.createElement('div'), { className: 'muted cat-none', textContent: '검색 결과가 없습니다' })]));
    results.hidden = false;
  }

  function pick(code) {
    render(chainOf(code));
    setCode(code);
    search.value = '';
    results.hidden = true;
  }

  search.addEventListener('input', () => showResults(search.value));
  search.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); results.querySelector('.cat-hit')?.click(); }
    if (e.key === 'Escape') results.hidden = true;
  });
  document.addEventListener('click', (e) => { if (!e.target.closest('.cat-search-wrap')) results.hidden = true; });

  fetch('/api/categories').then((r) => r.json()).then((d) => {
    for (const n of d.nodes) {
      byCode.set(n.c, n);
      if (!kids.has(n.p)) kids.set(n.p, []);
      kids.get(n.p).push(n);
    }
    kids.forEach((list) => list.sort((a, b) => a.n.localeCompare(b.n, 'ko')));
    leaves = [...byCode.keys()].filter((c) => !kids.has(c));
    const cur = codeInput.value.trim();
    if (cur && !byCode.has(cur)) {  // 목록에 없는 코드(이전 임시저장 등)는 그대로 두고 알려 준다
      render([]);
      selected.className = 'cat-selected todo';
      selected.textContent = `⚠ 코드 ${cur} 는 현재 카테고리 목록에 없습니다. 다시 선택하세요`;
      return;
    }
    render(chainOf(cur));
    setCode(cur, true);
  });

  // 상품명 글자 수
  document.querySelectorAll('.cnt').forEach((el) => {
    const input = document.querySelector(`[name="${el.dataset.for}"]`);
    const upd = () => { el.textContent = input.value.length ? `${input.value.length}자` : ''; };
    input.addEventListener('input', upd); upd();
  });
})();
