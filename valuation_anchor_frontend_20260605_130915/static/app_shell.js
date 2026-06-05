(function () {
    if (window.__reviewsDailyWorkspaceShellLoaded) return;
    window.__reviewsDailyWorkspaceShellLoaded = true;

    var TAB_KEY = 'reviewsdaily.workspaceTabs.v2';
    var LEGACY_TAB_KEY = 'reviewsdaily.workspaceTabs.v1';
    var NAV_KEY = 'reviewsdaily.workspaceNavCollapsed.v1';
    var NAV_SECTION_KEY = 'reviewsdaily.workspaceNavSections.v1';
    var MAX_TABS = 12;
    var FRAME_PARAM = '__rd_frame';
    var BRAND_NAME = '知行合一';
    var ROOT_PATH = normalizePath(window.location.href);
    var ROOT_TAB_PATH = ROOT_PATH;
    var activePath = ROOT_PATH;
    var AI_USAGE_CACHE_KEY = 'reviewsdaily.aiUsage.v1';
    var AI_USAGE_CACHE_TTL_MS = 5 * 60 * 1000;
    var TERM_POPOVER_HIDE_DELAY_MS = 1800;
    var TERM_CONTEXT_HIDE_DELAY_MS = 1200;
    var TERM_POPOVER_FADE_MS = 190;
    var TERM_CONTEXT_FADE_MS = 165;
    var TERM_SELECTION_DELAY_MS = 140;
    var TERM_SELECTION_DUPLICATE_MS = 260;
    var TERM_LIBRARY_INTENT_KEY = 'reviewsdaily.experienceLessons.intent.v1';
    var termLookupState = {
        popover: null,
        selectedText: '',
        contextText: '',
        selectionRect: null,
        loading: false,
        lastItem: null,
        hideTimer: 0,
        selectionTimer: 0,
        popoverFadeTimer: 0,
        contextHideTimer: 0,
        contextFadeTimer: 0,
        activeDoc: null,
        selectionKey: '',
        lookupRequestId: 0,
        lookupController: null,
        lastSelectionEventAt: 0,
        linkSelectionAnchor: null,
        linkSelectionUntil: 0,
        contextMenu: null,
        sourceTitle: '',
        sourceUrl: ''
    };

    function ready(fn) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', fn);
        } else {
            fn();
        }
    }

    function normalizePath(path) {
        var a = document.createElement('a');
        a.href = path || window.location.href;
        var params = new URLSearchParams(a.search || '');
        params.delete(FRAME_PARAM);
        var search = params.toString();
        return a.pathname + (search ? '?' + search : '');
    }

    function frameSrc(path) {
        var a = document.createElement('a');
        a.href = normalizePath(path);
        var params = new URLSearchParams(a.search || '');
        params.set(FRAME_PARAM, '1');
        return a.pathname + '?' + params.toString();
    }

    function basePath(path) {
        return String(path || '').split('#')[0].split('?')[0].replace(/\/+$/, '') || '/';
    }

    function normalizeTitleForBrand(title) {
        var raw = String(title || '').replace(/\s+/g, ' ').trim();
        raw = raw
            .replace(/\s*[·\-|]\s*ReviewsDaily\s*$/i, '')
            .replace(/\s*[·\-|]\s*知行合一\s*$/, '')
            .trim();
        return raw && raw !== BRAND_NAME ? raw + ' · ' + BRAND_NAME : BRAND_NAME;
    }

    function applyBrandTitle() {
        document.title = normalizeTitleForBrand(document.title);
    }

    function isAuthPath(path) {
        var clean = basePath(path);
        return clean === '/login' || clean === '/register' || clean === '/logout';
    }

    function leaveWorkspaceTo(path) {
        try {
            localStorage.removeItem(TAB_KEY);
            localStorage.removeItem(LEGACY_TAB_KEY);
        } catch (error) {}
        window.location.href = normalizePath(path || '/login');
    }

    function getTitleFromDocument() {
        var h1 = document.querySelector('h1');
        if (h1 && h1.textContent.trim()) {
            return h1.textContent.trim().replace(/\s+/g, ' ').slice(0, 26);
        }
        return (document.title || '当前页面').replace(/\s*[-|].*$/, '').trim() || '当前页面';
    }

    function readTabs() {
        try {
            var raw = localStorage.getItem(TAB_KEY) || localStorage.getItem(LEGACY_TAB_KEY) || '[]';
            var parsed = JSON.parse(raw);
            if (!Array.isArray(parsed)) return [];
            return dedupeTabs(parsed.filter(function (tab) {
                return tab && tab.path && tab.title;
            }).map(function (tab) {
                var originalPath = normalizePath(tab.path);
                var ownerPath = tabPathForPath(originalPath);
                if (!ownerPath) return null;
                tab.path = ownerPath;
                tab.innerPath = tab.innerPath ? normalizePath(tab.innerPath) : '';
                if (ownerPath !== originalPath && !tab.innerPath) {
                    tab.innerPath = originalPath;
                }
                if (ownerPath !== originalPath) {
                    var meta = tabMetaForPath(ownerPath, tab.title);
                    tab.title = meta.title || tab.title;
                    tab.icon = meta.icon || tab.icon;
                }
                if (tab.innerPath === tab.path) tab.innerPath = '';
                return tab;
            }).filter(Boolean));
        } catch (error) {
            return [];
        }
    }

    function writeTabs(tabs) {
        localStorage.setItem(TAB_KEY, JSON.stringify(tabs.slice(-MAX_TABS)));
    }

    function sameOriginHref(href) {
        try {
            var url = new URL(href, window.location.href);
            if (url.origin !== window.location.origin) return '';
            if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/static/')) return '';
            return normalizePath(url.pathname + url.search);
        } catch (error) {
            return '';
        }
    }

    function tabMetaForPath(path, fallbackTitle) {
        var clean = basePath(tabPathForPath(path) || path);
        var link = document.querySelector('.rd-nav-link[data-rd-nav-path="' + cssEscape(clean) + '"]');
        if (!link && clean.indexOf('/reports/reader/') === 0) {
            link = document.querySelector('.rd-nav-link[data-rd-nav-path="/reports/reader"]');
        }
        if (!link && clean.indexOf('/reports') === 0) {
            link = document.querySelector('.rd-nav-link[data-rd-nav-path="/reports"]');
        }
        if (link) {
            return {
                title: link.getAttribute('data-rd-tab-title') || link.textContent.trim() || fallbackTitle,
                icon: link.getAttribute('data-rd-tab-icon') || '•'
            };
        }
        return { title: fallbackTitle || '当前页面', icon: '•' };
    }

    function routeOwnerPath(path) {
        var clean = basePath(path);
        if (!clean || isAuthPath(clean)) return '';
        if (clean === '/data_query_builder') return '/data_query';
        var rules = [
            { re: /^\/daily\/market\b/, owner: '/daily/market' },
            { re: /^\/daily\/ai\b/, owner: '/daily/ai' },
            { re: /^\/daily\/export\b/, owner: '/daily/export' },
            { re: /^\/daily\b/, owner: '/daily' },
            { re: /^\/add_(essay|review)\b/, owner: '/daily' },
            { re: /^\/edit_review\//, owner: '/daily' },
            { re: /^\/(delete|save)_(essay|review)\b/, owner: '/daily' },
            { re: /^\/ai_generate\b/, owner: '/daily/ai' },
            { re: /^\/ai_research_assistant\b/, owner: '/ai_research_assistant' },
            { re: /^\/export_excel\b/, owner: '/daily/export' },
            { re: /^\/market_tone\/(set|save)\b/, owner: '/daily/market' },
            { re: /^\/index_trend\/(set|save)\b/, owner: '/daily/market' },
            { re: /^\/(upload|download)_report\b/, owner: '/reports' },
            { re: /^\/reports\/(view|add|edit|delete)\b/, owner: '/reports' },
            { re: /^\/reports\/reader\/\d+/, owner: '/reports/reader' },
            { re: /^\/reports\/workspace\b/, owner: '/reports/reader' },
            { re: /^\/reports\/pdf_file\//, owner: '/reports/reader' },
            { re: /^\/reports\/epub_reader\/\d+/, owner: '/reports/reader' },
            { re: /^\/epub_reader\b/, owner: '/epub_reader' },
            { re: /^\/trading_agents\/\d+/, owner: '/trading_agents' },
            { re: /^\/topics\/(add|edit|delete)\b/, owner: '/topics' },
            { re: /^\/plans\/(add|edit|delete)\b/, owner: '/plans' },
            { re: /^\/graph\b/, owner: '/plans' },
            { re: /^\/calendar\/(add|edit|delete)\b/, owner: '/calendar' },
            { re: /^\/concept_stocks\/(add|edit|delete)\b/, owner: '/concept_stocks' },
            { re: /^\/stock_analysis\b/, owner: '/data_center' },
            { re: /^\/screening_tasks\/result\//, owner: '/screening_tasks' },
            { re: /^\/admin\/ai-provider\/(status|save|test)\b/, owner: '/admin/ai-provider' },
            { re: /^\/crawler_dashboard\/wordcloud\b/, owner: '/crawler_dashboard/wordcloud' },
            { re: /^\/timeline\b/, owner: '/crawler_dashboard' }
        ];
        for (var i = 0; i < rules.length; i += 1) {
            if (rules[i].re.test(clean)) return rules[i].owner;
        }
        return '';
    }

    function primaryNavPath(path) {
        var clean = basePath(path);
        var link = document.querySelector('.rd-nav-link[data-rd-nav-path="' + cssEscape(clean) + '"]');
        return link ? clean : '';
    }

    function tabPathForPath(path) {
        var clean = basePath(path);
        var direct = primaryNavPath(clean);
        if (direct) return normalizePath(path);
        var owner = routeOwnerPath(clean);
        return owner && primaryNavPath(owner) ? owner : '';
    }

    function tabDefaultContentPath(path) {
        var clean = basePath(path);
        var link = document.querySelector('.rd-nav-link[data-rd-nav-path="' + cssEscape(clean) + '"]');
        if (!link) return normalizePath(path);
        return sameOriginHref(link.getAttribute('href') || '') || normalizePath(path);
    }

    function upsertTab(path, title, icon, innerPath) {
        path = normalizePath(path);
        innerPath = innerPath ? normalizePath(innerPath) : '';
        var tabs = readTabs();
        var existing = tabs.find(function (tab) { return tab.path === path; });
        if (existing) {
            existing.title = title || existing.title;
            existing.icon = icon || existing.icon || '•';
            if (innerPath !== undefined) {
                existing.innerPath = innerPath && innerPath !== path ? innerPath : '';
            }
            existing.last = Date.now();
        } else {
            tabs.push({ path: path, title: title || '当前页面', icon: icon || '•', innerPath: innerPath && innerPath !== path ? innerPath : '', last: Date.now() });
        }
        writeTabs(tabs);
        return tabs;
    }

    function removeFrame(path) {
        var frame = document.querySelector('.rd-tab-frame[data-rd-path="' + cssEscape(path) + '"]');
        if (frame) frame.remove();
    }

    function closeTab(path) {
        path = normalizePath(path);
        var tabs = readTabs();
        var index = tabs.findIndex(function (tab) { return tab.path === path; });
        if (index < 0) return;
        tabs.splice(index, 1);
        if (!tabs.length) {
            tabs = [{
                path: ROOT_TAB_PATH,
                title: getTitleFromDocument(),
                icon: tabMetaForPath(ROOT_TAB_PATH).icon,
                innerPath: ROOT_TAB_PATH !== ROOT_PATH ? ROOT_PATH : '',
                last: Date.now()
            }];
        }
        writeTabs(tabs);
        removeFrame(path);
        if (path === activePath) {
            var next = tabs[Math.max(0, index - 1)] || tabs[0];
            activateTab(next.path);
        } else {
            renderTabs();
        }
    }

    function rootTabSnapshot() {
        var meta = tabMetaForPath(ROOT_TAB_PATH, getTitleFromDocument());
        return {
            path: ROOT_TAB_PATH,
            title: meta.title || getTitleFromDocument(),
            icon: meta.icon || '•',
            innerPath: ROOT_TAB_PATH !== ROOT_PATH ? ROOT_PATH : '',
            last: Date.now()
        };
    }

    function reloadTab(path) {
        path = normalizePath(path);
        var tabs = readTabs();
        var tab = tabs.find(function (item) { return item.path === path; });
        if (!tab && path !== ROOT_TAB_PATH) return;
        if (path === ROOT_TAB_PATH) {
            activateTab(path);
            window.location.reload();
            return;
        }
        var frame = document.querySelector('.rd-tab-frame[data-rd-path="' + cssEscape(path) + '"]');
        if (!frame) {
            activateTab(path);
            return;
        }
        try {
            if (frame.contentWindow && frame.contentWindow.location) {
                frame.contentWindow.location.reload();
                return;
            }
        } catch (error) {}
        frame.src = frame.src;
    }

    function closeTabsByMode(mode) {
        mode = mode || 'others';
        var tabs = readTabs();
        if (!tabs.length) return;
        var activeIndex = tabs.findIndex(function (tab) { return tab.path === activePath; });
        if (activeIndex < 0) activeIndex = 0;
        var keepPaths = {};
        var nextActive = tabs[activeIndex] || tabs[0];

        if (mode === 'all') {
            nextActive = rootTabSnapshot();
            tabs = [nextActive];
        } else {
            tabs = tabs.filter(function (tab, index) {
                if (mode === 'others') return index === activeIndex;
                if (mode === 'left') return index >= activeIndex;
                if (mode === 'right') return index <= activeIndex;
                return true;
            });
            if (!tabs.length) {
                nextActive = rootTabSnapshot();
                tabs = [nextActive];
            } else {
                nextActive = tabs.find(function (tab) { return tab.path === activePath; }) || tabs[0];
            }
        }

        tabs = tabs.map(function (tab) {
            return {
                path: tab.path,
                title: tab.title,
                icon: tab.icon,
                innerPath: tab.innerPath || '',
                last: tab.path === nextActive.path ? Date.now() : (tab.last || Date.now())
            };
        });
        tabs.forEach(function (tab) { keepPaths[tab.path] = true; });
        writeTabs(tabs);
        document.querySelectorAll('.rd-tab-frame').forEach(function (frame) {
            if (!keepPaths[frame.dataset.rdPath]) frame.remove();
        });
        activateTab(nextActive.path, {
            skipUpsert: true,
            innerPath: nextActive.innerPath || '',
            forceDefault: mode === 'all'
        });
    }

    function ensureFrameHost() {
        var host = document.getElementById('rdFrameHost');
        if (host) return host;
        host = document.createElement('div');
        host.id = 'rdFrameHost';
        host.className = 'rd-frame-host';
        var shell = document.getElementById('rd-workspace-shell');
        if (shell && shell.parentNode) {
            shell.parentNode.insertBefore(host, shell.nextSibling);
        } else {
            document.body.appendChild(host);
        }
        return host;
    }

    function ensureFrame(path, tab) {
        path = normalizePath(path);
        var frame = document.querySelector('.rd-tab-frame[data-rd-path="' + cssEscape(path) + '"]');
        if (frame) return frame;
        frame = document.createElement('iframe');
        frame.className = 'rd-tab-frame';
        frame.dataset.rdPath = path;
        var targetPath = (tab && tab.innerPath) || tabDefaultContentPath(path);
        frame.dataset.rdInnerPath = normalizePath(targetPath);
        frame.title = (tab && tab.title) || tabMetaForPath(path).title || '页面';
        frame.loading = 'eager';
        frame.src = frameSrc(targetPath);
        frame.addEventListener('load', function () {
            handleFrameLoad(frame);
        });
        ensureFrameHost().appendChild(frame);
        return frame;
    }

    function handleFrameLoad(frame) {
        var frameWindow;
        var frameDocument;
        try {
            frameWindow = frame.contentWindow;
            frameDocument = frameWindow && frameWindow.document;
        } catch (error) {
            return;
        }
        if (!frameWindow || !frameDocument) return;

        var frameUrl;
        try {
            frameUrl = new URL(frameWindow.location.href);
        } catch (error) {
            return;
        }
        if (frameUrl.origin !== window.location.origin) return;

        var cleanPath = normalizePath(frameUrl.pathname + frameUrl.search);
        if (isAuthPath(cleanPath)) {
            leaveWorkspaceTo(cleanPath);
            return;
        }
        if (frameUrl.searchParams.get(FRAME_PARAM) !== '1') {
            frame.src = frameSrc(cleanPath);
            return;
        }

        bindThorShortcut(frameDocument);

        var oldPath = frame.dataset.rdPath;
        var nextPrimaryPath = tabPathForPath(cleanPath);
        if (!nextPrimaryPath) return;
        if (oldPath !== nextPrimaryPath) {
            frame.dataset.rdPath = nextPrimaryPath;
            frame.dataset.rdInnerPath = cleanPath;
            renameTabPath(oldPath, nextPrimaryPath, frameDocument, cleanPath);
            if (activePath === oldPath) {
                activePath = nextPrimaryPath;
                history.replaceState({ rdActiveTab: nextPrimaryPath }, '', nextPrimaryPath);
                updateActiveNav(nextPrimaryPath);
            }
            renderTabs();
        } else if (oldPath === cleanPath) {
            frame.dataset.rdInnerPath = '';
            updateTabTitle(cleanPath, frameDocument);
        } else {
            frame.dataset.rdInnerPath = cleanPath;
            var parentMeta = tabMetaForPath(oldPath, frame.title || '页面');
            updateStoredTab(oldPath, parentMeta.title, parentMeta.icon, cleanPath);
        }

        if (!frameDocument.__rdWorkspaceClickBound) {
            frameDocument.__rdWorkspaceClickBound = true;
            frameDocument.addEventListener('click', function (event) {
                var anchor = event.target.closest ? event.target.closest('a[href]') : null;
                if (handleFrameNavigation(frameWindow, anchor, event)) {
                    document.body.classList.remove('rd-mobile-nav-open');
                }
            }, true);
        }

        if (!frameDocument.__rdWorkspaceSubmitBound) {
            frameDocument.__rdWorkspaceSubmitBound = true;
            frameDocument.addEventListener('submit', function (event) {
                var form = event.target;
                if (!form || !form.tagName || form.tagName.toLowerCase() !== 'form') return;
                if ((form.target || '').toLowerCase() === '_blank') return;
                ensureFrameFormMode(form);
            }, true);
        }
        bindTermLookupSelection(frameDocument);
    }

    function renameTabPath(oldPath, newPath, frameDocument, innerPath) {
        var tabs = readTabs();
        var tab = tabs.find(function (item) { return item.path === oldPath; }) ||
            tabs.find(function (item) { return item.path === newPath; });
        var meta = tabMetaForPath(newPath, titleFromFrame(frameDocument));
        if (tab) {
            tab.path = newPath;
            tab.title = meta.title || tab.title;
            tab.icon = meta.icon || tab.icon || '•';
            tab.innerPath = innerPath && innerPath !== newPath ? normalizePath(innerPath) : '';
            tab.last = Date.now();
        } else {
            tabs.push({
                path: newPath,
                title: meta.title,
                icon: meta.icon,
                innerPath: innerPath && innerPath !== newPath ? normalizePath(innerPath) : '',
                last: Date.now()
            });
        }
        writeTabs(dedupeTabs(tabs));
    }

    function updateTabTitle(path, frameDocument) {
        var title = titleFromFrame(frameDocument);
        if (!title) return;
        var meta = tabMetaForPath(path, title);
        updateStoredTab(path, meta.title || title, meta.icon);
    }

    function updateStoredTab(path, title, icon, innerPath) {
        var tabs = readTabs();
        var tab = tabs.find(function (item) { return item.path === path; });
        if (!tab) return;
        tab.title = title || tab.title;
        tab.icon = icon || tab.icon || '•';
        if (innerPath !== undefined) {
            tab.innerPath = innerPath && innerPath !== path ? normalizePath(innerPath) : '';
        }
        writeTabs(tabs);
        renderTabs();
    }

    function titleFromFrame(frameDocument) {
        var h1 = frameDocument.querySelector('h1');
        if (h1 && h1.textContent.trim()) {
            return h1.textContent.trim().replace(/\s+/g, ' ').slice(0, 26);
        }
        return (frameDocument.title || '').replace(/\s*[-|].*$/, '').trim();
    }

    function dedupeTabs(tabs) {
        var byPath = {};
        tabs.forEach(function (tab) {
            if (!tab || !tab.path) return;
            var existing = byPath[tab.path];
            if (!existing || (tab.last || 0) >= (existing.last || 0)) {
                byPath[tab.path] = tab;
            }
        });
        return Object.keys(byPath).map(function (path) { return byPath[path]; });
    }

    function ensureFrameFormMode(form) {
        try {
            var method = (form.method || 'get').toLowerCase();
            var actionUrl = new URL(form.getAttribute('action') || form.ownerDocument.location.href, form.ownerDocument.location.href);
            if (actionUrl.origin !== window.location.origin) return;
            actionUrl.searchParams.set(FRAME_PARAM, '1');
            form.action = actionUrl.pathname + '?' + actionUrl.searchParams.toString();
            if (method === 'get') {
                return;
            }
            var hidden = form.querySelector('input[type="hidden"][name="' + FRAME_PARAM + '"]');
            if (!hidden) {
                hidden = form.ownerDocument.createElement('input');
                hidden.type = 'hidden';
                hidden.name = FRAME_PARAM;
                form.appendChild(hidden);
            }
            hidden.value = '1';
        } catch (error) {
            // Best-effort only; normal form behavior should still work.
        }
    }

    function isRootActive() {
        return activePath === ROOT_TAB_PATH;
    }

    function setRootVisible(visible) {
        document.body.classList.toggle('rd-root-tab-hidden', !visible);
    }

    function activateTab(path, options) {
        options = options || {};
        var requestedPath = normalizePath(path);
        path = tabPathForPath(requestedPath) || requestedPath;
        var requestedOwner = tabPathForPath(requestedPath);
        var innerPath = options.innerPath ? normalizePath(options.innerPath) :
            (requestedOwner && requestedOwner !== requestedPath ? requestedPath : '');
        var tabs = readTabs();
        var tab = tabs.find(function (item) { return item.path === path; });
        if (!tab) {
            var meta = tabMetaForPath(path, '当前页面');
            tab = { path: path, title: meta.title, icon: meta.icon, innerPath: innerPath, last: Date.now() };
            tabs.push(tab);
            writeTabs(tabs);
        } else if (innerPath !== undefined) {
            if (!innerPath && tab.innerPath && !options.forceDefault) {
                innerPath = normalizePath(tab.innerPath);
            }
            tab.innerPath = innerPath;
            tab.last = Date.now();
            writeTabs(tabs);
        }
        activePath = path;
        setRootVisible(isRootActive());
        document.querySelectorAll('.rd-tab-frame').forEach(function (frame) {
            frame.classList.toggle('active', frame.dataset.rdPath === path);
        });
        if (!options.skipUpsert) {
            upsertTab(path, tab.title, tab.icon, innerPath);
        }
        if (!isRootActive()) {
            var activeFrame = ensureFrame(path, tab);
            activeFrame.classList.add('active');
            if (innerPath !== undefined && innerPath && activeFrame.dataset.rdInnerPath !== innerPath) {
                activeFrame.dataset.rdInnerPath = innerPath;
                activeFrame.src = frameSrc(innerPath);
            } else if (innerPath === '' && options.forceDefault && activeFrame.dataset.rdInnerPath && activeFrame.dataset.rdInnerPath !== path) {
                var defaultPath = tabDefaultContentPath(path);
                activeFrame.dataset.rdInnerPath = defaultPath;
                activeFrame.src = frameSrc(defaultPath);
            }
        }
        if (!options.skipHistory && history.replaceState) {
            history.replaceState({ rdActiveTab: path }, '', path);
        }
        updateActiveNav(path);
        renderTabs();
    }

    function updateActiveNav(path) {
        var currentBase = basePath(path || activePath);
        document.querySelectorAll('.rd-nav-link[data-rd-nav-path]').forEach(function (link) {
            var linkPath = basePath(link.getAttribute('data-rd-nav-path'));
            var active = currentBase === linkPath || (linkPath !== '/' && currentBase.indexOf(linkPath + '/') === 0);
            link.classList.toggle('active', active);
        });
    }

    function renderTabs() {
        var tabsEl = document.getElementById('rdTabs');
        if (!tabsEl) return;
        var tabs = readTabs();
        tabsEl.innerHTML = tabs.map(function (tab) {
            var active = tab.path === activePath;
            return '<div class="rd-tab' + (active ? ' active' : '') + '" title="' + escapeHtml(tab.title) + '">' +
                '<button class="rd-tab-main" type="button" data-path="' + escapeHtml(tab.path) + '" title="单击打开，双击刷新">' +
                '<span class="rd-tab-icon">' + escapeHtml(tab.icon || '•') + '</span>' +
                '<span class="rd-tab-title">' + escapeHtml(tab.title) + '</span></button>' +
                '<button class="rd-tab-close" type="button" data-path="' + escapeHtml(tab.path) + '" aria-label="关闭">×</button>' +
                '</div>';
        }).join('');
        tabsEl.querySelectorAll('.rd-tab-main').forEach(function (btn) {
            btn.addEventListener('click', function () {
                activateTab(btn.getAttribute('data-path'));
            });
            btn.addEventListener('dblclick', function (event) {
                event.preventDefault();
                event.stopPropagation();
                reloadTab(btn.getAttribute('data-path'));
            });
        });
        tabsEl.querySelectorAll('.rd-tab-close').forEach(function (btn) {
            btn.addEventListener('click', function (event) {
                event.preventDefault();
                event.stopPropagation();
                closeTab(btn.getAttribute('data-path'));
            });
        });
        var activeTab = tabsEl.querySelector('.rd-tab.active');
        if (activeTab && activeTab.scrollIntoView) {
            activeTab.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }
    }

    function handleWorkspaceNavigation(anchor, event) {
        if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return false;
        var rawHref = anchor.getAttribute('href') || '';
        var path = sameOriginHref(rawHref);
        if (!path) return false;
        var method = (anchor.getAttribute('data-method') || anchor.dataset.rdMethod || '').toLowerCase();
        if (method && method !== 'get') return false;
        if (isAuthPath(path) || path.indexOf('/delete') >= 0) return false;
        if (anchor.dataset.rdNative === '1') return false;
        var tabPath = tabPathForPath(path);
        if (!tabPath) return false;
        if (isRootActive() && basePath(tabPath) === basePath(ROOT_TAB_PATH) && path !== normalizePath(window.location.href)) {
            // The root document is already the active tab, so same-owner links need a real page navigation.
            return false;
        }

        var title = anchor.getAttribute('data-rd-tab-title') ||
            (anchor.querySelector('.feature-title') && anchor.querySelector('.feature-title').textContent) ||
            (anchor.querySelector('.module-title') && anchor.querySelector('.module-title').textContent) ||
            anchor.textContent.trim();
        var icon = anchor.getAttribute('data-rd-tab-icon') ||
            (anchor.querySelector('.feature-icon') && anchor.querySelector('.feature-icon').textContent) ||
            (anchor.querySelector('.module-icon') && anchor.querySelector('.module-icon').textContent) ||
            tabMetaForPath(tabPath, title).icon;
        var meta = tabMetaForPath(tabPath, title);
        title = (meta.title || title || '当前页面').replace(/\s+/g, ' ').slice(0, 28);
        icon = (meta.icon || icon || '•').trim().slice(0, 2);
        upsertTab(tabPath, title, icon, tabPath !== path ? path : '');
        activateTab(tabPath, { skipUpsert: true, innerPath: tabPath !== path ? path : '' });
        event.preventDefault();
        event.stopPropagation();
        return true;
    }

    function handleFrameNavigation(frameWindow, anchor, event) {
        if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return false;
        var rawHref = anchor.getAttribute('href') || '';
        var path = sameOriginHref(rawHref);
        if (!path) return false;
        var method = (anchor.getAttribute('data-method') || anchor.dataset.rdMethod || '').toLowerCase();
        if (method && method !== 'get') return false;
        if (anchor.dataset.rdNative === '1') return false;
        if (isAuthPath(path)) {
            event.preventDefault();
            event.stopPropagation();
            leaveWorkspaceTo(path);
            return true;
        }
        if (path.indexOf('/delete') >= 0) return false;
        var tabPath = tabPathForPath(path);
        if (!tabPath) return false;
        var currentTabPath = tabPathForPath(activePath) || activePath;
        try {
            if (tabPath === currentTabPath) {
                frameWindow.location.href = frameSrc(path);
                updateStoredTab(tabPath, null, null, path);
            } else {
                activateTab(tabPath, { innerPath: tabPath !== path ? path : '' });
            }
            event.preventDefault();
            event.stopPropagation();
            return true;
        } catch (error) {
            return false;
        }
    }

    function escapeHtml(value) {
        return String(value || '').replace(/[&<>"']/g, function (ch) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
        });
    }

    function cssEscape(value) {
        if (window.CSS && CSS.escape) return CSS.escape(String(value));
        return String(value).replace(/["\\]/g, '\\$&');
    }

    function bindThorShortcut(doc) {
        if (window.__reviewsDailyBindThorShortcut) window.__reviewsDailyBindThorShortcut(doc);
    }

    function activeFrame() {
        return document.querySelector('.rd-tab-frame.active');
    }

    function csrfHeaders() {
        var headers = { 'Content-Type': 'application/json' };
        var meta = document.querySelector('meta[name="csrf-token"]');
        var token = meta ? (meta.getAttribute('content') || '') : '';
        if (token) headers['X-CSRF-Token'] = token;
        return headers;
    }

    function normalizeSelectedTerm(text) {
        text = String(text || '').replace(/\s+/g, ' ').trim();
        text = text.replace(/^[,，。；;：:\-—_《〈「『【\[\(（]+|[,，。；;：:\-—_》〉」』】\]\)）]+$/g, '');
        return text.slice(0, 80);
    }

    function selectionSourceForDoc(doc) {
        doc = doc || document;
        var view = doc.defaultView || window;
        var title = doc.title || document.title || '';
        var sourceUrl = '';
        try {
            sourceUrl = view.location.pathname + view.location.search;
        } catch (error) {
            sourceUrl = window.location.pathname + window.location.search;
        }
        return { sourceTitle: title, sourceUrl: sourceUrl };
    }

    function isTermTextControl(element) {
        if (!element || !element.tagName) return false;
        var tag = element.tagName.toLowerCase();
        if (tag === 'textarea') return true;
        if (tag !== 'input') return false;
        var type = String(element.type || 'text').toLowerCase();
        return ['text', 'search', 'url', 'tel', 'email', 'number'].indexOf(type) >= 0;
    }

    function getControlSelectionInfo(doc, target, point) {
        doc = doc || document;
        target = isTermTextControl(target) ? target : doc.activeElement;
        if (!isTermTextControl(target)) return null;
        var start = 0;
        var end = 0;
        try {
            start = target.selectionStart;
            end = target.selectionEnd;
        } catch (error) {
            return null;
        }
        if (typeof start !== 'number' || typeof end !== 'number' || start === end) return null;
        var raw = String(target.value || '').slice(Math.min(start, end), Math.max(start, end));
        var text = normalizeSelectedTerm(raw);
        if (!text || text.length < 2 || text.length > 80) return null;
        var rect;
        if (point && typeof point.clientX === 'number' && typeof point.clientY === 'number') {
            rect = { left: point.clientX, right: point.clientX, top: point.clientY, bottom: point.clientY, width: 0, height: 0 };
        } else {
            try {
                var box = target.getBoundingClientRect();
                rect = { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height };
            } catch (error) {}
        }
        if (!rect) return null;
        var source = selectionSourceForDoc(doc);
        return {
            text: text,
            context: String(target.value || '').replace(/\s+/g, ' ').trim().slice(0, 1800) || text,
            rect: rect,
            sourceTitle: source.sourceTitle,
            sourceUrl: source.sourceUrl
        };
    }

    function translateSelectionInfoFromDoc(info, doc) {
        if (!info || !doc || doc === document) return info;
        try {
            var view = doc.defaultView;
            var frame = view && view.frameElement;
            if (frame && info.rect) {
                var frameRect = frame.getBoundingClientRect();
                info.rect = {
                    left: info.rect.left + frameRect.left,
                    right: info.rect.right + frameRect.left,
                    top: info.rect.top + frameRect.top,
                    bottom: info.rect.bottom + frameRect.top,
                    width: info.rect.width,
                    height: info.rect.height
                };
            }
        } catch (error) {}
        return info;
    }

    function getSelectionInfo(doc, options) {
        doc = doc || document;
        options = options || {};
        var controlInfo = getControlSelectionInfo(doc, options.target, options);
        if (controlInfo) return controlInfo;
        var selection;
        try {
            selection = doc.getSelection ? doc.getSelection() : null;
        } catch (error) {
            return null;
        }
        if (!selection || selection.rangeCount <= 0 || selection.isCollapsed) return null;
        var text = normalizeSelectedTerm(selection.toString());
        if (!text || text.length < 2 || text.length > 80) return null;
        var range = selection.getRangeAt(0);
        var rect = null;
        try {
            rect = range.getBoundingClientRect();
        } catch (error) {}
        if ((!rect || (!rect.width && !rect.height)) && typeof options.clientX === 'number' && typeof options.clientY === 'number') {
            rect = { left: options.clientX, right: options.clientX, top: options.clientY, bottom: options.clientY, width: 0, height: 0 };
        }
        if (!rect || (!rect.width && !rect.height && typeof options.clientX !== 'number')) return null;
        var context = text;
        try {
            var container = range.commonAncestorContainer;
            var element = container && container.nodeType === 1 ? container : container.parentElement;
            var block = element && element.closest ? element.closest('p,li,td,th,article,section,main,.item,.monitor-alert,.card,.panel,.lesson-item,.rd-card,.module-card') : null;
            context = (block && block.textContent ? block.textContent : selection.toString()).replace(/\s+/g, ' ').trim().slice(0, 1800);
        } catch (error) {}
        var source = selectionSourceForDoc(doc);
        return { text: text, context: context || text, rect: rect, sourceTitle: source.sourceTitle, sourceUrl: source.sourceUrl };
    }

    function isTermSelectableLink(anchor) {
        if (!anchor || !anchor.matches) return false;
        return anchor.matches('a[href]');
    }

    function rememberLinkSelection(anchor) {
        termLookupState.linkSelectionAnchor = anchor || null;
        termLookupState.linkSelectionUntil = Date.now() + 900;
    }

    function selectionIntersectsElement(doc, element) {
        if (!doc || !element) return false;
        var selection;
        try {
            selection = doc.getSelection ? doc.getSelection() : null;
        } catch (error) {
            return false;
        }
        if (!selection || selection.rangeCount <= 0 || selection.isCollapsed) return false;
        for (var i = 0; i < selection.rangeCount; i += 1) {
            try {
                var range = selection.getRangeAt(i);
                if (range.intersectsNode && range.intersectsNode(element)) return true;
                var container = range.commonAncestorContainer;
                if (container && (container === element || (element.contains && element.contains(container)))) return true;
            } catch (error) {}
        }
        return false;
    }

    function shouldBlockLinkSelectionClick(anchor, doc) {
        if (!anchor || !isTermSelectableLink(anchor)) return false;
        if (!selectionIntersectsElement(doc || document, anchor)) return false;
        var info = getSelectionInfo(doc || document);
        if (!info) return false;
        if (termLookupState.linkSelectionAnchor && termLookupState.linkSelectionAnchor !== anchor && Date.now() > termLookupState.linkSelectionUntil) {
            termLookupState.linkSelectionAnchor = null;
        }
        rememberLinkSelection(anchor);
        return true;
    }

    function cancelTermContextHide() {
        window.clearTimeout(termLookupState.contextHideTimer);
        window.clearTimeout(termLookupState.contextFadeTimer);
        if (termLookupState.contextMenu && !termLookupState.contextMenu.hidden) {
            termLookupState.contextMenu.classList.remove('is-fading');
            termLookupState.contextMenu.classList.add('is-open');
        }
    }

    function scheduleTermContextHide(delay) {
        var menu = termLookupState.contextMenu;
        if (!menu || menu.hidden) return;
        window.clearTimeout(termLookupState.contextHideTimer);
        window.clearTimeout(termLookupState.contextFadeTimer);
        termLookupState.contextHideTimer = window.setTimeout(function () {
            if (menu.matches(':hover')) return;
            hideTermLookupContextMenu({ fade: true });
        }, delay == null ? TERM_CONTEXT_HIDE_DELAY_MS : delay);
    }

    function cancelTermPopoverHide() {
        window.clearTimeout(termLookupState.hideTimer);
        window.clearTimeout(termLookupState.popoverFadeTimer);
        if (termLookupState.popover && !termLookupState.popover.hidden) {
            termLookupState.popover.classList.remove('is-fading');
            termLookupState.popover.classList.add('is-open');
        }
    }

    function scheduleTermPopoverHide(delay) {
        var pop = termLookupState.popover;
        if (!pop || pop.hidden) return;
        window.clearTimeout(termLookupState.hideTimer);
        window.clearTimeout(termLookupState.popoverFadeTimer);
        termLookupState.hideTimer = window.setTimeout(function () {
            if (pop.matches(':hover')) return;
            hideTermLookupPopover({ fade: true });
        }, delay == null ? TERM_POPOVER_HIDE_DELAY_MS : delay);
    }

    function ensureTermLookupContextMenu() {
        if (termLookupState.contextMenu) return termLookupState.contextMenu;
        var menu = document.createElement('div');
        menu.className = 'rd-term-context-menu';
        menu.hidden = true;
        menu.innerHTML = [
            '<div class="rd-term-context-kicker">产业名词</div>',
            '<div class="rd-term-context-term"></div>',
            '<div class="rd-term-context-actions">',
            '<button type="button" class="rd-term-context-action">解释并存入知识库</button>',
            '<button type="button" class="rd-term-context-close" aria-label="关闭">×</button>',
            '</div>'
        ].join('');
        document.body.appendChild(menu);
        termLookupState.contextMenu = menu;
        menu.addEventListener('mousedown', function (event) {
            event.preventDefault();
        });
        menu.addEventListener('mouseenter', cancelTermContextHide);
        menu.addEventListener('mouseleave', function () {
            scheduleTermContextHide(TERM_CONTEXT_HIDE_DELAY_MS);
        });
        menu.querySelector('.rd-term-context-action').addEventListener('click', function (event) {
            event.preventDefault();
            hideTermLookupContextMenu();
            showTermLookupForSelection({
                text: termLookupState.selectedText,
                context: termLookupState.contextText,
                rect: termLookupState.selectionRect,
                sourceTitle: termLookupState.sourceTitle,
                sourceUrl: termLookupState.sourceUrl
            });
            lookupIndustryTerm(false);
        });
        menu.querySelector('.rd-term-context-close').addEventListener('click', function (event) {
            event.preventDefault();
            hideTermLookupContextMenu({ fade: true });
        });
        return menu;
    }

    function setTermSelectionState(info) {
        if (!info) return;
        termLookupState.selectedText = info.text;
        termLookupState.contextText = info.context || info.text;
        termLookupState.selectionRect = info.rect;
        termLookupState.sourceTitle = info.sourceTitle || document.title || '';
        termLookupState.sourceUrl = info.sourceUrl || (window.location.pathname + window.location.search);
        termLookupState.selectionKey = termSelectionKey(info);
    }

    function hideTermLookupContextMenu(options) {
        options = options || {};
        if (!termLookupState.contextMenu) return;
        window.clearTimeout(termLookupState.contextHideTimer);
        window.clearTimeout(termLookupState.contextFadeTimer);
        if (options.fade && !termLookupState.contextMenu.hidden) {
            termLookupState.contextMenu.classList.add('is-fading');
            termLookupState.contextMenu.classList.remove('is-open');
            termLookupState.contextFadeTimer = window.setTimeout(function () {
                if (!termLookupState.contextMenu || termLookupState.contextMenu.matches(':hover')) {
                    cancelTermContextHide();
                    return;
                }
                termLookupState.contextMenu.hidden = true;
                termLookupState.contextMenu.classList.remove('is-open', 'is-fading');
            }, TERM_CONTEXT_FADE_MS);
            return;
        }
        termLookupState.contextMenu.hidden = true;
        termLookupState.contextMenu.classList.remove('is-open', 'is-fading');
    }

    function positionTermLookupContextMenu(rect) {
        var menu = ensureTermLookupContextMenu();
        rect = rect || {};
        var width = Math.min(286, Math.max(220, window.innerWidth - 20));
        var height = 104;
        var center = typeof rect.left === 'number' && typeof rect.width === 'number'
            ? rect.left + rect.width / 2
            : (rect.left || 10);
        var left = Math.max(10, Math.min(window.innerWidth - width - 10, center - width / 2));
        var top = (typeof rect.bottom === 'number' ? rect.bottom : (rect.top || 10)) + 8;
        if (top + height > window.innerHeight - 10) {
            top = (typeof rect.top === 'number' ? rect.top : top) - height - 8;
        }
        top = Math.max(10, Math.min(window.innerHeight - height - 10, top));
        menu.style.left = Math.round(left) + 'px';
        menu.style.top = Math.round(top) + 'px';
    }

    function showTermLookupContextMenu(info) {
        if (!info) return;
        var nextKey = termSelectionKey(info);
        var selectionChanged = nextKey && nextKey !== termLookupState.selectionKey;
        setTermSelectionState(info);
        var menu = ensureTermLookupContextMenu();
        cancelTermContextHide();
        var term = menu.querySelector('.rd-term-context-term');
        if (term) term.textContent = info.text;
        if (selectionChanged && termLookupState.popover && !termLookupState.popover.hidden && !termLookupState.popover.matches(':hover')) {
            hideTermLookupPopover({ fade: true });
        }
        positionTermLookupContextMenu(info.rect || { left: 10, top: 10, bottom: 10 });
        menu.hidden = false;
        menu.classList.remove('is-fading');
        menu.classList.add('is-open');
    }

    function termLookupEscape(value) {
        return String(value || '').replace(/[&<>"']/g, function (ch) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[ch];
        });
    }

    function termLookupList(items) {
        if (!Array.isArray(items) || !items.length) return '';
        return '<ul>' + items.slice(0, 8).map(function (item) {
            return '<li>' + termLookupEscape(item) + '</li>';
        }).join('') + '</ul>';
    }

    function termSelectionKey(info) {
        if (!info) return '';
        var rect = info.rect || {};
        return [
            normalizeSelectedTerm(info.text),
            Math.round(rect.left || 0),
            Math.round(rect.top || 0),
            Math.round(rect.right || 0),
            Math.round(rect.bottom || 0),
            info.sourceUrl || ''
        ].join('|');
    }

    function termLookupPills(items, limit) {
        if (!Array.isArray(items) || !items.length) return '';
        return '<div class="rd-term-tags">' + items.slice(0, limit || 8).map(function (item) {
            return '<span>' + termLookupEscape(item) + '</span>';
        }).join('') + '</div>';
    }

    function termLookupMiniList(title, items) {
        if (!Array.isArray(items) || !items.length) return '';
        return '<div class="rd-term-section"><strong>' + termLookupEscape(title) + '</strong>' + termLookupList(items) + '</div>';
    }

    function setTermLookupLoading(loading) {
        var pop = ensureTermLookupPopover();
        pop.classList.toggle('is-loading', !!loading);
        pop.querySelectorAll('.rd-term-popover-actions button').forEach(function (btn) {
            btn.disabled = !!loading && !btn.classList.contains('rd-term-popover-close');
        });
    }

    function dispatchTermLibraryIntent(intent) {
        var detail = { section: 'terms', submode: intent === 'term-quiz' ? 'quiz' : 'view' };
        var delivered = false;
        try {
            window.dispatchEvent(new CustomEvent('reviewsdaily:experience-lessons-intent', { detail: detail }));
        } catch (error) {}
        document.querySelectorAll('.rd-tab-frame').forEach(function (frame) {
            try {
                var frameWindow = frame.contentWindow;
                if (!frameWindow || !frameWindow.location || basePath(frameWindow.location.pathname) !== '/experience_lessons') return;
                frameWindow.dispatchEvent(new frameWindow.CustomEvent('reviewsdaily:experience-lessons-intent', { detail: detail }));
                delivered = true;
            } catch (error) {}
        });
        return delivered;
    }

    function openTermKnowledgeLibrary(mode) {
        var intent = mode === 'quiz' ? 'term-quiz' : 'terms';
        try {
            sessionStorage.setItem(TERM_LIBRARY_INTENT_KEY, intent);
        } catch (error) {}
        var path = '/experience_lessons';
        if (dispatchTermLibraryIntent(intent) && basePath(activePath) === path) return;
        var owner = tabPathForPath(path);
        if (owner) {
            activateTab(owner, { innerPath: path });
            window.setTimeout(function () {
                dispatchTermLibraryIntent(intent);
            }, 180);
            return;
        }
        window.location.href = path;
    }

    function ensureTermLookupPopover() {
        if (termLookupState.popover) return termLookupState.popover;
        var pop = document.createElement('div');
        pop.className = 'rd-term-popover';
        pop.hidden = true;
        pop.innerHTML = [
            '<div class="rd-term-popover-head">',
            '<div>',
            '<div class="rd-term-popover-kicker">产业名词知识库</div>',
            '<div class="rd-term-popover-title">解释选中的名词</div>',
            '</div>',
            '<button type="button" class="rd-term-popover-close" aria-label="关闭">×</button>',
            '</div>',
            '<div class="rd-term-popover-body"></div>',
            '<div class="rd-term-popover-actions">',
            '<button type="button" class="rd-term-lookup-btn">生成知识卡</button>',
            '<button type="button" class="rd-term-force-btn">重新解释</button>',
            '<button type="button" class="rd-term-library-btn">打开知识库</button>',
            '</div>',
            '<div class="rd-term-popover-status" role="status" aria-live="polite"></div>'
        ].join('');
        document.body.appendChild(pop);
        termLookupState.popover = pop;
        pop.querySelector('.rd-term-popover-close').addEventListener('click', hideTermLookupPopover);
        pop.querySelector('.rd-term-lookup-btn').addEventListener('click', function () { lookupIndustryTerm(false); });
        pop.querySelector('.rd-term-force-btn').addEventListener('click', function () { lookupIndustryTerm(true); });
        pop.querySelector('.rd-term-library-btn').addEventListener('click', function () { openTermKnowledgeLibrary('terms'); });
        pop.addEventListener('mousedown', function (event) {
            event.preventDefault();
        });
        pop.addEventListener('mouseenter', cancelTermPopoverHide);
        pop.addEventListener('mouseleave', function () {
            scheduleTermPopoverHide(TERM_POPOVER_HIDE_DELAY_MS);
        });
        return pop;
    }

    function positionTermLookupPopover(rect) {
        var pop = ensureTermLookupPopover();
        rect = rect || {};
        var width = Math.min(420, Math.max(320, window.innerWidth - 24));
        var left = Math.max(12, Math.min(window.innerWidth - width - 12, (rect.left || 12) + (rect.width || 0) / 2 - width / 2));
        var top = (typeof rect.bottom === 'number' ? rect.bottom : (rect.top || 56)) + 12;
        if (top > window.innerHeight - 360) {
            top = Math.max(56, (typeof rect.top === 'number' ? rect.top : top) - 330);
        }
        pop.style.left = Math.round(left) + 'px';
        pop.style.top = Math.round(top) + 'px';
    }

    function setTermLookupStatus(text, tone) {
        var pop = ensureTermLookupPopover();
        var status = pop.querySelector('.rd-term-popover-status');
        if (!status) return;
        status.textContent = text || '';
        status.classList.toggle('is-error', tone === 'error');
        status.classList.toggle('is-ok', tone === 'ok');
        status.classList.toggle('is-loading', tone === 'loading');
    }

    function renderTermLookupIntro(text) {
        var pop = ensureTermLookupPopover();
        var title = pop.querySelector('.rd-term-popover-title');
        if (title) title.textContent = '解释选中的名词';
        pop.querySelector('.rd-term-popover-body').innerHTML = [
            '<div class="rd-term-intro-card">',
            '<div class="rd-term-selected">', termLookupEscape(text), '</div>',
            '<div class="rd-term-muted">会按产业链位置、观察信号、误读风险生成一张可复习的知识卡，并进入“产业名词”题库。</div>',
            '</div>'
        ].join('');
        pop.querySelector('.rd-term-lookup-btn').hidden = false;
        pop.querySelector('.rd-term-lookup-btn').textContent = '生成知识卡';
        pop.querySelector('.rd-term-force-btn').hidden = true;
        pop.querySelector('.rd-term-library-btn').hidden = false;
        setTermLookupLoading(false);
        setTermLookupStatus('', '');
    }

    function renderTermLookupItem(item, cached) {
        var pop = ensureTermLookupPopover();
        var exp = item && item.explanation ? item.explanation : {};
        var chain = exp.industry_chain || {};
        var tags = Array.isArray(item.tags) && item.tags.length ? item.tags : (Array.isArray(exp.tags) ? exp.tags : []);
        var title = pop.querySelector('.rd-term-popover-title');
        if (title) title.textContent = cached ? '已复用知识卡' : '已保存知识卡';
        pop.querySelector('.rd-term-popover-body').innerHTML = [
            '<div class="rd-term-result-head">',
            '<div class="rd-term-selected">', termLookupEscape(item.term || exp.term || termLookupState.selectedText), '</div>',
            '<span class="rd-term-save-pill">', cached ? '知识库已有' : '已存入', '</span>',
            '</div>',
            '<p class="rd-term-definition">', termLookupEscape(exp.short_definition || item.summary || ''), '</p>',
            exp.industry_position ? '<div class="rd-term-position"><strong>产业位置</strong><span>' + termLookupEscape(exp.industry_position) + '</span></div>' : '',
            '<div class="rd-term-chain">',
            '<div><strong>上游</strong>' + (termLookupList(chain.upstream) || '<em>待补充</em>') + '</div>',
            '<div><strong>中游</strong>' + (termLookupList(chain.midstream) || '<em>待补充</em>') + '</div>',
            '<div><strong>下游</strong>' + (termLookupList(chain.downstream) || '<em>待补充</em>') + '</div>',
            '</div>',
            '<div class="rd-term-two-col">',
            termLookupMiniList('观察信号', exp.investment_signals),
            termLookupMiniList('关键指标', exp.key_metrics),
            termLookupMiniList('价值驱动', exp.value_drivers),
            termLookupMiniList('容易误读', exp.misunderstandings),
            '</div>',
            termLookupMiniList('风险提示', exp.risks),
            termLookupPills(tags, 8)
        ].join('');
        pop.querySelector('.rd-term-lookup-btn').hidden = true;
        pop.querySelector('.rd-term-force-btn').hidden = false;
        pop.querySelector('.rd-term-library-btn').hidden = false;
        setTermLookupLoading(false);
        setTermLookupStatus(cached ? '这张卡已在知识库中，本次已更新使用次数。' : '已保存到知识库，也会进入产业名词考试。', 'ok');
    }

    function showTermLookupForSelection(info) {
        if (!info) return;
        var pop = ensureTermLookupPopover();
        cancelTermPopoverHide();
        setTermSelectionState(info);
        renderTermLookupIntro(info.text);
        positionTermLookupPopover(info.rect);
        pop.hidden = false;
        pop.classList.remove('is-fading');
        pop.classList.add('is-open');
        hideTermLookupContextMenu();
    }

    function hideTermLookupPopover(options) {
        options = options || {};
        if (!termLookupState.popover) return;
        window.clearTimeout(termLookupState.hideTimer);
        window.clearTimeout(termLookupState.popoverFadeTimer);
        if (options.fade && !termLookupState.popover.hidden) {
            termLookupState.popover.classList.add('is-fading');
            termLookupState.popover.classList.remove('is-open');
            termLookupState.popoverFadeTimer = window.setTimeout(function () {
                if (!termLookupState.popover || termLookupState.popover.matches(':hover')) {
                    cancelTermPopoverHide();
                    return;
                }
                termLookupState.popover.hidden = true;
                termLookupState.popover.classList.remove('is-open', 'is-fading');
                termLookupState.loading = false;
            }, TERM_POPOVER_FADE_MS);
            return;
        }
        termLookupState.popover.hidden = true;
        termLookupState.popover.classList.remove('is-open', 'is-fading');
        termLookupState.loading = false;
    }

    function scheduleSelectionLookup(doc, options) {
        options = options || {};
        doc = doc || document;
        window.clearTimeout(termLookupState.selectionTimer);
        termLookupState.selectionTimer = window.setTimeout(function () {
            if (termLookupState.contextMenu && termLookupState.contextMenu.matches(':hover')) return;
            if (termLookupState.popover && termLookupState.popover.matches(':hover')) return;
            var info = getSelectionInfo(doc, options);
            if (info) {
                translateSelectionInfoFromDoc(info, doc);
                showTermLookupContextMenu(info);
            } else if (!options.keepOpen) {
                hideTermLookupContextMenu({ fade: true });
            }
        }, options.delay == null ? TERM_SELECTION_DELAY_MS : options.delay);
    }

    function lookupIndustryTerm(force) {
        var term = normalizeSelectedTerm(termLookupState.selectedText);
        if (!term) {
            setTermLookupStatus('请先选择一个名词', 'error');
            return;
        }
        var requestId = termLookupState.lookupRequestId + 1;
        termLookupState.lookupRequestId = requestId;
        if (termLookupState.lookupController && termLookupState.lookupController.abort) {
            try { termLookupState.lookupController.abort(); } catch (error) {}
        }
        if (window.AbortController) {
            termLookupState.lookupController = new AbortController();
        } else {
            termLookupState.lookupController = null;
        }
        termLookupState.loading = true;
        setTermLookupLoading(true);
        setTermLookupStatus(force ? '正在重新解释...' : '正在解释并保存...', 'loading');
        fetch('/api/industry_terms/lookup', {
            method: 'POST',
            headers: csrfHeaders(),
            credentials: 'same-origin',
            cache: 'no-store',
            signal: termLookupState.lookupController ? termLookupState.lookupController.signal : undefined,
            body: JSON.stringify({
                term: term,
                context: termLookupState.contextText || term,
                source_title: termLookupState.sourceTitle || document.title || '',
                source_url: termLookupState.sourceUrl || (window.location.pathname + window.location.search),
                force: !!force
            })
        })
            .then(function (response) {
                return response.text().then(function (text) {
                    var payload = {};
                    if (text) {
                        try { payload = JSON.parse(text); } catch (error) { payload = { success: false, error: text.slice(0, 160) }; }
                    }
                    return { ok: response.ok, status: response.status, payload: payload };
                });
            })
            .then(function (result) {
                if (requestId !== termLookupState.lookupRequestId) return;
                var payload = result.payload || {};
                if (!result.ok || payload.success === false) {
                    throw new Error(payload.error || ('HTTP ' + result.status));
                }
                termLookupState.lastItem = payload.item || null;
                renderTermLookupItem(payload.item || {}, !!payload.cached);
                try {
                    window.dispatchEvent(new CustomEvent('reviewsdaily:industry-term-saved', { detail: payload.item || {} }));
                } catch (error) {}
                var frame = activeFrame();
                if (frame) {
                    try {
                        var frameWindow = frame.contentWindow;
                        if (frameWindow && frameWindow.CustomEvent) {
                            frameWindow.dispatchEvent(new frameWindow.CustomEvent('reviewsdaily:industry-term-saved', { detail: payload.item || {} }));
                        }
                    } catch (error) {}
                }
            })
            .catch(function (error) {
                if (error && error.name === 'AbortError') return;
                if (requestId !== termLookupState.lookupRequestId) return;
                setTermLookupStatus(error && error.message ? error.message : '名词解释失败', 'error');
            })
            .finally(function () {
                if (requestId !== termLookupState.lookupRequestId) return;
                termLookupState.loading = false;
                setTermLookupLoading(false);
            });
    }

    function bindTermLookupSelection(doc) {
        if (!doc || doc.__rdTermLookupSelectionBound) return;
        doc.__rdTermLookupSelectionBound = true;
        termLookupState.activeDoc = doc;
        doc.addEventListener('pointerdown', function (event) {
            window.clearTimeout(termLookupState.selectionTimer);
            if (event.target && event.target.closest && event.target.closest('.rd-term-popover, .rd-term-context-menu')) return;
            var anchor = event.target && event.target.closest ? event.target.closest('a[href]') : null;
            if (isTermSelectableLink(anchor)) {
                rememberLinkSelection(anchor);
            }
            hideTermLookupContextMenu({ fade: true });
        }, true);
        doc.addEventListener('mouseup', function (event) {
            if (event.target && event.target.closest && event.target.closest('.rd-term-popover')) return;
            if (event.target && event.target.closest && event.target.closest('.rd-term-context-menu')) return;
            var anchor = event.target && event.target.closest ? event.target.closest('a[href]') : null;
            if (isTermSelectableLink(anchor)) rememberLinkSelection(anchor);
            termLookupState.lastSelectionEventAt = Date.now();
            scheduleSelectionLookup(doc, {
                target: event.target,
                clientX: event.clientX,
                clientY: event.clientY
            });
        }, true);
        doc.addEventListener('pointerup', function (event) {
            if (Date.now() - termLookupState.lastSelectionEventAt < TERM_SELECTION_DUPLICATE_MS) return;
            if (event.target && event.target.closest && event.target.closest('.rd-term-popover, .rd-term-context-menu')) return;
            termLookupState.lastSelectionEventAt = Date.now();
            scheduleSelectionLookup(doc, {
                target: event.target,
                clientX: event.clientX,
                clientY: event.clientY
            });
        }, true);
        doc.addEventListener('contextmenu', function (event) {
            if (event.target && event.target.closest && event.target.closest('.rd-term-popover, .rd-term-context-menu')) return;
            var info = getSelectionInfo(doc, {
                target: event.target,
                clientX: event.clientX,
                clientY: event.clientY
            });
            if (!info) return;
            event.preventDefault();
            event.stopPropagation();
            translateSelectionInfoFromDoc(info, doc);
            hideTermLookupPopover();
            showTermLookupContextMenu(info);
        }, true);
        doc.addEventListener('click', function (event) {
            if (event.target && event.target.closest && event.target.closest('.rd-term-popover, .rd-term-context-menu')) return;
            hideTermLookupContextMenu({ fade: true });
            var anchor = event.target && event.target.closest ? event.target.closest('a[href]') : null;
            if (!shouldBlockLinkSelectionClick(anchor, doc)) return;
            event.preventDefault();
            event.stopPropagation();
            scheduleSelectionLookup(doc, {
                target: event.target,
                clientX: event.clientX,
                clientY: event.clientY
            });
        }, true);
        doc.addEventListener('keyup', function (event) {
            if (event.key === 'Escape') {
                hideTermLookupPopover();
                hideTermLookupContextMenu();
                return;
            }
            if (event.key === 'Shift' || event.key === 'Control' || event.key === 'Meta' || event.key === 'Alt') {
                scheduleSelectionLookup(doc);
            }
        }, true);
        doc.addEventListener('selectionchange', function () {
            window.clearTimeout(termLookupState.selectionTimer);
            termLookupState.selectionTimer = window.setTimeout(function () {
                var info = getSelectionInfo(doc);
                var menuHover = termLookupState.contextMenu && termLookupState.contextMenu.matches(':hover');
                var popoverHover = termLookupState.popover && termLookupState.popover.matches(':hover');
                if (info) {
                    cancelTermContextHide();
                    cancelTermPopoverHide();
                    return;
                }
                if (!info && termLookupState.contextMenu && !menuHover) {
                    scheduleTermContextHide(TERM_CONTEXT_HIDE_DELAY_MS);
                }
                if (!info && termLookupState.popover && !popoverHover) {
                    scheduleTermPopoverHide(TERM_POPOVER_HIDE_DELAY_MS);
                }
            }, 420);
        });
        var view = doc.defaultView || window;
        try {
            view.addEventListener('scroll', function () {
                if (termLookupState.contextMenu && !termLookupState.contextMenu.hidden) hideTermLookupContextMenu({ fade: true });
                if (termLookupState.popover && !termLookupState.popover.hidden && !termLookupState.popover.matches(':hover')) {
                    scheduleTermPopoverHide(320);
                }
            }, true);
            view.addEventListener('resize', function () {
                if (termLookupState.selectionRect && termLookupState.popover && !termLookupState.popover.hidden) {
                    positionTermLookupPopover(termLookupState.selectionRect);
                }
                if (termLookupState.selectionRect && termLookupState.contextMenu && !termLookupState.contextMenu.hidden) {
                    positionTermLookupContextMenu(termLookupState.selectionRect);
                }
            });
        } catch (error) {}
    }

    var navTipEl = null;
    var mottoState = null;

    function normalizeUsageDisplay(data) {
        if (!data || data.success === false) {
            return { text: '查询失败', tone: 'error', title: data && data.error ? data.error : 'AI 额度查询失败' };
        }
        if (!data.configured) {
            return { text: '未配置', tone: 'warn', title: 'AI 设置未配置 API Key 或 Base URL' };
        }
        if (!data.supported) {
            return { text: '不支持', tone: 'warn', title: data.message || '当前供应商没有可用的额度查询接口' };
        }
        var remaining = data.remaining;
        var unit = data.unit || '';
        var text = remaining === null || remaining === undefined || remaining === ''
            ? '已连接'
            : String(remaining) + (unit ? ' ' + unit : '');
        return {
            text: text,
            tone: data.active === false ? 'warn' : 'ok',
            title: (data.provider_label || 'AI') + ' · ' + (data.usage_url || '') + (data.checked_at ? ' · ' + data.checked_at : '')
        };
    }

    function setAiUsageState(data, isLoading) {
        var btn = document.getElementById('rdAiUsage');
        var value = document.getElementById('rdAiUsageValue');
        if (!btn || !value) return;
        btn.classList.remove('is-ok', 'is-warn', 'is-error', 'is-loading');
        if (isLoading) {
            btn.classList.add('is-loading');
            value.textContent = '查询中';
            btn.title = '正在查询 AI 额度';
            return;
        }
        var display = normalizeUsageDisplay(data || {});
        btn.classList.add('is-' + display.tone);
        value.textContent = display.text;
        btn.title = display.title || '点击刷新 AI 额度';
    }

    function readAiUsageCache() {
        try {
            var raw = localStorage.getItem(AI_USAGE_CACHE_KEY);
            if (!raw) return null;
            var cached = JSON.parse(raw);
            if (!cached || !cached.data || !cached.saved_at) return null;
            if (Date.now() - cached.saved_at > AI_USAGE_CACHE_TTL_MS) return null;
            return cached.data;
        } catch (error) {
            return null;
        }
    }

    function writeAiUsageCache(data) {
        try {
            localStorage.setItem(AI_USAGE_CACHE_KEY, JSON.stringify({ saved_at: Date.now(), data: data }));
        } catch (error) {}
    }

    function refreshAiUsage(force) {
        var btn = document.getElementById('rdAiUsage');
        if (!btn) return;
        if (!force) {
            var cached = readAiUsageCache();
            if (cached) {
                setAiUsageState(cached, false);
                return;
            }
        }
        setAiUsageState(null, true);
        fetch('/api/ai-provider/usage', { credentials: 'same-origin', cache: 'no-store' })
            .then(function (response) {
                return response.text().then(function (text) {
                    var payload = {};
                    if (text) {
                        try {
                            payload = JSON.parse(text);
                        } catch (error) {
                            payload = { success: false, error: '额度接口返回的不是 JSON' };
                        }
                    }
                    return { ok: response.ok, status: response.status, payload: payload };
                });
            })
            .then(function (result) {
                var payload = result.payload || {};
                if (!result.ok && payload.success !== false) {
                    payload = { success: false, error: 'HTTP ' + result.status };
                }
                writeAiUsageCache(payload);
                setAiUsageState(payload, false);
            })
            .catch(function (error) {
                setAiUsageState({ success: false, error: error && error.message ? error.message : '查询失败' }, false);
            });
    }

    function initAiUsageWidget() {
        var btn = document.getElementById('rdAiUsage');
        if (!btn) return;
        btn.addEventListener('click', function () {
            refreshAiUsage(true);
        });
        refreshAiUsage(false);
    }

    function hideNavTip() {
        if (navTipEl) {
            navTipEl.remove();
            navTipEl = null;
        }
    }

    function showNavTip(link) {
        if (!document.body.classList.contains('rd-nav-collapsed')) return;
        if (!link) return;
        var label = (link.getAttribute('aria-label') || link.getAttribute('data-rd-tab-title') || link.textContent || '').replace(/\s+/g, ' ').trim();
        if (!label) return;
        hideNavTip();
        navTipEl = document.createElement('div');
        navTipEl.className = 'rd-nav-floating-tip';
        navTipEl.textContent = label;
        document.body.appendChild(navTipEl);
        var rect = link.getBoundingClientRect();
        var tipRect = navTipEl.getBoundingClientRect();
        var top = Math.max(8, Math.min(window.innerHeight - tipRect.height - 8, rect.top + rect.height / 2 - tipRect.height / 2));
        navTipEl.style.left = (rect.right + 10) + 'px';
        navTipEl.style.top = top + 'px';
    }

    function clampMottoPosition(state) {
        var maxX = Math.max(12, window.innerWidth - state.width - 12);
        var maxY = Math.max(12, window.innerHeight - state.height - 12);
        state.x = Math.max(12, Math.min(maxX, state.x));
        state.y = Math.max(12, Math.min(maxY, state.y));
    }

    function createMottoRipple(x, y) {
        var ripple = document.createElement('span');
        ripple.className = 'rd-motto-ripple';
        ripple.style.left = x + 'px';
        ripple.style.top = y + 'px';
        document.body.appendChild(ripple);
        window.setTimeout(function () {
            ripple.remove();
        }, 780);
    }

    function initMottoFloater() {
        if (window.self !== window.top) return;
        if (document.querySelector('.rd-motto-floater')) return;

        var floater = document.createElement('button');
        floater.type = 'button';
        floater.className = 'rd-motto-floater';
        floater.textContent = BRAND_NAME;
        floater.setAttribute('aria-label', '知行合一互动浮标');
        document.body.appendChild(floater);

        var rect = floater.getBoundingClientRect();
        mottoState = {
            el: floater,
            width: rect.width || 84,
            height: rect.height || 32,
            x: Math.max(72, window.innerWidth - (rect.width || 84) - 72),
            y: Math.max(88, Math.round(window.innerHeight * 0.28)),
            vx: 0.34,
            vy: 0.22,
            last: 0,
            boostUntil: 0,
            paused: false,
        };
        clampMottoPosition(mottoState);

        function step(ts) {
            var state = mottoState;
            if (!state || !state.el.isConnected) return;
            if (!state.last) state.last = ts;
            var delta = Math.min(42, ts - state.last);
            state.last = ts;
            if (!state.paused) {
                var speed = ts < state.boostUntil ? 2.4 : 1;
                state.x += state.vx * delta * speed;
                state.y += state.vy * delta * speed;
                var maxX = Math.max(12, window.innerWidth - state.width - 12);
                var maxY = Math.max(12, window.innerHeight - state.height - 12);
                if (state.x <= 12 || state.x >= maxX) state.vx *= -1;
                if (state.y <= 12 || state.y >= maxY) state.vy *= -1;
                clampMottoPosition(state);
                state.el.style.transform = 'translate3d(' + state.x.toFixed(1) + 'px, ' + state.y.toFixed(1) + 'px, 0)';
            }
            window.requestAnimationFrame(step);
        }

        floater.addEventListener('mouseenter', function () {
            if (mottoState) mottoState.paused = true;
        });
        floater.addEventListener('mouseleave', function () {
            if (mottoState) mottoState.paused = false;
        });
        floater.addEventListener('click', function (event) {
            if (!mottoState) return;
            mottoState.vx = (Math.random() > 0.5 ? 1 : -1) * (0.44 + Math.random() * 0.26);
            mottoState.vy = (Math.random() > 0.5 ? 1 : -1) * (0.26 + Math.random() * 0.24);
            mottoState.boostUntil = performance.now() + 900;
            floater.classList.remove('is-spark');
            void floater.offsetWidth;
            floater.classList.add('is-spark');
            createMottoRipple(event.clientX, event.clientY);
        });
        window.addEventListener('resize', function () {
            if (!mottoState) return;
            var nextRect = mottoState.el.getBoundingClientRect();
            mottoState.width = nextRect.width || mottoState.width;
            mottoState.height = nextRect.height || mottoState.height;
            clampMottoPosition(mottoState);
        });
        window.requestAnimationFrame(step);
    }

    function initWorkspaceShell() {
        var shell = document.getElementById('rd-workspace-shell');
        if (!shell) return;
        bindThorShortcut(document);
        bindTermLookupSelection(document);
        document.body.classList.add('rd-workspace-active');
        document.querySelectorAll('.rd-nav-link, .rd-brand, .rd-nav-toggle').forEach(function (link) {
            var label = link.getAttribute('data-rd-tab-title') || link.getAttribute('aria-label') || link.getAttribute('title') || link.textContent || '';
            label = label.replace(/\s+/g, ' ').trim();
            if (label && !link.getAttribute('aria-label')) {
                link.setAttribute('aria-label', label);
            }
            link.addEventListener('mouseenter', function () { showNavTip(link); });
            link.addEventListener('focus', function () { showNavTip(link); });
            link.addEventListener('mouseleave', hideNavTip);
            link.addEventListener('blur', hideNavTip);
        });
        if (localStorage.getItem(NAV_KEY) === '1') {
            document.body.classList.add('rd-nav-collapsed');
        }

        try {
            var collapsedSections = JSON.parse(localStorage.getItem(NAV_SECTION_KEY) || '{}') || {};
            document.querySelectorAll('.rd-nav-section[data-rd-nav-section]').forEach(function (section) {
                if (!section.querySelector('.rd-nav-link')) {
                    section.hidden = true;
                    return;
                }
                var id = section.getAttribute('data-rd-nav-section');
                var label = section.querySelector('.rd-nav-label');
                var isCollapsed = Object.prototype.hasOwnProperty.call(collapsedSections, id)
                    ? !!collapsedSections[id]
                    : section.getAttribute('data-default-collapsed') === 'true';
                section.classList.toggle('collapsed', isCollapsed);
                if (label) label.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
                if (label) {
                    label.addEventListener('click', function () {
                        if (document.body.classList.contains('rd-nav-collapsed') && !window.matchMedia('(max-width: 900px)').matches) return;
                        var next = !section.classList.contains('collapsed');
                        section.classList.toggle('collapsed', next);
                        label.setAttribute('aria-expanded', next ? 'false' : 'true');
                        collapsedSections[id] = next;
                        localStorage.setItem(NAV_SECTION_KEY, JSON.stringify(collapsedSections));
                    });
                }
            });
        } catch (error) {}

        ROOT_TAB_PATH = tabPathForPath(ROOT_PATH) || ROOT_PATH;
        var meta = tabMetaForPath(ROOT_TAB_PATH, getTitleFromDocument());
        upsertTab(ROOT_TAB_PATH, meta.title, meta.icon, ROOT_TAB_PATH !== ROOT_PATH ? ROOT_PATH : '');
        activePath = ROOT_TAB_PATH;
        updateActiveNav(activePath);
        renderTabs();
        initAiUsageWidget();

        var toggle = document.getElementById('rdNavToggle');
        if (toggle) {
            toggle.addEventListener('click', function () {
                if (window.matchMedia('(max-width: 900px)').matches) {
                    document.body.classList.toggle('rd-mobile-nav-open');
                    return;
                }
                document.body.classList.toggle('rd-nav-collapsed');
                localStorage.setItem(NAV_KEY, document.body.classList.contains('rd-nav-collapsed') ? '1' : '0');
                hideNavTip();
            });
        }

        var mobileToggle = document.getElementById('rdMobileNavToggle');
        if (mobileToggle) {
            mobileToggle.addEventListener('click', function () {
                document.body.classList.toggle('rd-mobile-nav-open');
            });
        }
        var scrim = document.getElementById('rdNavScrim');
        if (scrim) {
            scrim.addEventListener('click', function () {
                document.body.classList.remove('rd-mobile-nav-open');
            });
        }

        var closeOther = document.getElementById('rdCloseOtherTabs');
        if (closeOther) {
            var bulkMenu = document.getElementById('rdTabBulkMenu');
            function setBulkMenuOpen(open) {
                if (!bulkMenu) return;
                bulkMenu.hidden = !open;
                closeOther.setAttribute('aria-expanded', open ? 'true' : 'false');
            }
            closeOther.addEventListener('click', function (event) {
                event.preventDefault();
                event.stopPropagation();
                setBulkMenuOpen(bulkMenu ? bulkMenu.hidden : false);
            });
            if (bulkMenu) {
                bulkMenu.addEventListener('click', function (event) {
                    var btn = event.target.closest ? event.target.closest('[data-rd-close-mode]') : null;
                    if (!btn) return;
                    event.preventDefault();
                    event.stopPropagation();
                    setBulkMenuOpen(false);
                    closeTabsByMode(btn.getAttribute('data-rd-close-mode') || 'others');
                });
                document.addEventListener('click', function (event) {
                    if (bulkMenu.hidden) return;
                    if (event.target.closest && event.target.closest('.rd-tab-actions')) return;
                    setBulkMenuOpen(false);
                });
                document.addEventListener('keydown', function (event) {
                    if (event.key === 'Escape') setBulkMenuOpen(false);
                });
            }
        }

        document.addEventListener('click', function (event) {
            var anchor = event.target.closest ? event.target.closest('a[href]') : null;
            handleWorkspaceNavigation(anchor, event);
        }, true);

        document.addEventListener('keydown', function (event) {
            if ((event.ctrlKey || event.metaKey) && event.altKey && event.key.toLowerCase() === 'b') {
                event.preventDefault();
                document.body.classList.toggle('rd-nav-collapsed');
                localStorage.setItem(NAV_KEY, document.body.classList.contains('rd-nav-collapsed') ? '1' : '0');
                hideNavTip();
            }
        });

        window.addEventListener('popstate', function () {
            var path = normalizePath(window.location.href);
            var tabPath = tabPathForPath(path) || path;
            if (readTabs().some(function (tab) { return tab.path === tabPath; })) {
                activateTab(tabPath, { skipHistory: true });
            }
        });
    }

    ready(function () {
        applyBrandTitle();
        initMottoFloater();
        bindThorShortcut(document);
        var isFrameMode = document.body && document.body.classList.contains('rd-workspace-frame');
        if (!isFrameMode) bindTermLookupSelection(document);
        initWorkspaceShell();

        document.querySelectorAll('[data-rd-confirm]').forEach(function (el) {
            el.addEventListener('click', function (event) {
                var message = el.getAttribute('data-rd-confirm') || '确定继续吗？';
                if (!window.confirm(message)) {
                    event.preventDefault();
                    event.stopPropagation();
                }
            });
        });
    });
})();
