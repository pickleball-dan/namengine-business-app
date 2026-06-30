(function () {
  const STORAGE_KEY = 'namengineBusinessLovedNames';
  const MAX_ITEMS = 8;

  const canStore = () => {
    try {
      const probe = '__namengine_business_probe__';
      window.localStorage.setItem(probe, probe);
      window.localStorage.removeItem(probe);
      return true;
    } catch (error) {
      return false;
    }
  };

  const readHistory = () => {
    if (!canStore()) {
      return [];
    }
    try {
      const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  };

  const writeHistory = (items) => {
    if (!canStore()) {
      return;
    }
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_ITEMS)));
    } catch (error) {
      // Storage can be full or blocked; history should never interrupt naming.
    }
  };

  const absoluteShareUrl = (path) => new URL(path || window.location.href, window.location.origin).toString();

  const buildQuery = (values) => {
    const params = new URLSearchParams();
    const internalFields = new Set(['shortlist_id', 'previous_names', 'tune_history']);
    Object.entries(values || {}).forEach(([key, value]) => {
      if (value && !internalFields.has(key)) {
        params.set(key, value);
      }
    });
    return params.toString();
  };

  const collectFormData = () => {
    const form = document.querySelector('.js-loading-form');
    if (!form) {
      return {};
    }
    const internalFields = new Set(['shortlist_id', 'previous_names', 'tune_history']);
    return Array.from(new FormData(form).entries()).reduce((values, [key, value]) => {
      if (!key.startsWith('reaction__') && !internalFields.has(key) && typeof value === 'string') {
        values[key] = value;
      }
      return values;
    }, {});
  };

  const resumeUrlFor = (item) => {
    const query = buildQuery(item.formData);
    if (!query) {
      return '';
    }
    const path = (item.mode || '').toLowerCase() === 'original' ? '/original' : '/';
    const hash = path === '/original' ? '#original-brief' : '#brief';
    return `${path}?${query}${hash}`;
  };

  const resultUrlFor = (item) => {
    const query = buildQuery(item.formData);
    if (!query) {
      return '';
    }
    const path = (item.mode || '').toLowerCase() === 'original' ? '/original/results' : '/results';
    return `${path}?${query}`;
  };

  const getResultIdentity = (options) => {
    const shareButton = document.querySelector('.js-share-trigger');
    const shareUrl = absoluteShareUrl(options.shareUrl || shareButton?.dataset.shareUrl);
    return {
      id: `${options.mode || 'List'}:${shareUrl}`,
      shareUrl,
    };
  };

  const collectLovedNames = (options) => {
    const cards = Array.from(document.querySelectorAll(options.cardSelector || '.name-card'));
    return cards
      .filter((card) => card.querySelector('input[name^="reaction__"]:checked')?.value === 'love')
      .map((card) => card.querySelector('h2')?.textContent.trim())
      .filter(Boolean)
      .slice(0, 8);
  };

  const saveLovedNames = (options = {}) => {
    const names = collectLovedNames(options);
    const { id, shareUrl } = getResultIdentity(options);
    const existing = readHistory().filter((item) => item.id !== id && item.shareUrl !== shareUrl);

    if (!names.length) {
      writeHistory(existing);
      return;
    }

    const nextItem = {
      id,
      mode: options.mode || 'List',
      title: names.slice(0, 3).join(', '),
      summary: options.summary || document.querySelector(options.summarySelector || '.summary-chip')?.textContent.trim() || '',
      names,
      formData: collectFormData(),
      shareUrl,
      createdAt: new Date().toISOString(),
    };

    writeHistory([nextItem, ...existing]);
  };

  const trackLovedNames = (options = {}) => {
    saveLovedNames(options);
    document.querySelectorAll('input[name^="reaction__"]').forEach((input) => {
      input.addEventListener('change', () => saveLovedNames(options));
    });
  };

  const formatTime = (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '';
    }
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  };

  const formatCount = (count) => `${count} saved ${count === 1 ? 'search' : 'searches'}`;

  const renderNameList = (list, names) => {
    list.innerHTML = '';
    names.forEach((name) => {
      const li = document.createElement('li');
      li.textContent = name;
      list.appendChild(li);
    });
  };

  const renderHistoryDialog = (container, items) => {
    const dialog = container.querySelector('.js-taste-history-dialog');
    const openButton = container.querySelector('.js-taste-history-open');
    const closeButton = container.querySelector('.js-taste-history-close');
    const summary = container.querySelector('.js-taste-history-summary');
    const list = container.querySelector('.js-taste-history-list');
    if (!dialog || !openButton || !closeButton || !summary || !list) {
      return;
    }

    summary.textContent = formatCount(items.length);
    openButton.hidden = !items.length;
    list.innerHTML = '';

    items.forEach((item) => {
      const li = document.createElement('li');
      const header = document.createElement('div');
      const title = document.createElement('strong');
      const meta = document.createElement('span');
      const names = document.createElement('p');
      const actions = document.createElement('div');
      const resumeUrl = resumeUrlFor(item);
      const resultUrl = resultUrlFor(item);

      header.className = 'taste-history-session-head';
      actions.className = 'taste-history-actions';
      title.textContent = item.summary || item.title || 'Saved taste';
      meta.textContent = [item.mode, formatTime(item.createdAt)].filter(Boolean).join(' - ');
      names.textContent = `Loved: ${item.names.join(', ')}`;
      header.append(title, meta);
      li.append(header, names);

      if (resumeUrl) {
        const resume = document.createElement('a');
        resume.href = resumeUrl;
        resume.textContent = 'Resume';
        actions.appendChild(resume);
      }

      const view = document.createElement('a');
      view.href = resultUrl || item.shareUrl || '#';
      view.textContent = 'View list';
      actions.appendChild(view);
      li.appendChild(actions);
      list.appendChild(li);
    });

    openButton.addEventListener('click', () => {
      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', '');
      }
    });
    closeButton.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) {
        dialog.close();
      }
    });
  };

  const renderLoved = (container) => {
    if (!container) {
      return;
    }

    const list = container.querySelector('.js-loved-names-list');
    if (!list) {
      return;
    }

    const items = readHistory().filter((item) => Array.isArray(item.names) && item.names.length);
    container.hidden = !items.length;
    if (!items.length) {
      return;
    }

    renderNameList(list, items[0].names);
    renderHistoryDialog(container, items);
  };

  window.NamEngineTasteHistory = {
    renderLoved,
    trackLovedNames,
  };
})();
