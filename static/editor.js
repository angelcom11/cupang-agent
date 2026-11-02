// 상품 등록: 대표 이미지 업로드 + 상세설명 위지윅 에디터 + 임시저장 보조
(() => {
  const form = document.getElementById('reg-form');
  if (!form) return;
  const editor = document.getElementById('editor');
  const src = document.getElementById('desc-src');
  const dirty = document.getElementById('dirty');
  let srcMode = false, changed = false, submitting = false, savedRange = null;

  async function upload(file, kind = '') {
    const fd = new FormData();
    fd.append('file', file);
    if (kind) fd.append('kind', kind);
    const res = await fetch('/api/upload', { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({ error: `업로드 실패 (${res.status})` }));
    if (!res.ok || data.error) throw new Error(data.error || `업로드 실패 (${res.status})`);
    return data.url;
  }

  function markDirty() {
    changed = true;
    dirty.textContent = '● 저장 안 된 변경 있음';
  }

  // ---------- 대표 이미지 ----------
  const thumb = document.getElementById('thumb');
  const urlInput = document.getElementById('image_url');
  const imgMsg = document.getElementById('img-msg');
  function showThumb(url) {
    if (!url) { thumb.replaceChildren(Object.assign(document.createElement('span'), { textContent: '미리보기' })); return; }
    const img = document.createElement('img');
    img.src = url; img.alt = '';
    img.onerror = () => { imgMsg.textContent = '⚠ 이미지를 불러올 수 없습니다. 주소를 확인하세요.'; };
    thumb.replaceChildren(img);
  }
  document.getElementById('img-file').addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    imgMsg.textContent = '업로드 중…';
    try {
      const url = await upload(f);
      urlInput.value = url; showThumb(url); markDirty();
      imgMsg.textContent = `✔ 업로드 완료: ${f.name}`;
    } catch (err) { imgMsg.textContent = '⚠ ' + err.message; }
    e.target.value = '';
  });
  urlInput.addEventListener('change', () => showThumb(urlInput.value.trim()));

  // ---------- 위지윅 에디터 ----------
  // 에디터에 넣기 전 실행 가능한 요소·속성을 제거 (서버 clean_html 과 같은 규칙, DOMParser 문서는 스크립트를 실행하지 않음)
  function setEditorHtml(html) {
    const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html');
    doc.querySelectorAll('script,style,iframe,object,embed,form,meta,link').forEach((n) => n.remove());
    doc.querySelectorAll('*').forEach((el) => [...el.attributes].forEach((a) => {
      if (/^on/i.test(a.name) || /^\s*javascript:/i.test(a.value)) el.removeAttribute(a.name);
    }));
    editor.replaceChildren(...doc.body.childNodes);
  }
  setEditorHtml(src.value);
  document.execCommand('styleWithCSS', false, false);  // <b>·<i>·<u> 태그로 저장 (쿠팡 상세페이지 호환)
  document.execCommand('defaultParagraphSeparator', false, 'p');

  const saveSel = () => {
    const s = getSelection();
    if (s.rangeCount && editor.contains(s.anchorNode)) savedRange = s.getRangeAt(0).cloneRange();
  };
  const restoreSel = () => {
    editor.focus();
    if (savedRange) { const s = getSelection(); s.removeAllRanges(); s.addRange(savedRange); }
  };
  editor.addEventListener('keyup', saveSel);
  editor.addEventListener('mouseup', saveSel);
  editor.addEventListener('input', () => { saveSel(); markDirty(); });

  const tb = document.getElementById('tb');
  tb.addEventListener('mousedown', (e) => { if (e.target.closest('button')) e.preventDefault(); }); // 선택영역 유지
  tb.querySelectorAll('[data-cmd]').forEach((b) => b.addEventListener('click', () => {
    restoreSel(); document.execCommand(b.dataset.cmd, false, null); saveSel(); markDirty();
  }));
  tb.querySelector('[data-block]').addEventListener('change', (e) => {
    restoreSel(); document.execCommand('formatBlock', false, e.target.value); markDirty();
  });
  tb.querySelector('[data-color]').addEventListener('input', (e) => {
    restoreSel(); document.execCommand('foreColor', false, e.target.value); markDirty();
  });
  document.getElementById('tb-link').addEventListener('click', () => {
    const url = prompt('링크 주소 (https://...)');
    if (!url) return;
    if (!/^https?:\/\//i.test(url)) { alert('http:// 또는 https:// 로 시작하는 주소만 넣을 수 있습니다'); return; }
    restoreSel(); document.execCommand('createLink', false, url); markDirty();
  });

  async function insertImages(files) {
    for (const f of files) {
      try {
        const url = await upload(f);
        restoreSel(); document.execCommand('insertImage', false, url); saveSel(); markDirty();
      } catch (err) { alert(err.message); }
    }
  }
  const edFile = document.getElementById('ed-file');
  document.getElementById('tb-img').addEventListener('click', () => { saveSel(); edFile.click(); });
  edFile.addEventListener('change', async (e) => { await insertImages([...e.target.files]); e.target.value = ''; });
  editor.addEventListener('paste', (e) => {  // 붙여넣은 이미지는 data: 대신 업로드해서 주소로 넣는다
    const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/'));
    if (files.length) { e.preventDefault(); saveSel(); insertImages(files); }
  });
  editor.addEventListener('drop', (e) => {
    const files = [...(e.dataTransfer?.files || [])].filter((f) => f.type.startsWith('image/'));
    if (files.length) { e.preventDefault(); saveSel(); insertImages(files); }
  });

  const srcBtn = document.getElementById('tb-src');
  srcBtn.addEventListener('click', () => {
    srcMode = !srcMode;
    if (srcMode) { src.value = editor.innerHTML; } else { setEditorHtml(src.value); }
    editor.hidden = srcMode; src.hidden = !srcMode;
    srcBtn.classList.toggle('on', srcMode);
    tb.querySelectorAll('button:not(#tb-src), select, label.tbc').forEach((el) => el.classList.toggle('disabled', srcMode));
  });
  src.addEventListener('input', markDirty);

  // ---------- 저장 ----------
  // 옵션 표·고시정보처럼 나중에 생기는 칸도 포함하도록 form 에 위임
  const onEdit = (e) => { if (!e.target.closest('#tb, #cat-search') && e.target !== editor && !editor.contains(e.target)) markDirty(); };
  form.addEventListener('input', onEdit);
  form.addEventListener('change', onEdit);
  window.wingForm = { upload, markDirty };
  form.addEventListener('submit', () => {
    if (!srcMode) src.value = editor.innerHTML.trim() === '<p><br></p>' ? '' : editor.innerHTML;
    submitting = true;
  });
  addEventListener('beforeunload', (e) => { if (changed && !submitting) { e.preventDefault(); e.returnValue = ''; } });
  addEventListener('keydown', (e) => {  // Ctrl/Cmd+S = 임시저장
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
      e.preventDefault(); document.getElementById('btn-draft').click();
    }
  });
})();
