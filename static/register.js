// 상품 등록 (쿠팡 WING 상품등록 화면 순서): 옵션, 상품이미지, 상세설명, 상품 주요정보, 검색어, 검색필터,
// 상품정보제공고시, 배송, 반품/교환, 구비서류, 판매요청 — 카테고리 메타·출고지/반품지는 쿠팡 API에서 불러온다
(() => {
  const form = document.getElementById('reg-form');
  if (!form) return;
  const $ = (id) => document.getElementById(id);
  const el = (tag, { dataset, ...props } = {}, ...kids) => {
    const n = Object.assign(document.createElement(tag), props);
    Object.assign(n.dataset, dataset || {});  // dataset 은 읽기 전용 속성이라 따로 채운다
    kids.forEach((k) => n.append(k));
    return n;
  };
  const S = JSON.parse($('reg-state').textContent);
  const dirty = () => window.wingForm && window.wingForm.markDirty();
  const upload = (f, kind) => window.wingForm.upload(f, kind);
  const NO_RETURN = 'NO_RETURN_CENTERCODE';
  const MAX_TYPES = 3, MAX_OPTIONS = 200, MAX_GALLERY = 9, MAX_TAGS = 20;
  const NOTICE_REF = '상품 상세페이지 참조';
  let meta = null;

  const val = (n) => (form.elements[n]?.value || '').trim();
  const money = (v) => Number(String(v ?? '').replace(/,/g, '').trim());
  const isNum = (v) => /^\d+$/.test(String(v ?? '').replace(/,/g, '').trim());
  const radios = (n) => [...form.querySelectorAll(`input[type=radio][name="${n}"]`)];
  const setRadio = (n, v) => radios(n).forEach((r) => { r.checked = r.value === v; });
  const onRadio = (n, fn) => radios(n).forEach((r) => r.addEventListener('change', fn));
  const choiceText = (n) => {  // select 는 고른 항목, 라디오는 고른 버튼의 글자
    const e = form.elements[n];
    if (!e) return '';
    if (e.tagName === 'SELECT') return e.selectedOptions[0]?.textContent.trim() || '';
    return radios(n).find((r) => r.checked)?.closest('label').textContent.trim() || '';
  };
  const show = (node, on) => { node.hidden = !on; };
  const sellOn = () => form.elements.sell_seller.checked, rocketOn = () => form.elements.sell_rocket.checked;

  // ================= 옵션 =================
  const newOption = (values = {}) => ({ values, name: '', original_price: '', sale_price: '', stock: '', sku: '', model_no: '', barcode: '' });
  if (!S.options.length) S.options.push(newOption());
  let types = S.option_types.map((t) => ({ name: t, values: [...new Set(S.options.map((o) => o.values[t]).filter(Boolean))].join(', ') }));
  let optMode = S.option_types.length || S.options.length > 1 ? 'multi' : 'single';
  const attrOf = (name) => (meta?.attributes || []).find((a) => a.attributeTypeName === name);
  const unitHint = (a) => (a && a.dataType === 'NUMBER') ? ((a.usableUnits || []).filter(Boolean).join('/') || a.basicUnit || '') : '';

  function setOptMode(mode) {
    optMode = mode;
    $('opt-mode').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
    show($('opt-multi'), mode === 'multi');
    if (mode === 'single') {  // 단일 상품: 옵션 종류 없이 한 줄
      types = []; S.option_types = []; S.options = [{ ...(S.options[0] || newOption()), values: {} }];
    } else if (!types.length) types.push({ name: '', values: '' });
    renderTypes(); renderTable();
  }
  $('opt-mode').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { if (b.dataset.mode !== optMode) { setOptMode(b.dataset.mode); dirty(); } }));

  function renderTypes() {
    $('optypes').replaceChildren(...types.map((t, i) => {
      const a = attrOf(t.name), unit = unitHint(a);
      const name = el('input', { value: t.name, placeholder: '옵션명 (예: 색상)', className: 'tname' });
      name.setAttribute('list', 'attr-names');
      name.addEventListener('input', () => { t.name = name.value.trim(); });
      name.addEventListener('change', () => renderTypes());
      const vals = el('input', { value: t.values, className: 'tvals',
        placeholder: unit ? `옵션값을 콤마(,)로 구분 (예: 350${unit.split('/').pop()}, 500${unit.split('/').pop()})` : '옵션값을 콤마(,)로 구분 (예: 블랙, 화이트)' });
      vals.addEventListener('input', () => { t.values = vals.value; });
      const del = el('button', { type: 'button', className: 'ghost tiny', textContent: '✕', title: '이 옵션명 빼기' });
      del.addEventListener('click', () => { types.splice(i, 1); if (!types.length) types.push({ name: '', values: '' }); buildOptions(); renderTypes(); dirty(); });
      return el('div', { className: 'optype' }, name, vals, del, el('span', { className: 'muted unit', textContent: unit ? `단위: ${unit}` : '' }));
    }));
    $('opt-addtype').disabled = types.length >= MAX_TYPES;
    renderSuggest(); renderFixed();
  }
  $('opt-addtype').addEventListener('click', () => { if (types.length < MAX_TYPES) { types.push({ name: '', values: '' }); renderTypes(); } });

  function renderSuggest() {
    const box = $('opt-suggest');
    const exposed = (meta?.attributes || []).filter((a) => a.exposed === 'EXPOSED');
    if (!exposed.length) { box.replaceChildren(); return; }
    const used = new Set(types.map((t) => t.name));
    box.replaceChildren('추천 옵션명: ', ...exposed.map((a) => {
      const b = el('button', { type: 'button', className: 'optchip' + (used.has(a.attributeTypeName) ? ' on' : ''),
        textContent: a.attributeTypeName + (a.required === 'MANDATORY' ? ' *' : '') });
      b.disabled = used.has(a.attributeTypeName) || (types.length >= MAX_TYPES && !types.some((t) => !t.name));
      b.addEventListener('click', () => {
        const blank = types.find((t) => !t.name);
        if (blank) blank.name = a.attributeTypeName; else types.push({ name: a.attributeTypeName, values: '' });
        renderTypes();
      });
      return b;
    }), el('span', { textContent: '(* 필수: 옵션으로 쓰지 않으면 아래 구매옵션에 입력)' }));
  }

  // 필수 구매옵션 중 옵션명으로 쓰지 않은 것 → 모든 옵션 공통 값 (예: 수량 1개)
  function renderFixed() {
    const used = new Set(optMode === 'multi' ? types.map((t) => t.name) : []);
    const need = (meta?.attributes || []).filter((a) => a.exposed === 'EXPOSED' && !used.has(a.attributeTypeName));
    show($('opt-fixed-row'), need.length > 0);
    $('fix-attrs').replaceChildren(...need.map((a) => {
      const unit = unitHint(a), n = a.attributeTypeName;
      const input = el('input', { value: S.fixed_attrs[n] || '', placeholder: unit ? `예: 1${unit.split('/').pop()}` : '' });
      input.addEventListener('input', () => { S.fixed_attrs[n] = input.value.trim(); });
      return el('label', {}, el('span', { textContent: n + (a.required === 'MANDATORY' ? ' *' : '') + (unit ? ` (${unit})` : '') }), input);
    }));
  }

  // 옵션명·값 → 옵션 조합. 이미 입력한 가격·재고는 같은 조합에 그대로 남긴다.
  function buildOptions() {
    const ts = types.filter((t) => t.name);
    const lists = ts.map((t) => [...new Set(t.values.split(',').map((v) => v.trim()).filter(Boolean))]);
    const key = (vals) => ts.map((t) => vals[t.name] || '').join('\u0001');
    const old = new Map(S.options.map((o) => [key(o.values), o]));
    let combos = [{}];
    ts.forEach((t, i) => { combos = combos.flatMap((c) => (lists[i].length ? lists[i] : ['']).map((v) => ({ ...c, [t.name]: v }))); });
    if (combos.length > MAX_OPTIONS) { alert(`옵션 조합이 ${combos.length}개입니다. 최대 ${MAX_OPTIONS}개까지 만들 수 있어요.`); return false; }
    const first = S.options[0] || newOption();
    S.option_types = ts.map((t) => t.name);
    S.options = combos.map((vals) => {
      const o = old.get(key(vals));
      return o ? { ...o, values: vals } : { ...newOption(vals), original_price: first.original_price, sale_price: first.sale_price, stock: first.stock };
    });
    renderTable(); renderFixed();
    return true;
  }
  $('opt-build').addEventListener('click', () => {
    if (!types.some((t) => t.name)) { alert('옵션명을 입력하세요.'); return; }
    if (types.some((t) => t.name && !t.values.trim())) { alert('옵션값이 비어 있는 옵션명이 있어요.'); return; }
    if (buildOptions()) dirty();
  });

  const COLS = [['original_price', '정상가', 'numeric'], ['sale_price', '판매가 *', 'numeric'], ['discount', '할인율'],
    ['stock', '재고수량', 'numeric'], ['sku', '판매자상품코드', ''], ['model_no', '모델번호', ''], ['barcode', '바코드', '']];
  const discountOf = (o) => {
    const op = money(o.original_price), sp = money(o.sale_price);
    return op > 0 && sp > 0 && op > sp ? `${Math.floor(((op - sp) / op) * 100)}%` : '-';
  };
  function renderTable() {
    const t = $('opt-table'), multi = optMode === 'multi', ts = S.option_types;
    const all = el('input', { type: 'checkbox', title: '전체 선택' });
    all.addEventListener('change', () => t.querySelectorAll('tbody .osel').forEach((c) => { c.checked = all.checked; }));
    const nameCols = multi ? (ts.length ? ts : ['옵션명']) : [];
    const ownBarcode = rocketOn() && val('rg_barcode_mode') === 'own';
    const cols = COLS.filter(([k]) => k !== 'stock' || sellOn())  // 로켓그로스만이면 재고는 입고 수량으로 정해짐
      .map(([k, label, mode]) => [k, k === 'barcode' && ownBarcode ? '바코드 *' : label, mode]);
    const head = el('tr', {}, ...(multi ? [el('th', {}, all)] : []), ...nameCols.map((n) => el('th', { textContent: n })),
      ...cols.map(([, label]) => el('th', { textContent: label })), ...(multi ? [el('th')] : []));
    const body = el('tbody');
    S.options.forEach((o, i) => {
      const tr = el('tr');
      if (multi) {
        tr.append(el('td', {}, el('input', { type: 'checkbox', className: 'osel' })));
        if (ts.length) {
          ts.forEach((n) => {
            const inp = el('input', { value: o.values[n] || '', className: 'oval' });
            inp.addEventListener('input', () => { o.values[n] = inp.value.trim(); });
            tr.append(el('td', { dataset: { label: n } }, inp));
          });
        } else {
          const inp = el('input', { value: o.name || '', className: 'oname', placeholder: '옵션명' });
          inp.addEventListener('input', () => { o.name = inp.value; });
          tr.append(el('td', { dataset: { label: '옵션명' } }, inp));
        }
      }
      const disc = el('span', { className: 'disc', textContent: discountOf(o) });
      cols.forEach(([k, label, mode]) => {
        if (k === 'discount') { tr.append(el('td', { dataset: { label } }, disc)); return; }
        const inp = el('input', { value: o[k] || '', inputMode: mode || 'text' });
        inp.addEventListener('input', () => { o[k] = inp.value.trim(); disc.textContent = discountOf(o); });
        tr.append(el('td', { dataset: { label } }, inp));
      });
      if (multi) {
        const del = el('button', { type: 'button', className: 'ghost tiny', textContent: '삭제', disabled: S.options.length === 1 });
        del.addEventListener('click', () => { S.options.splice(i, 1); renderTable(); dirty(); });
        tr.append(el('td', {}, del));
      }
      body.append(tr);
    });
    t.replaceChildren(el('thead', {}, head), body);
    $('opt-count').textContent = multi ? `옵션 ${S.options.length}개` : '';
    show($('opt-bulk'), multi && S.options.length > 1);
    show($('opt-addrow'), multi);
  }
  $('opt-addrow').addEventListener('click', () => {
    if (S.options.length >= MAX_OPTIONS) return;
    S.options.push(newOption(Object.fromEntries(S.option_types.map((n) => [n, ''])))); renderTable(); dirty();
  });
  $('opt-apply').addEventListener('click', () => {
    const rows = [...$('opt-table').querySelectorAll('tbody tr')];
    const picked = rows.map((r, i) => r.querySelector('.osel')?.checked ? i : -1).filter((i) => i >= 0);
    const targets = picked.length ? picked : S.options.map((_, i) => i);
    document.querySelectorAll('[data-bulk]').forEach((inp) => {
      const v = inp.value.trim();
      if (v) targets.forEach((i) => { S.options[i][inp.dataset.bulk] = v; });
      inp.value = '';
    });
    renderTable(); dirty();
  });

  // ================= 카테고리 메타 =================
  const metaMsg = $('meta-msg');
  async function loadMeta(code) {
    if (!code) { meta = null; renderMeta(); return; }
    metaMsg.textContent = '쿠팡에서 카테고리 정보를 불러오는 중…';
    try {
      const res = await fetch(`/api/category-meta/${code}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.status);
      meta = data;
      const need = data.attributes.filter((a) => a.required === 'MANDATORY').map((a) => a.attributeTypeName);
      metaMsg.textContent = `✔ 불러옴 · 필수 구매옵션: ${need.join(', ') || '없음'} · 상품정보제공고시 ${data.noticeCategories.length}종 · 구비서류 ${data.requiredDocumentNames.length}종`;
    } catch (err) {
      meta = null;
      metaMsg.textContent = '⚠ ' + err.message;
    }
    renderMeta();
  }
  function renderMeta() {
    if (form.elements.rg_inbound) syncRocket();
    const dl = $('attr-names') || document.body.appendChild(el('datalist', { id: 'attr-names' }));
    dl.replaceChildren(...(meta?.attributes || []).filter((a) => a.exposed === 'EXPOSED').map((a) => el('option', { value: a.attributeTypeName })));
    renderTypes(); renderFilters(); renderCerts(); renderNoticeCats(); renderDocs(); renderOffer();
    refreshSummary();
  }
  function refreshSummary() {  // 카테고리 정보·출고지가 늦게 도착하면 요약과 단계 표시를 다시 그린다
    if (curInput.value === 's-confirm') renderSummary();
    paintSteps();
  }

  // ================= 상품 주요정보 =================
  const brand = $('brand'), brandNone = $('brand-none');
  const syncBrand = () => { brand.disabled = brandNone.checked; if (brandNone.checked) brand.value = ''; };
  brandNone.addEventListener('change', syncBrand);

  // 인증정보: 인증·신고 대상 / 상세페이지 별도표기 / 인증·신고 대상 아님 (WING 라디오) → certification_type
  const certSel = $('cert-type'), certWrap = $('cert-code-wrap');
  const SPECIAL = { none: 'NOT_REQUIRED', detail: 'PRESENTED_IN_DETAIL_PAGE' };
  const certMode = () => radios('cert_mode').find((r) => r.checked)?.value || 'none';
  function renderCerts() {
    const cur = certSel.value || certSel.dataset.value || '';
    const certs = (meta?.certifications || []).filter((c) => !Object.values(SPECIAL).includes(c.certificationType));
    certSel.replaceChildren(
      el('option', { value: SPECIAL.none, textContent: '인증·신고 대상 아님', hidden: true }),
      el('option', { value: SPECIAL.detail, textContent: '상세페이지 별도표기', hidden: true }),
      ...(certs.length ? [el('option', { value: '', textContent: '인증 종류 선택' })] : [el('option', { value: '', textContent: '카테고리를 먼저 고르세요' })]),
      ...certs.map((c) => el('option', { value: c.certificationType, textContent: c.name + (c.dataType === 'CODE' ? ' (인증번호 필요)' : '') })));
    if ([...certSel.options].some((o) => o.value === cur)) certSel.value = cur;
    if (!radios('cert_mode').some((r) => r.checked)) setRadio('cert_mode', cur === SPECIAL.detail ? 'detail' : (cur && cur !== SPECIAL.none ? 'target' : 'none'));
    syncCert();
  }
  function syncCert() {
    const mode = certMode();
    if (mode !== 'target') certSel.value = SPECIAL[mode];
    else if (Object.values(SPECIAL).includes(certSel.value)) certSel.value = '';
    show($('cert-target'), mode === 'target');
    const c = (meta?.certifications || []).find((x) => x.certificationType === certSel.value);
    certWrap.hidden = !(mode === 'target' && c && c.dataType === 'CODE');
  }
  onRadio('cert_mode', syncCert);
  certSel.addEventListener('change', syncCert);

  function renderOffer() {
    const allowed = meta?.allowedOfferConditions;
    radios('offer_condition').forEach((r) => { r.disabled = !!allowed && !allowed.includes(r.value); r.closest('label').classList.toggle('dis', r.disabled); });
    if (radios('offer_condition').some((r) => r.checked && r.disabled)) setRadio('offer_condition', 'NEW');
    show($('offer-desc-wrap'), val('offer_condition').startsWith('USED'));
  }
  onRadio('offer_condition', renderOffer);

  // 인당 최대구매수량 · 판매기간: 설정안함 / 설정함
  setRadio('maxbuy_mode', money(val('max_per_person')) > 0 ? 'on' : 'off');
  const farFuture = (v) => !v || v.startsWith('2099');
  setRadio('period_mode', val('sale_start') || !farFuture(val('sale_end')) ? 'on' : 'off');
  const syncLimits = () => {
    show($('maxbuy-fields'), val('maxbuy_mode') === 'on');
    show($('period-fields'), val('period_mode') === 'on');
  };
  onRadio('maxbuy_mode', syncLimits); onRadio('period_mode', syncLimits);

  // ================= 검색어 (태그) =================
  const tagHidden = $('search-tags'), tagInput = $('tag-input');
  let tags = [...new Set(tagHidden.value.split(',').map((t) => t.trim()).filter(Boolean))].slice(0, MAX_TAGS);
  function renderTags() {
    $('tagbox').querySelectorAll('.tag').forEach((n) => n.remove());
    tags.forEach((t, i) => {
      const x = el('button', { type: 'button', textContent: '✕', title: '빼기' });
      x.addEventListener('click', () => { tags.splice(i, 1); renderTags(); dirty(); });
      tagInput.before(el('span', { className: 'tag' }, t, x));
    });
    tagHidden.value = tags.join(',');
    $('tag-count').textContent = tags.length;
    tagInput.disabled = tags.length >= MAX_TAGS;
    tagInput.placeholder = tags.length >= MAX_TAGS ? '최대 20개까지 입력했습니다' : '검색어 입력 후 Enter 또는 콤마(,)';
  }
  function addTags(text) {
    for (const t of text.split(',').map((x) => x.trim()).filter(Boolean)) {
      if (tags.length >= MAX_TAGS) break;
      if (!tags.includes(t)) tags.push(t);
    }
    tagInput.value = ''; renderTags(); dirty();
  }
  tagInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); if (tagInput.value.trim()) addTags(tagInput.value); }
    else if (e.key === 'Backspace' && !tagInput.value && tags.length) { tags.pop(); renderTags(); dirty(); }
  });
  tagInput.addEventListener('blur', () => { if (tagInput.value.trim()) addTags(tagInput.value); });
  tagInput.addEventListener('paste', (e) => { const t = e.clipboardData.getData('text'); if (t.includes(',')) { e.preventDefault(); addTags(t); } });
  $('tagbox').addEventListener('click', (e) => { if (e.target.id === 'tagbox') tagInput.focus(); });

  // ================= 검색필터 =================
  function renderFilters() {
    const box = $('filter-attrs');
    const list = (meta?.attributes || []).filter((a) => a.exposed !== 'EXPOSED');
    if (!list.length) { box.replaceChildren(el('span', { className: 'muted', textContent: meta ? '이 카테고리는 검색필터가 없습니다.' : '카테고리를 고르면 나타납니다.' })); return; }
    box.replaceChildren(...list.map((a) => {
      const n = a.attributeTypeName, unit = unitHint(a);
      let inp;
      if ((a.inputValues || []).length) {
        inp = el('select', {}, el('option', { value: '', textContent: '선택 안 함' }), ...a.inputValues.map((v) => el('option', { value: v, textContent: v })));
        inp.value = S.filter_attrs[n] || '';
      } else {
        inp = el('input', { value: S.filter_attrs[n] || '', placeholder: unit ? `예: 1${unit.split('/').pop()}` : '' });
      }
      const save = () => { S.filter_attrs[n] = inp.value.trim(); };
      inp.addEventListener('change', save); inp.addEventListener('input', save);
      return el('div', { className: 'wrow' }, el('div', { className: 'wlabel' + (a.required === 'MANDATORY' ? ' req' : ''), textContent: n }), el('div', { className: 'wfield' }, inp));
    }));
  }

  // ================= 상품정보제공고시 =================
  const noticeSel = $('notice-cat'), noticeAll = $('notice-all');
  function renderNoticeCats() {
    const cur = noticeSel.value || noticeSel.dataset.value || '';
    const cats = meta?.noticeCategories || [];
    noticeSel.replaceChildren(el('option', { value: '', textContent: cats.length ? '상품군을 선택하세요' : '카테고리를 먼저 고르세요' }),
      ...cats.map((c) => el('option', { value: c.noticeCategoryName, textContent: c.noticeCategoryName })));
    if (cats.some((c) => c.noticeCategoryName === cur)) noticeSel.value = cur;
    else if (cats.length === 1) noticeSel.value = cats[0].noticeCategoryName;
    renderNotices();
  }
  function noticeCat() { return (meta?.noticeCategories || []).find((c) => c.noticeCategoryName === noticeSel.value); }
  function renderNotices() {
    const cat = noticeCat();
    if (!cat) { $('notice-fields').replaceChildren(); noticeAll.checked = false; return; }
    $('notice-fields').replaceChildren(...cat.noticeCategoryDetailNames.map((d) => {
      const n = d.noticeCategoryDetailName;
      const inp = el('input', { value: S.notices[n] || '', placeholder: NOTICE_REF });
      inp.addEventListener('input', () => { S.notices[n] = inp.value; noticeAll.checked = false; });
      return el('div', { className: 'wrow' }, el('div', { className: 'wlabel' + (d.required === 'MANDATORY' ? ' req' : ''), textContent: n }), el('div', { className: 'wfield' }, inp));
    }));
    noticeAll.checked = cat.noticeCategoryDetailNames.every((d) => S.notices[d.noticeCategoryDetailName] === NOTICE_REF);
  }
  noticeSel.addEventListener('change', renderNotices);
  noticeAll.addEventListener('change', () => {  // WING '전체 상품 상세페이지 참조'
    const cat = noticeCat();
    if (!cat) { noticeAll.checked = false; return; }
    cat.noticeCategoryDetailNames.forEach((d) => {
      const n = d.noticeCategoryDetailName;
      if (noticeAll.checked) S.notices[n] = NOTICE_REF; else if (S.notices[n] === NOTICE_REF) S.notices[n] = '';
    });
    renderNotices(); dirty();
  });

  // ================= 구비서류 =================
  const docNeeded = {
    MANDATORY: () => true,
    MANDATORY_PARALLEL_IMPORTED: () => val('parallel_imported') === '1',
    MANDATORY_OVERSEAS_PURCHASED: () => val('delivery_method') === 'AGENT_BUY',
  };
  const DOC_LABEL = { OPTIONAL: '선택', MANDATORY_PARALLEL_IMPORTED: '병행수입이면 필수', MANDATORY_OVERSEAS_PURCHASED: '구매대행이면 필수',
    MANDATORY_BATTERY_UN_TEST: '배터리 포함 상품이면 필수', MANDATORY_BATTERY_MSDS_TEST: '배터리 포함 상품이면 필수',
    MANDATORY_INGREDIENTS_PIC: '성분 표시가 필요한 상품이면 필수' };
  const requiredDocs = () => (meta?.requiredDocumentNames || []).filter((d) => docNeeded[d.required]?.()).map((d) => d.templateName);
  function renderDocs() {
    const box = $('doc-list');
    const docs = meta?.requiredDocumentNames || [];
    if (!docs.length) { box.replaceChildren(el('span', { className: 'muted', textContent: meta ? '이 카테고리는 구비서류가 없습니다.' : '카테고리를 고르면 이 카테고리에서 요구하는 서류가 나타납니다.' })); return; }
    box.replaceChildren(...docs.map((d) => {
      const n = d.templateName, req = !!docNeeded[d.required]?.();
      const status = el('span', { className: 'docfile' });
      const showDoc = () => {
        status.replaceChildren(S.docs[n] ? el('a', { href: S.docs[n], target: '_blank', textContent: '✔ 등록됨 · 보기' }) : el('span', { className: 'muted', textContent: '미등록' }));
        if (S.docs[n]) {
          const rm = el('button', { type: 'button', className: 'ghost tiny', textContent: '삭제' });
          rm.addEventListener('click', () => { delete S.docs[n]; showDoc(); dirty(); });
          status.append(' ', rm);
        }
      };
      const file = el('input', { type: 'file', hidden: true, accept: '.pdf,.hwp,.doc,.docx,.txt,.png,.jpg,.jpeg' });
      file.addEventListener('change', async () => {
        const f = file.files[0];
        if (!f) return;
        status.textContent = '올리는 중…';
        try { S.docs[n] = await upload(f, 'doc'); dirty(); showDoc(); } catch (err) { status.textContent = '⚠ ' + err.message; }
        file.value = '';
      });
      showDoc();
      return el('div', { className: 'docrow' },
        el('span', { className: 'docname' }, n, ' ', el('b', { className: req ? 'req' : 'muted', textContent: req ? '필수' : (DOC_LABEL[d.required] || '조건에 따라 필수') })),
        el('label', { className: 'btn-like sm', textContent: '파일 등록' }, file), status);
    }));
  }
  onRadio('parallel_imported', renderDocs);

  // ================= 배송 =================
  const syncCharge = () => document.querySelectorAll('[data-charge]').forEach((l) => { l.hidden = !l.dataset.charge.split(' ').includes(val('delivery_charge_type')); });
  onRadio('delivery_charge_type', syncCharge);
  const syncMethod = () => {
    show($('extra-msg-wrap'), val('delivery_method') === 'MAKE_ORDER');
    show($('agent-note'), val('delivery_method') === 'AGENT_BUY');
    renderDocs();
  };
  onRadio('delivery_method', syncMethod);

  // ================= 출고지 / 반품지 =================
  const outSel = $('outbound'), retSel = $('return-center');
  let returns = [];
  function fillPlaces(sel, list, cur, extra) {
    const opts = list.map((p) => el('option', { value: p.code, textContent: `${p.name} · ${p.address}${p.usable === false ? ' (사용 안 함)' : ''}`, disabled: p.usable === false }));
    if (cur && cur !== NO_RETURN && !list.some((p) => p.code === cur)) opts.unshift(el('option', { value: cur, textContent: `코드 ${cur} (WING 목록에 없음)` }));
    const head = el('option', { value: '', textContent: list.length ? '선택하세요' : '등록된 주소가 없습니다 — WING > 판매자정보 > 주소록에서 먼저 등록' });
    sel.replaceChildren(head, ...opts, ...(extra || []));
    sel.value = cur || (list.filter((p) => p.usable !== false).length === 1 ? list.find((p) => p.usable !== false).code : '');
  }
  async function loadPlaces(refresh = false) {
    $('outbound-info').textContent = $('return-info').textContent = '불러오는 중…';
    let data;
    try { data = await (await fetch('/api/shipping-places' + (refresh ? '?refresh=1' : ''))).json(); } catch (err) { data = { outbound: [], returns: [], errors: [err.message] }; }
    returns = data.returns;
    fillPlaces(outSel, data.outbound, outSel.value || outSel.dataset.value);
    fillPlaces(retSel, data.returns, retSel.value || retSel.dataset.value, [el('option', { value: NO_RETURN, textContent: '직접 입력', hidden: true })]);
    const err = (data.errors || []).join(' / ');
    $('outbound-info').textContent = err || (data.outbound.length ? `출고지 ${data.outbound.length}곳` : '');
    syncReturnMode();
    if (err) $('return-info').textContent = err;
    refreshSummary();
  }
  setRadio('return_mode', retSel.dataset.value === NO_RETURN ? 'direct' : 'book');
  function syncReturnMode() {
    const direct = val('return_mode') === 'direct';
    if (direct) retSel.value = NO_RETURN;
    else if (retSel.value === NO_RETURN) {
      const usable = returns.filter((p) => p.usable !== false);
      retSel.value = usable.length === 1 ? usable[0].code : '';
    }
    show($('return-book'), !direct); show($('return-manual'), direct);
    syncReturn();
  }
  function syncReturn() {
    const c = returns.find((r) => r.code === retSel.value);
    if (c) {  // 쿠팡 요청 본문에도 반품지 주소·연락처가 필요해서 고른 반품지 정보로 채운다
      const set = (k, v) => { if (v) form.elements[k].value = v; };
      set('return_name', c.name); set('return_phone', c.phone); set('return_zip', c.zip); set('return_addr', c.addr); set('return_addr_detail', c.addr_detail);
    }
    $('return-info').textContent = c ? `${c.address} · ${c.phone || ''}` : '';
  }
  onRadio('return_mode', syncReturnMode);
  retSel.addEventListener('change', syncReturn);
  outSel.addEventListener('change', () => {
    const o = [...outSel.options].find((x) => x.value === outSel.value);
    $('outbound-info').textContent = o && o.value ? o.textContent : '';
  });
  document.querySelectorAll('[data-reload-places]').forEach((b) => b.addEventListener('click', () => loadPlaces(true)));

  // ================= 추가이미지 / 상세설명 이미지 =================
  function imageList(box, list, horizontal, rerender) {
    box.replaceChildren(...list.map((url, i) => {
      const btn = (txt, title, fn, dis) => {
        const b = el('button', { type: 'button', className: 'ghost tiny', textContent: txt, title, disabled: dis });
        b.addEventListener('click', () => { fn(); rerender(); dirty(); });
        return b;
      };
      const swap = (j) => { [list[i], list[j]] = [list[j], list[i]]; };
      const [back, fwd] = horizontal ? ['◀', '▶'] : ['▲', '▼'];
      return el(horizontal ? 'figure' : 'li', {}, el('img', { src: url, alt: '' }), el(horizontal ? 'figcaption' : 'div', { className: 'imgbtns' },
        btn(back, '앞으로', () => swap(i - 1), i === 0), btn('✕', '삭제', () => list.splice(i, 1)),
        btn(fwd, '뒤로', () => swap(i + 1), i === list.length - 1)));
    }));
  }
  function renderGallery() {
    imageList($('gallery'), S.detail_images, true, renderGallery);
    $('gal-file').closest('label').hidden = S.detail_images.length >= MAX_GALLERY;
  }
  $('gal-file').addEventListener('change', async (e) => {
    for (const f of [...e.target.files].slice(0, MAX_GALLERY - S.detail_images.length)) {
      try { S.detail_images.push(await upload(f)); } catch (err) { alert(err.message); }
    }
    e.target.value = ''; renderGallery(); dirty();
  });
  const renderContent = () => imageList($('content-list'), S.content_images, false, renderContent);
  $('content-file').addEventListener('change', async (e) => {
    for (const f of [...e.target.files]) {
      try { S.content_images.push(await upload(f)); } catch (err) { alert(err.message); }
    }
    e.target.value = ''; renderContent(); dirty();
  });

  // 상세설명: 이미지 업로드 / 에디터 작성 / HTML 작성 (HTML 전환은 editor.js 의 소스 보기 버튼을 그대로 쓴다)
  const modeInput = $('detail-mode'), srcBtn = $('tb-src'), srcBox = $('desc-src');
  function setDetailMode(mode) {
    modeInput.value = mode;
    $('detail-tabs').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.mode === mode));
    show($('detail-images'), mode === 'images');
    show($('detail-editor'), mode !== 'images');
    const inSource = !srcBox.hidden;
    if ((mode === 'html') !== inSource && mode !== 'images') srcBtn.click();
    $('detail-editor').classList.toggle('htmlmode', mode === 'html');
  }
  $('detail-tabs').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { setDetailMode(b.dataset.mode); dirty(); }));

  // ================= 로켓그로스 =================
  function syncRocket() {  // 함수 선언: 카테고리 정보가 늦게 와도(renderMeta) 부를 수 있게
    show($('rg-now'), val('rg_inbound') === 'now');
    show($('rg-barcode-auto'), val('rg_barcode_mode') !== 'own');
    show($('rg-barcode-own'), val('rg_barcode_mode') === 'own');
    const need = !!meta?.isExpirationDateRequiredForRocketGrowth;
    $('rg-expiry-row').querySelector('.wlabel').classList.toggle('req', need);
    $('rg-expiry-note').textContent = need ? '이 카테고리는 소비기한이 필수입니다' : '소비기한이 없는 상품은 0';
    renderTable();
  }
  onRadio('rg_inbound', syncRocket); onRadio('rg_barcode_mode', syncRocket);

  // ================= 저장 =================
  form.addEventListener('submit', () => {
    if (optMode === 'multi' && types.some((t) => t.name) && types.filter((t) => t.name).map((t) => t.name).join() !== S.option_types.join()) buildOptions();
    if (tagInput.value.trim()) addTags(tagInput.value);
    if (rocketOn() && val('rg_inbound') === 'now' && !val('rg_inbound_name')) form.elements.rg_inbound_name.value = val('display_name');
    if (val('maxbuy_mode') === 'off') form.elements.max_per_person.value = '0';
    if (val('period_mode') === 'off') { form.elements.sale_start.value = ''; form.elements.sale_end.value = '2099-01-01T23:59'; }
    const keep = S.options.filter((o) => Object.values(o.values).some(Boolean) || o.name || o.sale_price || o.original_price || o.stock);
    const data = { ...S, options: keep.length ? keep : [] };
    Object.keys(data).forEach((k) => { const h = $('j-' + k); if (h) h.value = JSON.stringify(data[k]); });
  });

  // ================= 단계별 작성 =================
  const steps = [...document.querySelectorAll('fieldset.sec')];
  const stepBtns = [...document.querySelectorAll('#stepper [data-go]')];
  const subs = [...document.querySelectorAll('#s-main .substep')];
  const subBtns = [...document.querySelectorAll('#substeps [data-sub]')];
  const curInput = $('cur-step');
  const resume = form.dataset.resume === '1';
  let cur = Math.max(0, steps.findIndex((s) => s.id === curInput.value));
  const visited = new Set(resume ? steps.map((_, k) => k) : [cur]);  // 한 번 열어 본 단계 → 완료/미완료 표시
  let sub = 0;
  const optionLabel = (o) => S.option_types.map((t) => String(o.values[t] || '').trim()).filter(Boolean).join(' ') || String(o.name || '').trim();

  // '다음'을 누를 때 그 단계에서 꼭 필요한 것만 확인한다 (전체 검증은 등록할 때 서버가 한 번 더)
  const CHECK = {
    's-name': () => [!val('display_name') && '노출상품명을 입력하세요'],
    's-cat': () => [!$('cat-code').value && '카테고리를 마지막 단계까지 선택하세요'],
    's-option': () => {
      const out = [];
      if (optMode === 'multi') {
        if (!S.option_types.length && S.options.length < 2 && types.some((t) => t.name)) out.push("옵션명과 옵션값을 입력하고 '옵션목록으로 적용'을 누르세요");
        else if (types.filter((t) => t.name).map((t) => t.name).join() !== S.option_types.join()) out.push("옵션명을 바꿨어요. '옵션목록으로 적용'을 다시 누르세요");
      }
      S.options.forEach((o, i) => {
        const label = optionLabel(o) || (optMode === 'single' ? '단일 상품' : `${i + 1}번째 옵션`);
        S.option_types.forEach((t) => { if (!String(o.values[t] || '').trim()) out.push(`${label}: '${t}' 옵션값을 입력하세요`); });
        if (!isNum(o.sale_price) || money(o.sale_price) <= 0) out.push(`${label}: 판매가를 입력하세요`);
        else if (money(o.sale_price) % 10) out.push(`${label}: 판매가는 10원 단위로 입력하세요`);
        if (o.original_price && isNum(o.original_price) && money(o.original_price) < money(o.sale_price)) out.push(`${label}: 정상가는 판매가보다 작을 수 없습니다`);
      });
      (meta?.attributes || []).filter((a) => a.required === 'MANDATORY' && (a.groupNumber || 'NONE') === 'NONE'
        && !S.option_types.includes(a.attributeTypeName) && !String(S.fixed_attrs[a.attributeTypeName] || '').trim())
        .forEach((a) => out.push(`필수 구매옵션 '${a.attributeTypeName}'을(를) 옵션명으로 쓰거나 '구매옵션'에 입력하세요`));
      return out;
    },
    's-image': () => [!val('image_url') && '대표이미지를 등록하세요'],
    's-detail': () => [val('detail_mode') === 'images' && !S.content_images.length && '상세설명 이미지를 등록하거나 에디터로 작성하세요'],
    's-notice': () => [(meta?.noticeCategories || []).length > 1 && !noticeSel.value && '상품군을 선택하세요'],
    's-ship': () => [!outSel.value && '출고지를 선택하세요 (WING 판매자 주소록에 출고지가 없으면 먼저 등록해야 합니다)',
      val('delivery_charge_type') !== 'FREE' && !(money(val('delivery_charge')) > 0) && '기본 배송비를 입력하세요',
      val('delivery_charge_type') === 'CONDITIONAL_FREE' && (money(val('free_ship_over')) < 100 || money(val('free_ship_over')) % 100) && '무료배송 기준 금액을 100원 단위로 입력하세요',
      (!isNum(val('outbound_days')) || money(val('outbound_days')) < 1) && '출고 소요일을 1일 이상으로 입력하세요'],
    's-return': () => [!retSel.value && '반품/교환지를 선택하세요',
      ...(val('return_mode') === 'direct' ? [['return_name', '반품지명'], ['return_phone', '연락처'], ['return_zip', '우편번호'], ['return_addr', '주소'], ['return_addr_detail', '상세주소']]
        .map(([n, l]) => !val(n) && `${l}을(를) 입력하세요`) : []),
      ...['delivery_charge_on_return', 'return_charge'].map((n) => !isNum(val(n)) && '반품 배송비는 숫자로 입력하세요')],
    's-docs': () => requiredDocs().filter((n) => !S.docs[n]).map((n) => `구비서류 '${n}'을(를) 등록하세요`),
    's-rg': () => {
      const out = [!form.elements.rg_agree.checked && '로켓그로스 상품 검수 기준에 동의해야 합니다'];
      if (val('rg_barcode_mode') === 'own') {
        S.options.forEach((o, i) => {
          const b = String(o.barcode || '').trim(), label = optionLabel(o) || `${i + 1}번째 옵션`;
          if (!b) out.push(`'${label}' 바코드를 옵션 단계에 입력하거나 '쿠팡 바코드 사용'을 고르세요`);
          else if (!/^[A-Z0-9-]+$/.test(b) || ![8, 12, 13, 14, 18].includes(b.replace(/-/g, '').length)) out.push(`'${label}' 바코드는 8·12·13·14·18자리 영문 대문자·숫자여야 합니다`);
        });
      }
      if (val('rg_inbound') === 'now') {
        [['rg_width', '가로'], ['rg_length', '세로'], ['rg_height', '높이'], ['rg_weight', '무게'], ['rg_net_weight', '순중량']]
          .forEach(([n, l]) => { if (!(money(val(n)) > 0)) out.push(`${l} 값을 1 이상의 숫자로 입력하세요`); });
        if (money(val('rg_net_weight')) > money(val('rg_weight')) && money(val('rg_weight')) > 0) out.push('순중량은 무게보다 클 수 없습니다');
        if (!isNum(val('rg_expiry_days') || '0')) out.push('소비기한은 숫자로 입력하세요');
        else if (meta?.isExpirationDateRequiredForRocketGrowth && !(money(val('rg_expiry_days')) > 0)) out.push('이 카테고리는 소비기한(일)이 필수입니다');
      }
      return out;
    },
    's-confirm': () => [!val('vendor_user_id') && 'WING 아이디를 입력하세요'],
  };
  // 판매방식에 따라 쓰는 단계: 배송·반품/교환 = 판매자배송, 로켓그로스 입고 정보 = 로켓그로스
  const STEP_NEEDS = { 's-ship': sellOn, 's-return': sellOn, 's-rg': rocketOn };
  const active = (k) => (STEP_NEEDS[steps[k].id] || (() => true))();
  const nextActive = (k, dir) => { let j = k + dir; while (j >= 0 && j < steps.length && !active(j)) j += dir; return j; };
  function syncSteps() {
    let n = 0;
    stepBtns.forEach((b, k) => {
      const on = active(k);
      b.closest('li').hidden = !on;
      if (on) { n += 1; b.querySelector('b').textContent = n; b.title = `${n}. ${b.querySelector('span').textContent}`; }
    });
    if (!active(cur)) showStep(Math.max(0, nextActive(cur, -1)));
    else { updateButtons(); paintSteps(); }
  }
  const SUBCHECK = [
    () => [!brandNone.checked && !val('brand') && "브랜드를 입력하거나 '브랜드 없음'을 체크하세요"],
    () => {
      if (certMode() !== 'target') return [];
      const c = (meta?.certifications || []).find((x) => x.certificationType === certSel.value);
      return [!c && '인증 종류를 선택하세요', c && c.dataType === 'CODE' && !val('certification_code') && '인증번호를 입력하세요'];
    },
    () => [],
    () => [val('maxbuy_mode') === 'on' && (!(money(val('max_per_person')) > 0) || !(money(val('max_per_person_period')) > 0)) && '인당 최대구매수량과 기간을 1 이상으로 입력하세요',
      val('period_mode') === 'on' && val('sale_end') && val('sale_start') && val('sale_end') <= val('sale_start') && '판매 종료일은 시작일보다 뒤여야 합니다'],
  ];

  function stepMsg(errs, scroll = true) {
    const box = steps[cur].querySelector('.stepmsg') || steps[cur].appendChild(el('div', { className: 'stepmsg', role: 'alert' }));
    const list = [...new Set(errs)];
    box.replaceChildren(...(list.length ? [el('b', { textContent: '다음으로 가기 전에 확인하세요' }),
      el('ul', {}, ...list.slice(0, 8).map((e) => el('li', { textContent: e })))] : []));
    box.hidden = !list.length;
    if (list.length && scroll) box.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  const currentErrors = () => (steps[cur].id === 's-main' ? SUBCHECK[sub]() : (CHECK[steps[cur].id]?.() || [])).filter(Boolean);
  function refreshMsg() {  // 안내가 떠 있으면 고친 항목은 바로 지운다
    const box = steps[cur].querySelector('.stepmsg');
    if (box && !box.hidden) stepMsg(currentErrors(), false);
  }
  function jumpTop() {
    const side = document.querySelector('.side');
    const offset = side && getComputedStyle(side).position === 'sticky' ? side.offsetHeight : 0;
    scrollTo({ top: $('stepper').getBoundingClientRect().top + scrollY - offset - 8, behavior: 'smooth' });
  }
  const subOk = (k) => !SUBCHECK[k]().filter(Boolean).length;
  function showSub(i) {
    sub = i;
    subs.forEach((d, k) => d.classList.toggle('cur', k === i));
    subBtns.forEach((b, k) => { b.classList.toggle('on', k === i); b.classList.toggle('done', k !== i && subOk(k)); });
    updateButtons();
  }
  function showStep(i, s = 0) {
    cur = i; visited.add(i);
    steps.forEach((f, k) => f.classList.toggle('cur', k === i));
    paintSteps();
    curInput.value = steps[i].id;
    if (steps[i].id === 's-main') showSub(s);
    if (steps[i].id === 's-confirm') renderSummary();
    const on = steps.map((_, k) => k).filter(active);
    $('step-progress').style.width = `${((on.indexOf(i) + 1) / on.length) * 100}%`;
    const box = steps[i].querySelector('.stepmsg'); if (box) box.hidden = true;
    stepBtns[i].scrollIntoView({ block: 'nearest', inline: 'center' });
    updateButtons();
  }
  function updateButtons() {
    const last = cur === steps.length - 1, inMain = steps[cur].id === 's-main';
    $('btn-prev').disabled = nextActive(cur, -1) < 0;
    $('btn-next').hidden = last;
    $('btn-next').textContent = inMain && sub < subs.length - 1 ? `다음 (${sub + 1}/${subs.length}) →` : '다음 →';
    ['btn-preview', 'btn-save', 'btn-submit'].forEach((id) => { $(id).hidden = !last; });
  }
  function checkCurrent() {
    const id = steps[cur].id;
    const errs = currentErrors();
    stepMsg(errs);
    if (!errs.length && id !== 's-main') stepBtns[cur].classList.remove('err');
    return !errs.length;
  }
  function next() {
    if (!checkCurrent()) return;
    if (steps[cur].id === 's-main' && sub < subs.length - 1) { showSub(sub + 1); jumpTop(); return; }
    stepBtns[cur].classList.remove('err');
    showStep(nextActive(cur, 1)); jumpTop();
  }
  function prev() {
    if (steps[cur].id === 's-main' && sub > 0) { showSub(sub - 1); jumpTop(); return; }
    const p = nextActive(cur, -1);
    if (p >= 0) { showStep(p, steps[p].id === 's-main' ? subs.length - 1 : 0); jumpTop(); }
  }
  function stepOk(k) {
    const id = steps[k].id;
    if (!active(k)) return true;
    if (id === 's-confirm') return !CHECK['s-confirm']().filter(Boolean).length && steps.every((_, j) => j === k || stepOk(j));
    if ((id === 's-notice' || id === 's-docs' || id === 's-filter') && !meta) return false;  // 카테고리를 골라야 알 수 있음
    if (id === 's-main') return SUBCHECK.every((_, j) => subOk(j));
    return !(CHECK[id]?.() || []).filter(Boolean).length;
  }
  // 번호 색: 지금(주황) · 열어 봤고 다 채움(검정 ✓) · 열어 봤는데 빠진 것 있음(주황 테두리) · 아직 안 봄(회색)
  function paintSteps() {
    stepBtns.forEach((b, k) => {
      const seen = visited.has(k) && k !== cur, ok = seen && stepOk(k);
      b.classList.toggle('on', k === cur);
      b.classList.toggle('done', ok);
      b.classList.toggle('todo', seen && !ok);
      if (ok) b.classList.remove('err');
    });
  }
  let paintTimer;
  const repaint = () => { clearTimeout(paintTimer); paintTimer = setTimeout(() => { paintSteps(); refreshMsg(); }, 250); };
  form.addEventListener('input', repaint);
  form.addEventListener('change', repaint);
  const go = (i, s = 0) => { showStep(i, s); jumpTop(); };  // 번호를 누르면 확인 없이 그 단계로
  $('btn-next').addEventListener('click', next);
  $('btn-prev').addEventListener('click', prev);
  stepBtns.forEach((b, k) => b.addEventListener('click', () => go(k)));
  subBtns.forEach((b, k) => b.addEventListener('click', () => { showSub(k); stepMsg([]); }));
  // 입력칸에서 Enter = 다음 (실수로 저장·판매요청이 눌리지 않게)
  form.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || e.target.tagName !== 'INPUT' || ['checkbox', 'radio', 'file', 'submit'].includes(e.target.type)) return;
    if (e.target.id === 'cat-search' || e.target.id === 'tag-input') return;  // 각자 Enter 동작이 있음
    e.preventDefault();
    if (!e.target.closest('.optype, .bulkset, #opt-table') && !$('btn-next').hidden) next();
  });

  // ================= 판매요청 단계 요약 =================
  function renderSummary() {
    const prices = S.options.map((o) => money(o.sale_price)).filter((x) => x > 0);
    const won = (x) => `${x.toLocaleString('ko-KR')}원`;
    const lo = Math.min(...prices), hi = Math.max(...prices);
    const detail = { images: `이미지 ${S.content_images.length}장`, html: 'HTML 작성' }[val('detail_mode')]
      || ($('editor').textContent.trim() || $('editor').querySelector('img') ? '에디터 작성' : '');
    const rows = [
      ['판매방식', [sellOn() && '판매자배송', rocketOn() && '로켓그로스'].filter(Boolean).join(' + '), 's-name'],
      ['노출상품명', val('display_name'), 's-name'], ['등록상품명', val('name') || '(노출상품명과 같음)', 's-name'],
      ['카테고리', $('cat-selected').textContent.trim(), 's-cat'],
      ['옵션', (optMode === 'single' ? '단일 상품' : `옵션 ${S.options.length}개`) + (prices.length ? ` · ${won(lo)}${hi !== lo ? ` ~ ${won(hi)}` : ''}` : '') +
        ` · 재고 ${S.options.reduce((a, o) => a + (money(o.stock) || 0), 0)}개`, 's-option'],
      ['상품이미지', val('image_url') ? `대표 1장 + 추가 ${S.detail_images.length}장` : '', 's-image'],
      ['상세설명', detail, 's-detail'],
      ['상품 주요정보', [brandNone.checked ? '브랜드 없음' : val('brand'), choiceText('cert_mode'), choiceText('parallel_imported'),
        `미성년자 구매 ${choiceText('adult_only')}`, choiceText('tax_type')].filter(Boolean).join(' · '), 's-main'],
      ['검색어', tags.length ? `${tags.length}개 · ${tags.slice(0, 5).join(', ')}${tags.length > 5 ? ' …' : ''}` : '없음', 's-keyword'],
      ['상품정보제공고시', noticeSel.value, 's-notice'],
      ['배송', `${choiceText('delivery_method')} · ${choiceText('delivery_company')} · ${choiceText('delivery_charge_type')}` +
        (val('delivery_charge_type') !== 'FREE' ? ` ${won(money(val('delivery_charge')))}` : '') + ` · 출고 ${val('outbound_days')}일`, 's-ship'],
      ['출고지', !sellOn() ? '(로켓그로스: 쿠팡 배송)' : (outSel.value ? choiceText('outbound_place_code') : ''), 's-ship'],
      ['반품/교환지', val('return_mode') === 'direct' ? `직접 입력: ${val('return_zip')} ${val('return_addr')} ${val('return_addr_detail')}`.trim() : (retSel.value ? choiceText('return_center_code') : ''), 's-return'],
      ['구비서류', Object.keys(S.docs).filter((k) => S.docs[k]).join(', ') || '없음', 's-docs'],
      ...(rocketOn() ? [['로켓그로스', [val('rg_barcode_mode') === 'own' ? '내 바코드' : '쿠팡 바코드',
        val('rg_inbound') === 'now' ? `입고 정보 ${val('rg_width')}×${val('rg_length')}×${val('rg_height')}mm · ${val('rg_weight')}g` : '입고 정보 나중에',
        form.elements.rg_agree.checked ? '검수 기준 동의함' : ''].filter(Boolean).join(' · ') + (form.elements.rg_agree.checked ? '' : ' (동의 필요)'), 's-rg']] : []),
    ];
    const usable = rows.filter(([, , sid]) => active(steps.findIndex((f) => f.id === sid)));
    $('summary').replaceChildren(...usable.flatMap(([k, v, sid]) => {
      const edit = el('button', { type: 'button', className: 'ghost tiny', textContent: '수정' });
      edit.addEventListener('click', () => go(steps.findIndex((f) => f.id === sid)));
      return [el('dt', { textContent: k }), el('dd', { textContent: v || '⚠ 입력 안 됨', className: v ? '' : 'missing' }), el('dd', { className: 'act' }, edit)];
    }));
  }

  // ================= 시작 =================
  const code = $('cat-code');
  code.addEventListener('input', () => loadMeta(code.value));
  setOptMode(optMode); renderGallery(); renderContent(); renderTags(); syncBrand();
  syncCharge(); syncMethod(); syncLimits(); renderOffer(); renderCerts();
  setDetailMode(modeInput.value || 'editor');
  ['sell_seller', 'sell_rocket'].forEach((n) => form.elements[n].addEventListener('change', (e) => {
    if (!sellOn() && !rocketOn()) e.target.checked = true;  // 판매방식은 하나 이상
    syncRocket(); syncSteps(); dirty();
  }));
  form.classList.add('wiz-on');
  if (!active(cur)) cur = Math.max(0, nextActive(cur, -1));
  showStep(cur, Number(form.dataset.sub) || 0);
  syncSteps(); syncRocket();
  loadMeta(code.value); loadPlaces();
})();
