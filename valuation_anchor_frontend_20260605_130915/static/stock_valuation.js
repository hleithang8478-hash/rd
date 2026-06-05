(function () {
    const page = document.querySelector('.valuation-page');
    const methodDefinitions = safeJson(page?.dataset.methodDefinitions, []);

    const state = {
        activeTab: 'profile',
        source: 'juyuan',
        stockCode: '',
        facts: {},
        config: {},
        defaults: {},
        guide: null,
        lastValuation: null,
        recommendations: [],
        currentCase: null,
        cases: [],
        caseScope: 'current',
        loading: false,
        hydrating: false,
        assumptionEvidenceDrafts: {},
        inlinePopoverField: '',
        assumptionDrawerOpen: false,
        verifyingFields: new Set(),
        activeCoachJobs: 0,
        workflow: {
            completedTabs: [],
            unlockedTabs: ['profile', 'cases'],
            lastCompletedTab: ''
        },
        assumptionStepIndex: 0,
        pbProcessStepIndex: 0,
        saveTimer: null
    };

    const $ = (id) => document.getElementById(id);
    const workflowTabs = ['profile', 'methods', 'assumptions', 'scenarios', 'conclusion'];
    const alwaysOpenTabs = new Set(['cases']);
    const tabTitles = {
        profile: 'Profile',
        methods: 'Methods',
        assumptions: 'Assumptions',
        scenarios: 'Scenarios',
        conclusion: 'Conclusion',
        cases: 'Cases'
    };
    const manualKeys = [
        'close_price', 'pe_ttm', 'pb', 'ps_ttm', 'pcf_ttm',
        'roe_ttm', 'revenue_growth', 'revenue_ps', 'dividend_ps', 'third_industry'
    ];
    const assumptionMap = {
        target_pe: 'targetPe',
        target_pb: 'targetPb',
        target_ps: 'targetPs',
        target_pcf: 'targetPcf',
        target_dividend_yield: 'targetDividendYield',
        dcf_growth: 'dcfGrowth',
        discount_rate: 'discountRate',
        terminal_growth: 'terminalGrowth',
        eps: 'epsInput',
        bvps: 'bvpsInput',
        cashflow_ps: 'cashflowPsInput',
        dcf_years: 'dcfYears'
    };
    const percentKeys = new Set(['target_dividend_yield', 'dcf_growth', 'discount_rate', 'terminal_growth']);
    const rebuttalTags = ['引用财报', '行业政策', '管理层', '历史分位'];
    const defaultMethodFields = {
        dcf: { primary: ['dcf_growth', 'discount_rate', 'terminal_growth', 'dcf_years'], supporting: ['cashflow_ps'], secondary: ['target_pe', 'target_pcf'] },
        pe: { primary: ['target_pe', 'eps'], supporting: ['dcf_growth'], secondary: ['target_pb', 'target_ps'] },
        pb: { primary: ['target_pb', 'bvps'], supporting: [], secondary: ['target_pe', 'target_dividend_yield'] },
        ps: { primary: ['target_ps'], supporting: ['dcf_growth'], secondary: ['target_pe', 'target_pcf'] },
        pcf: { primary: ['target_pcf', 'cashflow_ps'], supporting: [], secondary: ['target_pe', 'dcf_growth'] },
        dividend: { primary: ['target_dividend_yield'], supporting: [], secondary: ['target_pb', 'target_pe'] }
    };
    const assumptionRowOrder = [
        'target_pe',
        'target_pb',
        'target_ps',
        'target_pcf',
        'dcf_growth',
        'discount_rate',
        'terminal_growth',
        'target_dividend_yield',
        'eps',
        'bvps',
        'cashflow_ps',
        'dcf_years'
    ];
    const guidedAssumptionOrder = [
        'target_pe',
        'target_pb',
        'target_ps',
        'target_pcf',
        'dcf_growth',
        'discount_rate',
        'terminal_growth',
        'target_dividend_yield',
        'eps',
        'bvps',
        'cashflow_ps',
        'dcf_years'
    ];
    const configLabels = {
        stock_table: '证券主表',
        quote_table: '日线行情',
        valuation_table: '估值指标',
        financial_table: '财务指标',
        income_table: '利润表',
        dividend_table: '分红事件'
    };

    function asArray(value) {
        return Array.isArray(value) ? value : [];
    }

    function safeJson(text, fallback) {
        try {
            return JSON.parse(text || '');
        } catch (_) {
            return fallback;
        }
    }

    function fmtNumber(value, digits = 2) {
        if (value === null || value === undefined || value === '') return '-';
        const n = Number(value);
        if (!Number.isFinite(n)) return '-';
        return n.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }

    function fmtPct(value) {
        if (value === null || value === undefined || value === '') return '-';
        const n = Number(value);
        if (!Number.isFinite(n)) return '-';
        return (Math.abs(n) <= 1.5 ? n * 100 : n).toFixed(2) + '%';
    }

    function fmtMetric(value, format = 'number') {
        if (format === 'text') return value === null || value === undefined || value === '' ? '-' : String(value);
        return format === 'pct' ? fmtPct(value) : fmtNumber(value, 2);
    }

    function parseValue(id) {
        const raw = ($(id)?.value || '').trim();
        if (!raw) return null;
        const n = Number(raw.replace(/,/g, ''));
        return Number.isFinite(n) ? n : null;
    }

    function pctAssumption(id) {
        const n = parseValue(id);
        if (n === null) return null;
        return Math.abs(n) > 1.5 ? n / 100 : n;
    }

    function setStatus(text, tone = '') {
        const el = $('sideStatus');
        if (!el) return;
        el.textContent = text || '';
        el.className = 'status-line ' + tone;
    }

    function setLoading(loading) {
        state.loading = loading;
        [
            'fetchBtn', 'createCaseBtn', 'guideBtn', 'applyGuideBtn', 'calcBtn',
            'runScenariosBtn', 'saveSnapshotBtn', 'saveConfigBtn', 'saveAssumptionsBtn',
            'coachBtn', 'reviewAssumptionsBtn', 'refreshCasesBtn'
        ].forEach((id) => {
            const el = $(id);
            if (el) el.disabled = loading;
        });
        document.querySelectorAll('[data-case-scope]').forEach((el) => {
            el.disabled = loading;
        });
        document.querySelectorAll('[data-delete-case]').forEach((el) => {
            el.disabled = loading;
        });
        renderWorkflowRail();
    }

    function uniqueTabs(items) {
        const allowed = new Set([...workflowTabs, ...alwaysOpenTabs]);
        const out = [];
        (items || []).forEach((item) => {
            if (allowed.has(item) && !out.includes(item)) out.push(item);
        });
        return out;
    }

    function tabIndex(tabKey) {
        return workflowTabs.indexOf(tabKey);
    }

    function normalizeWorkflow(raw) {
        const completed = uniqueTabs(raw?.completed_tabs || raw?.completedTabs || state.workflow.completedTabs || []);
        let unlocked = uniqueTabs(raw?.unlocked_tabs || raw?.unlockedTabs || state.workflow.unlockedTabs || ['profile', 'cases']);
        unlocked = uniqueTabs([...unlocked, 'profile', 'cases']);
        completed.forEach((tab) => {
            const idx = tabIndex(tab);
            if (idx >= 0 && workflowTabs[idx + 1]) unlocked.push(workflowTabs[idx + 1]);
        });
        if (state.facts?.stock_code) unlocked.push('methods');
        if (state.guide?.method_decision?.primary_method) unlocked.push('assumptions');
        if ((state.currentCase?.assumptions || []).length) unlocked.push('scenarios');
        if ((state.currentCase?.latest_results || []).length || state.lastValuation?.summary?.available_methods) unlocked.push('conclusion');
        return {
            completedTabs: uniqueTabs(completed),
            unlockedTabs: uniqueTabs(unlocked),
            lastCompletedTab: raw?.last_completed_tab || raw?.lastCompletedTab || completed[completed.length - 1] || ''
        };
    }

    function markCompleted(tabKey) {
        if (workflowTabs.includes(tabKey) && !state.workflow.completedTabs.includes(tabKey)) {
            state.workflow.completedTabs.push(tabKey);
        }
        const next = workflowTabs[tabIndex(tabKey) + 1];
        if (next && !state.workflow.unlockedTabs.includes(next)) state.workflow.unlockedTabs.push(next);
        if (!state.workflow.unlockedTabs.includes('cases')) state.workflow.unlockedTabs.push('cases');
        state.workflow.lastCompletedTab = tabKey;
        renderWorkflowRail();
    }

    function invalidateFrom(tabKey, keepCurrent = true) {
        const idx = tabIndex(tabKey);
        if (idx < 0) return;
        const keep = new Set(workflowTabs.slice(0, idx + (keepCurrent ? 1 : 0)));
        state.workflow.completedTabs = state.workflow.completedTabs.filter((tab) => keep.has(tab));
        state.workflow.unlockedTabs = uniqueTabs([...workflowTabs.slice(0, idx + 1), 'cases']);
        if (keepCurrent && workflowTabs[idx + 1]) state.workflow.unlockedTabs.push(workflowTabs[idx + 1]);
        state.workflow.lastCompletedTab = state.workflow.completedTabs[state.workflow.completedTabs.length - 1] || '';
        renderWorkflowRail();
        scheduleCaseStateSave();
    }

    function prerequisitesMessage(tabKey) {
        const pbGate = pbProcessGate();
        if ((tabKey === 'scenarios' || tabKey === 'conclusion') && !pbGate.ok) {
            const first = pbGate.blockers[0] || pbGate.missing[0];
            return `PB 主锚还没闭环：请先完成「${first?.title || 'PB 推导流程'}」。`;
        }
        if ((tabKey === 'scenarios' || tabKey === 'conclusion') && hasLevelOneBlockers()) {
            const first = levelOneBlockers()[0];
            return `先解决 Level 1：${first.label || coachFieldLabel(first.field)}。`;
        }
        if (tabKey === 'methods') return '先完成公司画像和数据核对，再进入估值方法。';
        if (tabKey === 'assumptions') return '先生成并确认估值方法，再填写假设。';
        if (tabKey === 'scenarios') return '先保存假设，再做情景测算。';
        if (tabKey === 'conclusion') return '先完成情景测算，再回到结论。';
        return '请先完成前一步。';
    }

    function canOpenTab(tabKey) {
        if ((tabKey === 'scenarios' || tabKey === 'conclusion') && !pbProcessGate().ok) return false;
        if ((tabKey === 'scenarios' || tabKey === 'conclusion') && hasLevelOneBlockers()) return false;
        return alwaysOpenTabs.has(tabKey) || state.workflow.unlockedTabs.includes(tabKey) || state.workflow.completedTabs.includes(tabKey);
    }

    function renderWorkflowRail() {
        document.querySelectorAll('[data-tab-button]').forEach((btn) => {
            const tabKey = btn.dataset.tabButton;
            const done = state.workflow.completedTabs.includes(tabKey);
            const unlocked = canOpenTab(tabKey);
            btn.classList.toggle('active', tabKey === state.activeTab);
            btn.classList.toggle('done', done);
            btn.classList.toggle('locked', !unlocked);
            btn.disabled = state.loading && !alwaysOpenTabs.has(tabKey);
            btn.setAttribute('aria-disabled', unlocked ? 'false' : 'true');
            btn.title = unlocked ? '' : prerequisitesMessage(tabKey);
        });
    }

    function buildCaseState() {
        const existing = state.currentCase?.state || {};
        return Object.assign({}, existing, {
            schema_version: existing.schema_version || 'valuation_case_v1',
            ui: {
                active_tab: state.activeTab,
                dirty: false
            },
            identity: {
                stock_code: state.stockCode || state.facts?.stock_code || '',
                stock_name: state.facts?.stock_name || state.currentCase?.stock_name || '',
                valuation_date: $('asOfInput')?.value || state.currentCase?.valuation_date || ''
            },
            facts: state.facts || {},
            valuation: state.lastValuation || existing.valuation || {},
            recommendations: state.recommendations || [],
            guide: state.guide || existing.guide || {},
            data_quality: state.guide?.data_quality || existing.data_quality || {},
            workflow: {
                completed_tabs: uniqueTabs(state.workflow.completedTabs),
                unlocked_tabs: uniqueTabs(state.workflow.unlockedTabs),
                last_completed_tab: state.workflow.lastCompletedTab || ''
            },
            tabs: Object.assign({}, existing.tabs || {}, {
                profile: Object.assign({}, existing.tabs?.profile || {}, {
                    loaded: Boolean(state.facts?.stock_code),
                    manual_fields: currentManualFields()
                }),
                methods: Object.assign({}, existing.tabs?.methods || {}, {
                    selected_primary: state.guide?.method_decision?.primary_method || ''
                }),
                assumptions: Object.assign({}, existing.tabs?.assumptions || {}, {
                    active_scenario: 'base',
                    items: currentUiAssumptions(),
                    evidence: currentAssumptionEvidence(),
                    pb_process: {
                        active_index: state.pbProcessStepIndex,
                        completed_steps: pbProcessSteps().filter((step) => step.status === 'done').map((step) => step.key)
                    },
                    logic: $('assumptionLogic')?.value || '',
                    review: state.currentCase?.state?.assumption_review || existing.assumption_review || existing.tabs?.assumptions?.review || null
                }),
                scenarios: Object.assign({}, existing.tabs?.scenarios || {}, {
                    active: 'base',
                    drafts: currentScenarioDrafts()
                }),
                conclusion: Object.assign({}, existing.tabs?.conclusion || {}, {
                    summary: state.guide?.conclusion?.text || ''
                })
            })
        });
    }

    async function saveCaseState(immediate = false) {
        if (!state.currentCase?.id || state.hydrating) return;
        window.clearTimeout(state.saveTimer);
        const run = async () => {
            try {
                const data = await apiFetch(`/api/stock_valuation/cases/${state.currentCase.id}/state`, {
                    method: 'POST',
                    body: JSON.stringify({ state: buildCaseState(), current_tab: state.activeTab })
                });
                if (data.case) state.currentCase = data.case;
                state.workflow = normalizeWorkflow(state.currentCase?.state?.workflow);
                renderWorkflowRail();
                renderCaseHeader();
            } catch (err) {
                setStatus(`保存工作流状态失败：${err.message}`, 'warn');
            }
        };
        if (immediate) {
            await run();
        } else {
            state.saveTimer = window.setTimeout(run, 650);
        }
    }

    function scheduleCaseStateSave() {
        saveCaseState(false);
    }

    async function apiFetch(url, options = {}) {
        const headers = Object.assign({ 'Content-Type': 'application/json' }, options.headers || {});
        const token = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        if (token) headers['X-CSRF-Token'] = token;
        const res = await fetch(url, Object.assign({}, options, { headers }));
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.success) {
            throw new Error(data.error || `请求失败：${res.status}`);
        }
        return data;
    }

    function switchTab(tabKey) {
        if (!canOpenTab(tabKey)) {
            setStatus(prerequisitesMessage(tabKey), 'warn');
            renderWorkflowRail();
            return;
        }
        state.activeTab = tabKey;
        renderWorkflowRail();
        document.querySelectorAll('[data-tab-panel]').forEach((panel) => {
            panel.classList.toggle('active', panel.dataset.tabPanel === tabKey);
        });
        if (tabKey === 'assumptions') renderGuidedAssumptions();
        if (tabKey === 'cases') loadCases().catch((err) => setStatus(err.message, 'err'));
        scheduleCaseStateSave();
    }

    function normalizeCode(text) {
        const match = String(text || '').match(/\d{6}/);
        return match ? match[0] : '';
    }

    function currentManualFields() {
        const fields = {};
        manualKeys.forEach((key) => {
            const input = document.querySelector(`[data-manual="${key}"]`);
            if (!input) return;
            const value = input.value.trim();
            if (value) fields[key] = value;
        });
        if (state.stockCode) fields.stock_code = state.stockCode;
        return fields;
    }

    function currentUiAssumptions() {
        const out = {};
        Object.entries(assumptionMap).forEach(([key, id]) => {
            const n = parseValue(id);
            if (n !== null) out[key] = n;
        });
        return out;
    }

    function currentAssumptionEvidence() {
        const out = Object.assign({}, savedAssumptionEvidence(), state.assumptionEvidenceDrafts || {});
        Object.keys(assumptionMap).forEach((key) => {
            const input = document.querySelector(`[data-assumption-evidence="${key}"]`);
            const rowInput = document.querySelector(`[data-assumption-logic="${key}"]`);
            if (input) out[key] = input.value.trim();
            if (rowInput) out[key] = rowInput.value.trim();
        });
        document.querySelectorAll('[data-pb-step]').forEach((input) => {
            out[pbStepEvidenceKey(input.dataset.pbStep)] = input.value.trim();
        });
        document.querySelectorAll('[data-pb-metric]').forEach((input) => {
            out[pbMetricEvidenceKey(input.dataset.pbStepKey, input.dataset.pbMetric)] = input.value.trim();
        });
        return out;
    }

    function setAssumptionEvidence(values) {
        const evidence = values || {};
        state.assumptionEvidenceDrafts = Object.assign({}, state.assumptionEvidenceDrafts || {}, evidence);
        Object.keys(assumptionMap).forEach((key) => {
            const input = document.querySelector(`[data-assumption-evidence="${key}"]`);
            const rowInput = document.querySelector(`[data-assumption-logic="${key}"]`);
            if (input) input.value = evidence[key] || '';
            if (rowInput) rowInput.value = evidence[key] || '';
        });
        document.querySelectorAll('[data-pb-step]').forEach((input) => {
            input.value = evidence[pbStepEvidenceKey(input.dataset.pbStep)] || '';
        });
        document.querySelectorAll('[data-pb-metric]').forEach((input) => {
            input.value = evidence[pbMetricEvidenceKey(input.dataset.pbStepKey, input.dataset.pbMetric)] || '';
        });
        syncAssumptionLogicFromRows();
    }

    function savedAssumptionEvidence() {
        const saved = {};
        (state.currentCase?.assumptions || []).forEach((item) => {
            if (item.scenario_key !== 'base' || !item.assumption_key) return;
            const text = item.user_logic || item.evidence_text || '';
            if (text) saved[item.assumption_key] = text;
        });
        return Object.assign({}, state.currentCase?.state?.tabs?.assumptions?.evidence || {}, saved);
    }

    function currentCalcAssumptions() {
        const out = {};
        Object.entries(assumptionMap).forEach(([key, id]) => {
            const n = percentKeys.has(key) ? pctAssumption(id) : parseValue(id);
            if (n !== null) out[key] = n;
        });
        return out;
    }

    function currentScenarioDrafts() {
        const drafts = {};
        document.querySelectorAll('[data-scenario-key]').forEach((card) => {
            const item = {};
            card.querySelectorAll('[data-scenario-field]').forEach((input) => {
                item[input.dataset.scenarioField] = input.value;
            });
            drafts[card.dataset.scenarioKey] = item;
        });
        return drafts;
    }

    function setAssumptionInputs(values) {
        if (!values) return;
        Object.entries(assumptionMap).forEach(([key, id]) => {
            if (values[key] === null || values[key] === undefined || values[key] === '') return;
            const input = $(id);
            if (input) input.value = values[key];
        });
    }

    function currentAnchorPlan() {
        const plan = state.guide?.anchor_plan || state.currentCase?.state?.guide?.anchor_plan || {};
        if (plan && typeof plan === 'object' && (plan.primary_method || plan.anchor_field || plan.headline)) {
            return plan;
        }
        const method = state.guide?.method_decision?.primary_method || state.currentCase?.state?.tabs?.methods?.selected_primary || '';
        const fields = defaultMethodFields[method] || defaultMethodFields.pe;
        const anchorField = fields.primary.find((key) => assumptionMap[key]) || 'target_pe';
        return {
            primary_method: method || 'pe',
            primary_method_name: (method || 'PE').toUpperCase(),
            anchor_field: anchorField,
            anchor_label: assumptionLabel(anchorField),
            headline: method ? `03 假设应围绕 ${(method || '').toUpperCase()} 主锚展开，其他方法只做交叉验证。` : '先在 02 生成估值路径，再进入主锚假设推导。',
            formula: '',
            primary_fields: fields.primary,
            supporting_fields: fields.supporting,
            secondary_fields: fields.secondary,
            derivation_steps: [],
            factors: []
        };
    }

    function pbHistory() {
        return state.facts?.pb_history || {};
    }

    function pbStepEvidenceKey(key) {
        return `pb_step_${key}`;
    }

    function pbStepSkipKey(key) {
        return `pb_skip_${key}`;
    }

    function pbStepEvidence(key) {
        return (currentAssumptionEvidence()[pbStepEvidenceKey(key)] || '').trim();
    }

    function pbStepSkipReason(key) {
        return (currentAssumptionEvidence()[pbStepSkipKey(key)] || '').trim();
    }

    function pbHistoryIsUsable(history = pbHistory()) {
        return Number(history.sample_count || 0) >= 120 && history.percentile !== null && history.percentile !== undefined;
    }

    function pbProcessSteps() {
        const plan = currentAnchorPlan();
        if ((plan.primary_method || '').toLowerCase() !== 'pb') return [];
        const history = pbHistory();
        const currentPb = history.current_pb ?? state.facts?.pb;
        const percentile = history.percentile_label || (history.percentile !== null && history.percentile !== undefined ? `${Math.round(Number(history.percentile) * 1000) / 10}%` : '-');
        return [
            {
                key: 'history_percentile',
                title: '1. 历史 PB 分位',
                owner: '系统计算',
                status: pbHistoryIsUsable(history) || pbStepSkipReason('history_percentile') ? 'done' : 'blocked',
                result: pbHistoryIsUsable(history)
                    ? `当前 PB ${fmtNumber(currentPb, 2)}，近 ${history.years || 10} 年分位 ${percentile}，区间 ${fmtNumber(history.min, 2)}-${fmtNumber(history.max, 2)}，样本 ${history.sample_count}。`
                    : pbStepSkipReason('history_percentile')
                    ? `已跳过历史分位：${pbStepSkipReason('history_percentile')}`
                    : `历史 PB 样本不足或未取到，样本 ${history.sample_count || 0}；目标 PB 只能保存为草稿。`,
                prompt: '系统必须先算出历史分位；没有它，不允许把 PB 结论当成正式锚。',
                required: true,
                computed: true
            },
            {
                key: 'quality',
                title: '2. 质地结论',
                owner: '你确认',
                status: pbStepEvidence('quality') ? 'done' : 'todo',
                result: pbStepEvidence('quality') || '还没有形成质地结论。',
                prompt: '用现金流/净利润、负债结构、ROIC、毛利稳定性、研发或成本曲线，写一句“质地较好/一般/待验证”的依据。',
                required: true
            },
            {
                key: 'cycle',
                title: '3. 周期定位',
                owner: '你确认',
                status: pbStepEvidence('cycle') ? 'done' : 'todo',
                result: pbStepEvidence('cycle') || '还没有确认利润处在低位、中性还是高位。',
                prompt: '写清核心产品价格/价差、开工率、库存或下游需求处在什么位置，以及当前 ROE 是否需要正常化。',
                required: true
            },
            {
                key: 'asset_quality',
                title: '4. 净资产质量',
                owner: '你确认',
                status: pbStepEvidence('asset_quality') ? 'done' : 'todo',
                result: pbStepEvidence('asset_quality') || '还没有确认账面净资产是否可靠。',
                prompt: '检查固定资产、在建工程、存货、应收、商誉/无形资产和减值准备，写一句是否需要折价。',
                required: true
            },
            {
                key: 'cross_check',
                title: '5. 侧面印证',
                owner: '你确认',
                status: pbStepEvidence('cross_check') ? 'done' : 'todo',
                result: pbStepEvidence('cross_check') || '还没有用其他估值方法验证 PB 方向。',
                prompt: '至少写一种侧验：EV/EBITDA、DCF、PE/PEG、PCF 或产能重置成本。若结论冲突，写冲突来源。',
                required: true
            },
            {
                key: 'target_pb',
                title: '6. 目标 PB 定稿',
                owner: '系统约束 + 你确认',
                status: pbStepEvidence('target_pb') ? 'done' : 'todo',
                result: pbStepEvidence('target_pb') || '还没有解释目标 PB 如何从历史分位和质量调整推出来。',
                prompt: '把前五步压缩成目标 PB 逻辑：基准 PB 是多少，因质地/周期/资产质量上调还是下调，什么情况失效。',
                required: true
            }
        ];
    }

    function pbProcessGate() {
        const steps = pbProcessSteps();
        if (!steps.length) return { ok: true, missing: [], blockers: [] };
        const missing = steps.filter((step) => step.required && step.status !== 'done');
        const blockers = steps.filter((step) => step.status === 'blocked');
        const next = blockers[0] || missing[0] || null;
        return { ok: missing.length === 0 && blockers.length === 0, missing, blockers, next };
    }

    function clampPbProcessStepIndex() {
        const steps = pbProcessSteps();
        if (!steps.length) {
            state.pbProcessStepIndex = 0;
            return steps;
        }
        const firstOpen = steps.findIndex((step) => step.status !== 'done');
        const preferred = Number.isFinite(Number(state.pbProcessStepIndex)) ? Number(state.pbProcessStepIndex) : 0;
        state.pbProcessStepIndex = Math.max(0, Math.min(preferred, steps.length - 1));
        if (firstOpen >= 0 && state.pbProcessStepIndex > firstOpen) {
            state.pbProcessStepIndex = firstOpen;
        }
        return steps;
    }

    function pbStepMetricFields(stepKey) {
        const f = state.facts || {};
        const currentPb = f.pb_history?.current_pb ?? f.pb;
        const map = {
            history_percentile: [
                { key: 'current_pb', label: '当前 PB', value: fmtNumber(currentPb, 2), readonly: true },
                { key: 'pb_percentile', label: '历史 PB 分位', value: f.pb_history?.percentile_label || '-', readonly: true },
                { key: 'pb_median', label: '历史 PB 中位', value: fmtNumber(f.pb_history?.median, 2), readonly: true }
            ],
            quality: [
                { key: 'roe_ttm', label: 'ROE TTM', value: fmtPct(f.roe_ttm), readonly: true },
                { key: 'revenue_growth', label: '收入增长', value: fmtPct(f.revenue_growth), readonly: true },
                { key: 'quality_note', label: '质地指标补充', placeholder: '如 ROIC、现金流含金量、负债结构，可跳过' }
            ],
            cycle: [
                { key: 'cycle_price', label: '产品价格/价差', placeholder: '如价格处于历史低位/中位/高位，可跳过' },
                { key: 'cycle_rate', label: '开工率/库存', placeholder: '如开工率、库存、供需位置，可跳过' },
                { key: 'cycle_roe', label: 'ROE 是否正常化', value: fmtPct(f.roe_ttm), readonly: true }
            ],
            asset_quality: [
                { key: 'bvps_ref', label: '每股净资产参考', value: fmtNumber(f.bvps, 2), readonly: true },
                { key: 'asset_impairment', label: '减值/商誉/存货风险', placeholder: '如无数据可跳过' },
                { key: 'asset_discount', label: '是否需要折价', placeholder: '例如账面资产需折价 10%，可跳过' }
            ],
            cross_check: [
                { key: 'pe_ttm', label: 'PE TTM', value: fmtNumber(f.pe_ttm, 2), readonly: true },
                { key: 'pcf_ttm', label: 'PCF TTM', value: fmtNumber(f.pcf_ttm, 2), readonly: true },
                { key: 'cross_method', label: '侧验方法', placeholder: 'EV/EBITDA、DCF、PE/PEG、PCF、重置成本，可跳过' }
            ],
            target_pb: [
                { key: 'target_pb_value', label: '目标 PB', assumption_key: 'target_pb', value: currentUiAssumptions().target_pb ?? '' },
                { key: 'base_pb', label: '基准 PB', placeholder: '如历史中位、当前 PB、同行中枢，可跳过' },
                { key: 'pb_fail_condition', label: '失效条件', placeholder: '什么事实出现后目标 PB 要重算，可跳过' }
            ]
        };
        return map[stepKey] || [];
    }

    function pbMetricEvidenceKey(stepKey, metricKey) {
        return `pb_metric_${stepKey}_${metricKey}`;
    }

    function pbMetricValue(stepKey, metric) {
        if (metric.assumption_key) {
            const value = currentUiAssumptions()[metric.assumption_key];
            return value === null || value === undefined ? '' : value;
        }
        return currentAssumptionEvidence()[pbMetricEvidenceKey(stepKey, metric.key)] || metric.value || '';
    }

    function pbMetricSummary(stepKey) {
        const parts = [];
        pbStepMetricFields(stepKey).forEach((metric) => {
            if (metric.readonly) return;
            const value = pbMetricValue(stepKey, metric);
            if (value !== null && value !== undefined && String(value).trim()) {
                parts.push(`${metric.label}: ${String(value).trim()}`);
            } else if (pbStepSkipReason(`${stepKey}_${metric.key}`)) {
                parts.push(`${metric.label}: 跳过(${pbStepSkipReason(`${stepKey}_${metric.key}`)})`);
            }
        });
        return parts.join('；');
    }

    function pbStepConclusionPlaceholder(step) {
        if (step.key === 'history_percentile' && !pbHistoryIsUsable()) {
            return '写清为什么先跳过历史 PB 分位，比如数据源未取到、样本不足，后续只能形成临时 PB 结论。';
        }
        if (step.key === 'target_pb') {
            return '输入最终 PB 推导结论：基准 PB、上调/下调理由、目标 PB、失效条件。';
        }
        return '输入这一张卡片的结论；指标可以跳过，但结论要能支撑下一步。';
    }

    function renderPbStepMetric(step, metric) {
        const value = pbMetricValue(step.key, metric);
        if (metric.readonly) {
            return `
                <div class="pb-metric readonly">
                    <span>${escapeHtml(metric.label)}</span>
                    <strong>${escapeHtml(value || '-')}</strong>
                </div>
            `;
        }
        const skipKey = `${step.key}_${metric.key}`;
        const skipped = pbStepSkipReason(skipKey);
        return `
            <div class="pb-metric input ${skipped ? 'skipped' : ''}">
                <label>${escapeHtml(metric.label)}
                    <input data-pb-metric="${escapeAttr(metric.key)}"
                        data-pb-step-key="${escapeAttr(step.key)}"
                        ${metric.assumption_key ? `data-pb-assumption="${escapeAttr(metric.assumption_key)}"` : ''}
                        value="${escapeAttr(skipped ? '' : value)}"
                        placeholder="${escapeAttr(metric.placeholder || '可输入，也可跳过')}">
                </label>
                <button type="button" data-pb-skip-metric="${escapeAttr(metric.key)}" data-pb-step-key="${escapeAttr(step.key)}">${skipped ? '已跳过' : '跳过'}</button>
                ${skipped ? `<em>${escapeHtml(skipped)}</em>` : ''}
            </div>
        `;
    }

    function renderPbProcess(plan) {
        const steps = clampPbProcessStepIndex();
        if (!steps.length) return '';
        const gate = pbProcessGate();
        const active = steps[state.pbProcessStepIndex] || steps[0];
        const progress = steps.length ? Math.round((steps.filter((step) => step.status === 'done').length / steps.length) * 100) : 0;
        const stepConclusion = pbStepEvidence(active.key);
        const metricSummary = pbMetricSummary(active.key);
        const stepBlocked = active.status === 'blocked';
        return `
            <div class="pb-process">
                <div class="pb-process-head">
                    <div>
                        <span>PB 推导流程</span>
                        <strong>${gate.ok ? 'PB 已闭环，下一步才开始每股净资产、PE、PCF 等交叉验证。' : `当前只处理「${escapeHtml(active.title)}」，完成后再进入下一张卡片。`}</strong>
                    </div>
                    <div class="pill ${gate.ok ? 'ok' : 'warn'}">${gate.ok ? '可测算' : '待补'}</div>
                </div>
                <div class="pb-flow-progress"><i style="width:${progress}%"></i></div>
                <div class="pb-flow-layout">
                    <div class="pb-step-nav">
                        ${steps.map((step, idx) => `
                            <button type="button"
                                class="${idx === state.pbProcessStepIndex ? 'active' : ''} ${escapeAttr(step.status)}"
                                data-pb-jump="${idx}"
                                ${idx > state.pbProcessStepIndex && step.status !== 'done' ? 'disabled' : ''}>
                                <span>${idx + 1}</span>
                                <strong>${escapeHtml(step.title.replace(/^\d+\.\s*/, ''))}</strong>
                            </button>
                        `).join('')}
                    </div>
                    <div class="pb-step-card ${escapeAttr(active.status)}">
                        <div class="pb-step-main">
                            <span>${escapeHtml(active.owner)} · 第 ${state.pbProcessStepIndex + 1} / ${steps.length} 张</span>
                            <strong>${escapeHtml(active.title)}</strong>
                            <p>${escapeHtml(active.result)}</p>
                            <em>${escapeHtml(active.prompt)}</em>
                        </div>
                        <div class="pb-metric-grid">
                            ${pbStepMetricFields(active.key).map((metric) => renderPbStepMetric(active, metric)).join('')}
                        </div>
                        ${metricSummary ? `<div class="pb-metric-summary">已填/跳过指标：${escapeHtml(metricSummary)}</div>` : ''}
                        <label class="pb-step-conclusion">
                            本步结论
                            <textarea data-pb-step="${escapeAttr(active.key)}" placeholder="${escapeAttr(pbStepConclusionPlaceholder(active))}">${escapeHtml(stepConclusion)}</textarea>
                        </label>
                        <div class="pb-card-actions">
                            <button type="button" data-prev-pb-step ${state.pbProcessStepIndex <= 0 ? 'disabled' : ''}>上一张</button>
                            ${stepBlocked ? `<button type="button" data-pb-skip-step="${escapeAttr(active.key)}">缺数据，写原因后继续</button>` : ''}
                            <button type="button" class="primary" data-next-pb-step>${state.pbProcessStepIndex >= steps.length - 1 ? '完成 PB，开始交叉验证' : '保存并下一张'}</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    function setPbProcessStep(index) {
        const steps = pbProcessSteps();
        if (!steps.length) return;
        const next = Math.max(0, Math.min(Number(index) || 0, steps.length - 1));
        state.pbProcessStepIndex = next;
        renderGuidedAssumptions();
        scheduleCaseStateSave();
    }

    function syncPbMetricInput(input) {
        if (!input) return;
        const stepKey = input.dataset.pbStepKey;
        const metricKey = input.dataset.pbMetric;
        const value = input.value.trim();
        const assumptionKey = input.dataset.pbAssumption;
        if (assumptionKey && assumptionMap[assumptionKey]) {
            const target = $(assumptionMap[assumptionKey]);
            if (target) target.value = value;
            state.assumptionEvidenceDrafts[pbMetricEvidenceKey(stepKey, metricKey)] = value;
        } else {
            state.assumptionEvidenceDrafts[pbMetricEvidenceKey(stepKey, metricKey)] = value;
        }
        state.assumptionEvidenceDrafts[pbStepSkipKey(`${stepKey}_${metricKey}`)] = '';
        invalidateFrom('assumptions', false);
        renderCoachFocus();
        renderInlineAnnotations();
    }

    function skipPbMetric(stepKey, metricKey) {
        const key = pbStepSkipKey(`${stepKey}_${metricKey}`);
        const alreadySkipped = Boolean(state.assumptionEvidenceDrafts[key] || currentAssumptionEvidence()[key]);
        state.assumptionEvidenceDrafts[pbMetricEvidenceKey(stepKey, metricKey)] = '';
        state.assumptionEvidenceDrafts[key] = alreadySkipped ? '' : '已跳过';
        invalidateFrom('assumptions', false);
        renderGuidedAssumptions();
    }

    function skipBlockedPbStep(stepKey) {
        state.assumptionEvidenceDrafts[pbStepSkipKey(stepKey)] = pbStepSkipReason(stepKey) ? '' : '系统未取到足够数据，先形成临时结论，后续补数据复核。';
        invalidateFrom('assumptions', false);
        renderGuidedAssumptions();
    }

    function advancePbStep() {
        const steps = pbProcessSteps();
        if (!steps.length) return true;
        const active = steps[state.pbProcessStepIndex] || steps[0];
        const conclusionInput = document.querySelector(`[data-pb-step="${cssEscape(active.key)}"]`);
        const conclusion = (conclusionInput?.value || pbStepEvidence(active.key) || '').trim();
        if (active.status === 'blocked' && !pbStepSkipReason(active.key)) {
            setStatus('这一步缺系统数据。请先写明跳过原因，再继续。', 'warn');
            return false;
        }
        if (!conclusion && (active.key !== 'history_percentile' || !pbHistoryIsUsable())) {
            setStatus('指标可以跳过，但本步结论必须写一句再进入下一张卡片。', 'warn');
            conclusionInput?.focus();
            return false;
        }
        if (conclusion) {
            state.assumptionEvidenceDrafts[pbStepEvidenceKey(active.key)] = conclusion;
            if (active.key === 'target_pb') {
                const logicInput = document.querySelector('[data-assumption-logic="target_pb"]');
                if (logicInput) logicInput.value = conclusion;
                state.assumptionEvidenceDrafts.target_pb = conclusion;
                syncAssumptionLogicFromRows();
            }
        }
        invalidateFrom('assumptions', false);
        const nextIndex = state.pbProcessStepIndex + 1;
        if (nextIndex < steps.length) {
            setPbProcessStep(nextIndex);
            setStatus(`已保存「${active.title}」，进入下一张 PB 卡片。`, 'ok');
            return false;
        }
        renderGuidedAssumptions();
        const gate = pbProcessGate();
        if (!gate.ok) {
            const first = gate.next || gate.missing[0] || gate.blockers[0];
            const idx = steps.findIndex((step) => step.key === first?.key);
            if (idx >= 0) state.pbProcessStepIndex = idx;
            renderGuidedAssumptions();
            setStatus(`PB 还没有闭环，请先补「${first?.title || 'PB 推导流程'}」。`, 'warn');
            return false;
        }
        setStatus('PB 推导完成。现在开始每股净资产、PE、PCF 等交叉验证。', 'ok');
        return true;
    }

    function cleanAssumptionFields(items) {
        const out = [];
        asArray(items).forEach((item) => {
            const key = String(item || '').trim();
            if (assumptionMap[key] && !out.includes(key)) out.push(key);
        });
        return out;
    }

    function methodFieldGroups() {
        const plan = currentAnchorPlan();
        const defaults = defaultMethodFields[plan.primary_method] || defaultMethodFields.pe;
        const primary = cleanAssumptionFields(plan.primary_fields).length ? cleanAssumptionFields(plan.primary_fields) : cleanAssumptionFields(defaults.primary);
        const supporting = cleanAssumptionFields(plan.supporting_fields).filter((key) => !primary.includes(key));
        const secondary = cleanAssumptionFields(plan.secondary_fields || defaults.secondary).filter((key) => !primary.includes(key) && !supporting.includes(key));
        return { primary, supporting, secondary };
    }

    function methodFieldRole(field) {
        const groups = methodFieldGroups();
        if (groups.primary.includes(field)) return 'primary';
        if (groups.supporting.includes(field)) return 'supporting';
        if (groups.secondary.includes(field)) return 'secondary';
        return 'extra';
    }

    function methodFieldRoleLabel(role) {
        return {
            primary: '主锚',
            supporting: '支撑',
            secondary: '辅助验证',
            extra: '暂不优先'
        }[role] || '暂不优先';
    }

    function visibleAssumptionSteps() {
        if (!state.guide && !(state.currentCase?.assumptions || []).length) return [];
        const guideSteps = Array.isArray(state.guide?.assumption_steps) ? state.guide.assumption_steps : [];
        const keyed = new Map();
        guideSteps.forEach((step) => {
            const key = String(step?.key || '').trim();
            if (key && assumptionMap[key] && !keyed.has(key)) keyed.set(key, step);
        });
        const values = currentUiAssumptions();
        const groups = methodFieldGroups();
        const focusedOrder = [...groups.primary, ...groups.supporting, ...groups.secondary];
        focusedOrder.forEach((key) => {
            if (!assumptionMap[key] || keyed.has(key)) return;
            if (values[key] === undefined && !['eps', 'bvps', 'cashflow_ps'].includes(key)) return;
            keyed.set(key, {
                key,
                label: assumptionLabel(key),
                suggested_value: values[key],
                unit: percentKeys.has(key) ? '%' : '',
                why: '这是当前估值模型会直接使用的关键假设，请写清楚来源和适用边界。',
                question: '这个数字来自历史分位、同行比较、财报趋势、研报，还是你的手工判断？',
                risk: '没有依据的数字会让后续情景测算显得精确，但结论不可复盘。'
            });
        });
        const ordered = [];
        focusedOrder.forEach((key) => {
            if (keyed.has(key)) ordered.push(keyed.get(key));
        });
        Array.from(keyed.values()).forEach((step) => {
            if (!ordered.some((item) => item.key === step.key)) ordered.push(step);
        });
        const exclude = new Set();
        if (String(currentAnchorPlan().primary_method || '').toLowerCase() === 'pb' && pbProcessGate().ok) {
            exclude.add('target_pb');
        }
        return ordered.filter((step) => assumptionMap[step.key] && !exclude.has(step.key)).slice(0, 8);
    }

    function clampAssumptionStepIndex() {
        const plan = currentAnchorPlan();
        if (String(plan.primary_method || '').toLowerCase() === 'pb' && !pbProcessGate().ok) {
            state.assumptionStepIndex = 0;
            return [];
        }
        const steps = visibleAssumptionSteps();
        if (!steps.length) {
            state.assumptionStepIndex = 0;
            return steps;
        }
        state.assumptionStepIndex = Math.max(0, Math.min(state.assumptionStepIndex, steps.length - 1));
        return steps;
    }

    function focusAssumptionStep(index) {
        const steps = visibleAssumptionSteps();
        if (!steps.length) {
            state.assumptionStepIndex = 0;
            renderGuidedAssumptions();
            return;
        }
        state.assumptionStepIndex = Math.max(0, Math.min(Number(index) || 0, steps.length - 1));
        const key = steps[state.assumptionStepIndex]?.key;
        const input = $(assumptionMap[key]);
        if (input) {
            input.focus({ preventScroll: true });
            input.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
        if ($('coachField')) $('coachField').value = key;
        renderGuidedAssumptions();
        renderCoachFocus();
    }

    function assumptionEvidenceFor(key) {
        return currentAssumptionEvidence()[key] || savedAssumptionEvidence()[key] || '';
    }

    function assumptionSkipKey(key) {
        return `assumption_skip_${key}`;
    }

    function assumptionSkipReason(key) {
        return (currentAssumptionEvidence()[assumptionSkipKey(key)] || '').trim();
    }

    function assumptionStepHandled(step) {
        const key = step?.key || '';
        return Boolean(key && assumptionEvidenceFor(key));
    }

    function firstIncompleteAssumptionStep() {
        return visibleAssumptionSteps().find((step) => !assumptionStepHandled(step)) || null;
    }

    function activeAssumptionStep() {
        const steps = visibleAssumptionSteps();
        return steps[state.assumptionStepIndex] || steps[0] || null;
    }

    function skipActiveAssumptionMetric() {
        const step = activeAssumptionStep();
        if (!step?.key) return;
        const key = assumptionSkipKey(step.key);
        const skipped = Boolean(state.assumptionEvidenceDrafts[key] || currentAssumptionEvidence()[key]);
        state.assumptionEvidenceDrafts[key] = skipped ? '' : '指标暂不输入，先写结论约束。';
        const input = document.querySelector(`[data-guided-value="${cssEscape(step.key)}"]`);
        if (input && !skipped) input.value = '';
        if (input) syncGuidedValue(step.key, input.value);
        renderGuidedAssumptions();
    }

    function advanceAssumptionStep() {
        const step = activeAssumptionStep();
        if (!step?.key) return true;
        const valueInput = document.querySelector(`[data-guided-value="${cssEscape(step.key)}"]`);
        const evidenceInput = document.querySelector(`[data-assumption-evidence="${cssEscape(step.key)}"]`);
        const value = (valueInput?.value || '').trim();
        const evidence = (evidenceInput?.value || assumptionEvidenceFor(step.key) || '').trim();
        if (!value && !assumptionSkipReason(step.key)) {
            setStatus('这一项可以不填指标，但请先点“跳过指标”，再写结论。', 'warn');
            valueInput?.focus();
            return false;
        }
        if (!evidence) {
            setStatus('请先写这一项的交叉验证结论，再进入下一张卡片。', 'warn');
            evidenceInput?.focus();
            return false;
        }
        state.assumptionEvidenceDrafts[step.key] = evidence;
        const logicInput = document.querySelector(`[data-assumption-logic="${cssEscape(step.key)}"]`);
        if (logicInput) logicInput.value = evidence;
        syncAssumptionLogicFromRows();
        if (state.assumptionStepIndex < visibleAssumptionSteps().length - 1) {
            focusAssumptionStep(state.assumptionStepIndex + 1);
            return false;
        }
        return true;
    }

    function renderGuidedAssumptions() {
        const el = $('assumptionGuidePanel');
        if (!el) return;
        const plan = currentAnchorPlan();
        const steps = clampAssumptionStepIndex();
        if (!state.guide && !steps.length) {
            el.innerHTML = '<div class="empty-state">先在 02 生成估值路径；03 会根据主方法展示应该优先推导的估值锚。</div>';
            renderInlineAnnotations();
            return;
        }
        const active = steps[state.assumptionStepIndex] || steps[0];
        const groups = methodFieldGroups();
        const progress = steps.length ? Math.round(((state.assumptionStepIndex + 1) / steps.length) * 100) : 0;
        const factorRows = asArray(plan.factors).slice(0, 6);
        const derivation = asArray(plan.derivation_steps).slice(0, 4);
        const isPbPrimary = String(plan.primary_method || '').toLowerCase() === 'pb';
        const pbGate = pbProcessGate();
        const roleTags = [
            ...groups.primary.map((key) => ({ key, role: 'primary' })),
            ...groups.supporting.map((key) => ({ key, role: 'supporting' })),
            ...groups.secondary.map((key) => ({ key, role: 'secondary' }))
        ].filter((item) => !isPbPrimary || pbGate.ok || item.key === 'target_pb');
        const showCrossValidation = !isPbPrimary || pbGate.ok;
        el.innerHTML = `
            <div class="anchor-guide-head">
                <div>
                    <span>${escapeHtml(plan.primary_method_name || plan.primary_method || '主估值锚')}</span>
                    <strong>${escapeHtml(plan.headline || '围绕主估值方法推导关键假设。')}</strong>
                    ${plan.formula ? `<em>${escapeHtml(plan.formula)}</em>` : ''}
                </div>
                <div class="anchor-guide-values">
                    <div><span>${escapeHtml(plan.base_anchor?.label || '基准锚')}</span><strong>${escapeHtml(plan.base_anchor?.value ?? '-')}</strong></div>
                    <div><span>${escapeHtml(plan.suggested_anchor?.label || plan.anchor_label || '建议锚')}</span><strong>${escapeHtml(plan.suggested_anchor?.value ?? '-')}</strong></div>
                </div>
            </div>
            <div class="anchor-role-row">
                ${roleTags.map((item) => `<button type="button" data-focus-assumption="${escapeAttr(item.key)}" class="${escapeAttr(item.role)}">${escapeHtml(methodFieldRoleLabel(item.role))} · ${escapeHtml(assumptionLabel(item.key))}</button>`).join('')}
            </div>
            <div class="anchor-split">
                <div class="anchor-derivation">
                    ${derivation.length ? derivation.map((item, idx) => `
                        <div class="anchor-step">
                            <span>${idx + 1}</span>
                            <strong>${escapeHtml(item.title || '')}</strong>
                            <p>${escapeHtml(item.detail || '')}</p>
                        </div>
                    `).join('') : `
                        <div class="anchor-step">
                            <span>1</span>
                            <strong>先找基准，再调价格</strong>
                            <p>用当前值、同行均值或历史分位作为起点，再按质量、成长和风险调整。</p>
                        </div>
                    `}
                    <div class="anchor-ai-role">
                        <div><b>程序</b><p>${escapeHtml(plan.program_role || '固定公式、字段和硬性校验。')}</p></div>
                        <div><b>AI</b><p>${escapeHtml(plan.ai_role || '解释证据、追问逻辑和生成反证条件。')}</p></div>
                    </div>
                </div>
                <div class="anchor-factor-list">
                    ${factorRows.length ? factorRows.map((item) => `
                        <div class="anchor-factor">
                            <div><strong>${escapeHtml(item.label || '')}</strong><span>${escapeHtml(item.weight ?? '-')}%</span></div>
                            <p>${escapeHtml(item.direction || item.pricing_rule || '')}</p>
                            ${item.evidence ? `<em>${escapeHtml(item.evidence)}</em>` : ''}
                        </div>
                    `).join('') : '<div class="empty-state">生成路径后会显示因素权重和调价依据。</div>'}
                </div>
            </div>
            ${renderPbProcess(plan)}
            ${isPbPrimary && !pbGate.ok ? `
                <div class="cross-validation-locked">
                    <strong>先完成 PB 主推导</strong>
                    <p>每股净资产、PE、PCF、DCF 等只做交叉验证。PB 卡片闭环后，这里才会进入下一组验证卡片。</p>
                </div>
            ` : ''}
            ${active && showCrossValidation ? `
                <div class="assumption-flow-head">
                    <div>
                        <span>${isPbPrimary ? '交叉验证项' : '当前推导项'} · ${escapeHtml(methodFieldRoleLabel(methodFieldRole(active.key)))}</span>
                        <strong>${escapeHtml(active.label || assumptionLabel(active.key))} ${active.suggested_value !== undefined ? `= ${escapeHtml(active.suggested_value)}${escapeHtml(active.unit || '')}` : ''}</strong>
                    </div>
                    <div class="assumption-progress"><i style="width:${progress}%"></i></div>
                </div>
                <div class="assumption-stepper">
                    ${steps.map((step, idx) => `
                    <button type="button" class="${idx === state.assumptionStepIndex ? 'active' : ''} ${assumptionEvidenceFor(step.key) ? 'done' : ''}" data-assumption-step="${idx}">
                            <span>${idx + 1}</span>${escapeHtml(step.label || assumptionLabel(step.key))}
                        </button>
                    `).join('')}
                </div>
                <div class="guided-assumption-card">
                    <div class="guided-copy">
                        <p><b>为什么：</b>${escapeHtml(active.why || '请写清楚这个假设为什么成立。')}</p>
                        <p><b>验证：</b>${escapeHtml(active.question || '这个数字来自哪里？')}</p>
                        <p><b>风险：</b>${escapeHtml(active.risk || '没有证据的假设不可复盘。')}</p>
                        ${renderReferenceChips(active.key, `guide:${active.key}`)}
                    </div>
                    <div class="guided-entry">
                        <label>${escapeHtml(active.label || assumptionLabel(active.key))}
                            <input data-guided-value="${escapeAttr(active.key)}" value="${escapeAttr(currentUiAssumptions()[active.key] ?? active.suggested_value ?? '')}" inputmode="decimal">
                        </label>
                        <label>推导依据
                            <textarea data-assumption-evidence="${escapeAttr(active.key)}" placeholder="基准来自哪里？为什么上调/下调？什么事实会推翻？">${escapeHtml(assumptionEvidenceFor(active.key))}</textarea>
                        </label>
                        ${assumptionSkipReason(active.key) ? `<div class="skip-note">已跳过指标：${escapeHtml(assumptionSkipReason(active.key))}</div>` : ''}
                        <div class="button-row compact">
                            <button type="button" data-prev-assumption>上一项</button>
                            <button type="button" data-skip-assumption>${assumptionSkipReason(active.key) ? '取消跳过' : '跳过指标'}</button>
                            <button type="button" data-coach-assumption>AI 追问</button>
                            <button type="button" class="primary" data-next-assumption>${state.assumptionStepIndex >= steps.length - 1 ? '保存假设' : '下一项'}</button>
                        </div>
                    </div>
                </div>
            ` : ''}
        `;
        renderInlineAnnotations();
    }

    function syncGuidedValue(key, rawValue) {
        const target = $(assumptionMap[key]);
        if (target) target.value = rawValue;
        invalidateFrom('assumptions', false);
        renderCoachFocus();
    }

    function applyFacts(facts) {
        state.facts = facts || {};
        state.stockCode = (state.facts.stock_code || state.stockCode || '').toString();
        manualKeys.forEach((key) => {
            const input = document.querySelector(`[data-manual="${key}"]`);
            if (!input) return;
            const value = state.facts[key];
            input.value = value === null || value === undefined ? '' : value;
        });
        renderSnapshot();
        renderInlineAnnotations();
    }

    function renderSnapshot() {
        const f = state.facts || {};
        $('mStock').textContent = f.stock_code ? `${f.stock_code} ${f.stock_name || ''}` : '-';
        $('mPrice').textContent = fmtNumber(f.close_price, 2);
        $('mPepb').textContent = `${fmtNumber(f.pe_ttm, 2)} / ${fmtNumber(f.pb, 2)}`;
        $('mPspcf').textContent = `${fmtNumber(f.ps_ttm, 2)} / ${fmtNumber(f.pcf_ttm, 2)}`;
        $('mRoe').textContent = fmtPct(f.roe_ttm);
        $('mIndustry').textContent = f.third_industry || f.second_industry || f.first_industry || '-';
        renderDataDates(f);
        renderDataQuality();
        renderIndustryPeers(f);
        renderCaseHeader();
    }

    function renderDataDates(f) {
        const items = [
            ['行情', f.quote_date],
            ['估值指标', f.valuation_date],
            ['财务指标', f.report_date],
            ['利润表', f.income_report_date],
            ['分红事件', f.dividend_date]
        ];
        $('dataDates').innerHTML = items.map(([label, value]) => `
            <div class="date-chip">
                <span>${escapeHtml(label)}</span>
                <strong>${escapeHtml(value || '未取到')}</strong>
            </div>
        `).join('');
    }

    function renderIndustryPeers(f) {
        const el = $('industryPeerStats');
        if (!el) return;
        const peer = f?.industry_peer_stats || {};
        const metrics = Array.isArray(peer.metrics) ? peer.metrics : [];
        if (!metrics.length) {
            el.innerHTML = '<div class="empty-state">未取到同行业参考。请确认行业字段和聚源估值/财务表可用。</div>';
            return;
        }
        const levelLabel = { third: '三级行业', second: '二级行业', first: '一级行业' }[peer.industry_level] || '行业';
        const samples = (peer.sample_stocks || []).slice(0, 6).join('、');
        el.innerHTML = `
            <div class="peer-head">
                <div>
                    <strong>同行业参考</strong>
                    <span>${escapeHtml(levelLabel)}：${escapeHtml(peer.industry_name || '-')} · 样本 ${escapeHtml(peer.sample_count ?? '-')} · ${escapeHtml(peer.as_of || '')}</span>
                </div>
                ${samples ? `<em>${escapeHtml(samples)}</em>` : ''}
            </div>
            <div class="peer-table-wrap">
                <table class="peer-table">
                    <thead>
                        <tr>
                            <th>指标</th>
                            <th>本股票</th>
                            <th>低</th>
                            <th>平均</th>
                            <th>高</th>
                            <th>样本</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${metrics.map((item) => `
                            <tr>
                                <td>${escapeHtml(item.label || item.key)}</td>
                                <td>${escapeHtml(fmtMetric(f[item.key], item.format))}</td>
                                <td>${escapeHtml(fmtMetric(item.min, item.format))}</td>
                                <td>${escapeHtml(fmtMetric(item.avg, item.format))}</td>
                                <td>${escapeHtml(fmtMetric(item.max, item.format))}</td>
                                <td>${escapeHtml(item.count ?? '-')}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }

    function renderDataQuality() {
        const quality = state.guide?.data_quality || state.currentCase?.state?.data_quality || {};
        const score = Number(quality.score);
        const width = Number.isFinite(score) ? Math.max(0, Math.min(100, score)) : 0;
        $('qualityScore').textContent = Number.isFinite(score) ? `${width}%` : '-';
        $('qualityBar').style.width = `${width}%`;
    }

    function renderWarnings(warnings) {
        const el = $('warningList');
        if (!warnings || !warnings.length) {
            el.classList.remove('active');
            el.innerHTML = '';
            return;
        }
        el.classList.add('active');
        el.innerHTML = warnings.map((item) => `<div>${escapeHtml(item)}</div>`).join('');
    }

    function renderCaseHeader() {
        const c = state.currentCase;
        const f = state.facts || {};
        $('caseLabel').textContent = c ? `案例 #${c.id} · ${c.status || 'draft'}` : '未创建工作纸';
        $('caseTitle').textContent = c
            ? `${c.stock_code} ${c.stock_name || ''} · ${c.valuation_date || ''}`
            : (f.stock_code ? `${f.stock_code} ${f.stock_name || ''}` : '先拉数据或输入手工字段');
    }

    function asList(value) {
        if (Array.isArray(value)) return value;
        if (value === null || value === undefined || value === '') return [];
        return [value];
    }

    function numericAssumption(key) {
        const value = currentUiAssumptions()[key];
        const n = Number(value);
        return Number.isFinite(n) ? n : null;
    }

    function currentAssumptionReview() {
        const review =
            state.currentCase?.state?.assumption_review ||
            state.currentCase?.state?.tabs?.assumptions?.review ||
            null;
        return review && typeof review === 'object' ? review : {};
    }

    function normalizeAssumptionField(value) {
        const field = String(value || '').trim();
        return assumptionMap[field] ? field : '';
    }

    function inferAssumptionFieldFromText(...parts) {
        const text = parts.map((part) => String(part || '')).filter(Boolean).join(' ');
        if (!text) return '';
        return assumptionRowOrder.find((key) => {
            const label = assumptionLabel(key);
            return text.includes(key) || (label && text.includes(label));
        }) || '';
    }

    function relatedAssumptionField(item) {
        if (!item || typeof item !== 'object') return '';
        const candidates = [
            item.field,
            item.assumption_key,
            item.linked_field,
            item.linked_assumption_key,
            item.related_field,
            item.suggested_revision?.field
        ];
        for (const candidate of candidates) {
            const field = normalizeAssumptionField(candidate);
            if (field) return field;
        }
        return inferAssumptionFieldFromText(
            item.label,
            item.title,
            item.question,
            item.gap,
            item.plain_take,
            item.reason,
            item.trigger_condition,
            item.suggested_action
        );
    }

    function reviewForField(field) {
        return asList(currentAssumptionReview().assumption_reviews).find((item) => relatedAssumptionField(item) === field) || null;
    }

    function annotationLevelFromReview(item) {
        const status = String(item?.status || '').toLowerCase();
        if (status === 'conflict') return 1;
        if (['too_optimistic', 'missing', 'needs_evidence', 'needs_work', 'high_risk'].includes(status)) return 2;
        if (status === 'too_conservative') return 3;
        return 0;
    }

    function localHardAssumptionIssues() {
        const issues = [];
        const discount = numericAssumption('discount_rate');
        const terminal = numericAssumption('terminal_growth');
        const years = numericAssumption('dcf_years');
        if (discount !== null && terminal !== null && discount <= terminal) {
            issues.push({
                field: 'discount_rate',
                label: assumptionLabel('discount_rate'),
                value: discount,
                status: 'hard_block',
                level: 1,
                plain_take: '折现率必须高于终值增长，否则 DCF 终值公式失效。',
                reason: `折现率 ${discount}%，终值增长 ${terminal}%。`,
                suggested_action: '先把折现率调高，或把终值增长下修，再进入情景测算。'
            });
            issues.push({
                field: 'terminal_growth',
                label: assumptionLabel('terminal_growth'),
                value: terminal,
                status: 'hard_block',
                level: 1,
                plain_take: '终值增长不能高于或等于折现率。',
                reason: `终值增长 ${terminal}%，折现率 ${discount}%。`,
                suggested_action: '长期终值增长应低于折现率，并写清楚宏观增长依据。'
            });
        }
        if (years !== null && years <= 0) {
            issues.push({
                field: 'dcf_years',
                label: assumptionLabel('dcf_years'),
                value: years,
                status: 'hard_block',
                level: 1,
                plain_take: 'DCF 年数必须大于 0。',
                reason: '没有有效预测期，现金流折现无法计算。',
                suggested_action: '把 DCF 年数改为 3、5 或 10 等可解释的预测窗口。'
            });
        }
        return issues;
    }

    function assumptionAnnotations() {
        const byField = new Map();
        localHardAssumptionIssues().forEach((item) => byField.set(item.field, item));
        asList(currentAssumptionReview().assumption_reviews).forEach((item) => {
            const field = relatedAssumptionField(item);
            if (!field || byField.has(field)) return;
            const level = annotationLevelFromReview(item);
            if (!level) return;
            byField.set(field, Object.assign({}, item, { field, level }));
        });
        return Array.from(byField.values());
    }

    function levelMeta(level) {
        if (Number(level) === 1) return { className: 'level-1', label: 'Level 1', title: '致命逻辑错误' };
        if (Number(level) === 2) return { className: 'level-2', label: 'Level 2', title: '证据待办' };
        return { className: 'level-3', label: 'Level 3', title: '压力测试' };
    }

    function levelOneBlockers() {
        return assumptionAnnotations().filter((item) => Number(item.level) === 1);
    }

    function hasLevelOneBlockers() {
        return levelOneBlockers().length > 0;
    }

    function assumptionAnnotationFor(field) {
        return assumptionAnnotations().find((item) => item.field === field) || null;
    }

    function fieldMetricChips(field) {
        const f = state.facts || {};
        const peerMetrics = Array.isArray(f.industry_peer_stats?.metrics) ? f.industry_peer_stats.metrics : [];
        const peerByKey = new Map(peerMetrics.map((item) => [item.key, item]));
        const chips = [];
        const push = (label, value, format = 'number') => {
            if (value === null || value === undefined || value === '') return;
            chips.push({ label, text: `${label}=${fmtMetric(value, format)}` });
        };
        if (field === 'target_pe') {
            push('当前PE', f.pe_ttm);
            push('同行PE均值', peerByKey.get('pe_ttm')?.avg);
        } else if (field === 'target_pb') {
            push('当前PB', f.pb);
            push('历史PB分位', f.pb_history?.percentile_label, 'text');
            push('历史PB中位', f.pb_history?.median);
            push('同行PB均值', peerByKey.get('pb')?.avg);
            push('ROE', f.roe_ttm, 'pct');
        } else if (field === 'target_ps') {
            push('当前PS', f.ps_ttm);
            push('同行PS均值', peerByKey.get('ps_ttm')?.avg);
            push('收入增速', f.revenue_growth, 'pct');
        } else if (field === 'target_pcf') {
            push('当前PCF', f.pcf_ttm);
            push('同行PCF均值', peerByKey.get('pcf_ttm')?.avg);
        } else if (field === 'dcf_growth' || field === 'terminal_growth') {
            push('收入增速', f.revenue_growth, 'pct');
            push('同行增速均值', peerByKey.get('revenue_growth')?.avg, 'pct');
            push('ROE', f.roe_ttm, 'pct');
        } else if (field === 'discount_rate') {
            push('ROE', f.roe_ttm, 'pct');
            push('收入增速', f.revenue_growth, 'pct');
        } else if (field === 'target_dividend_yield') {
            push('每股分红', f.dividend_ps);
            push('现价', f.close_price);
        }
        return chips.slice(0, 4);
    }

    function insertComposerText(textarea, text) {
        if (!textarea || !text) return;
        const value = textarea.value || '';
        const prefix = value && !value.endsWith(' ') && !value.endsWith('\n') ? ' ' : '';
        textarea.value = `${value}${prefix}${text} `;
        textarea.focus();
    }

    function renderReferenceChips(field, target) {
        const chips = fieldMetricChips(field);
        if (!chips.length) return '<div class="reference-chips empty">暂无可引用数据</div>';
        return `
            <div class="reference-chips">
                ${chips.map((chip) => `<button type="button" data-reference-chip="${escapeAttr(chip.text)}" data-reference-target="${escapeAttr(target)}">${escapeHtml(chip.label)}</button>`).join('')}
            </div>
        `;
    }

    function assumptionReferenceText(field) {
        const f = state.facts || {};
        const peerMetrics = Array.isArray(f.industry_peer_stats?.metrics) ? f.industry_peer_stats.metrics : [];
        const peerByKey = new Map(peerMetrics.map((item) => [item.key, item]));
        const parts = [];
        const add = (label, value, format = 'number') => {
            if (value === null || value === undefined || value === '') return;
            parts.push(`${label} ${fmtMetric(value, format)}`);
        };
        if (field === 'target_pe') {
            add('当前', f.pe_ttm);
            add('同行均值', peerByKey.get('pe_ttm')?.avg);
        } else if (field === 'target_pb') {
            add('当前', f.pb);
            add('历史分位', f.pb_history?.percentile_label, 'text');
            add('历史中位', f.pb_history?.median);
            add('同行均值', peerByKey.get('pb')?.avg);
            add('ROE', f.roe_ttm, 'pct');
        } else if (field === 'target_ps') {
            add('当前', f.ps_ttm);
            add('同行均值', peerByKey.get('ps_ttm')?.avg);
            add('收入增速', f.revenue_growth, 'pct');
        } else if (field === 'target_pcf') {
            add('当前', f.pcf_ttm);
            add('同行均值', peerByKey.get('pcf_ttm')?.avg);
        } else if (field === 'dcf_growth') {
            add('收入增速', f.revenue_growth, 'pct');
            add('同行增速', peerByKey.get('revenue_growth')?.avg, 'pct');
        } else if (field === 'discount_rate') {
            add('ROE', f.roe_ttm, 'pct');
            add('收入增速', f.revenue_growth, 'pct');
        } else if (field === 'terminal_growth') {
            add('收入增速', f.revenue_growth, 'pct');
            parts.push('长期增速需低于折现率');
        } else if (field === 'target_dividend_yield') {
            add('每股分红', f.dividend_ps);
            add('现价', f.close_price);
        } else if (field === 'eps') {
            add('现价/PE', f.pe_ttm);
        } else if (field === 'bvps') {
            add('现价/PB', f.pb);
        } else if (field === 'cashflow_ps') {
            add('现价/PCF', f.pcf_ttm);
        } else if (field === 'dcf_years') {
            parts.push('常用 3 / 5 / 10');
        }
        return parts.join(' · ') || '-';
    }

    function syncAssumptionLogicFromRows() {
        const lines = [];
        document.querySelectorAll('[data-assumption-logic]').forEach((input) => {
            const key = input.dataset.assumptionLogic;
            const value = input.value.trim();
            if (key && value) lines.push(`${assumptionLabel(key)}：${value}`);
        });
        const logic = $('assumptionLogic');
        if (logic) logic.value = lines.join('\n');
    }

    function setRowLogicFromEvidence(values) {
        const evidence = values || {};
        Object.keys(assumptionMap).forEach((key) => {
            const input = document.querySelector(`[data-assumption-logic="${key}"]`);
            if (input) input.value = evidence[key] || '';
        });
        syncAssumptionLogicFromRows();
    }

    function renderStatusBar() {
        const bar = $('assumptionStatusBar');
        if (!bar) return;
        const annotations = assumptionAnnotations();
        const level1 = annotations.filter((item) => Number(item.level) === 1).length;
        const level2 = annotations.filter((item) => Number(item.level) === 2).length;
        const level3 = annotations.filter((item) => Number(item.level) === 3).length;
        const pending = state.activeCoachJobs;
        const tone = level1 ? 'bad' : level2 ? 'warn' : 'ok';
        const syncText = pending ? `${pending} 项后台验证中` : 'AI 同步完成';
        bar.className = `linter-status-bar ${tone}`;
        bar.setAttribute('aria-expanded', state.assumptionDrawerOpen ? 'true' : 'false');
        bar.innerHTML = `
            <span class="status-dot ${escapeAttr(tone)}"></span>
            <strong>${escapeHtml(syncText)}</strong>
            <span>${level1} 阻断</span>
            <span>${level2} 待补证据</span>
            <span>${level3} 压力测试</span>
        `;
    }

    function renderAnnotationPopover(key, item) {
        const meta = levelMeta(item.level);
        const saved = assumptionEvidenceFor(key);
        const question = item.plain_take || item.reason || '这个假设需要补充证据。';
        return `
            <div class="assumption-lint-popover" data-lint-popover="${escapeAttr(key)}">
                <p>${escapeHtml(question)}</p>
                <input data-inline-rebuttal="${escapeAttr(key)}" value="${escapeAttr(saved)}" placeholder="一句话依据，输入 @ 可引用数据">
                <div class="lint-tag-row">
                    ${rebuttalTags.map((tag) => `<button type="button" data-inline-tag="${escapeAttr(tag)}" data-inline-field="${escapeAttr(key)}">${escapeHtml(tag)}</button>`).join('')}
                    ${fieldMetricChips(key).slice(0, 2).map((chip) => `<button type="button" data-reference-chip="${escapeAttr(chip.text)}" data-reference-target="${escapeAttr(`inline:${key}`)}">@${escapeHtml(chip.label)}</button>`).join('')}
                </div>
                <div class="lint-popover-actions">
                    <span>${escapeHtml(meta.label)} · ${escapeHtml(meta.title)}</span>
                    <button type="button" data-inline-apply="${escapeAttr(key)}">接受建议</button>
                    <button type="button" class="primary" data-inline-ask="${escapeAttr(key)}">异步验证</button>
                </div>
            </div>
        `;
    }

    function renderInlineAnnotations() {
        const annotations = new Map(assumptionAnnotations().map((item) => [item.field, item]));
        assumptionRowOrder.forEach((key) => {
            const row = document.querySelector(`[data-assumption-row="${key}"]`);
            const input = $(assumptionMap[key]);
            const indicator = row?.querySelector('[data-lint-toggle]');
            const reference = document.querySelector(`[data-assumption-reference="${key}"]`);
            if (reference) reference.textContent = assumptionReferenceText(key);
            if (!row || !input || !indicator) return;
            row.classList.remove('level-1', 'level-2', 'level-3', 'active-lint', 'verifying', 'method-primary-row', 'method-support-row', 'method-secondary-row', 'method-extra-row');
            input.classList.remove('level-1', 'level-2', 'level-3');
            row.querySelector('[data-lint-popover]')?.remove();
            const role = methodFieldRole(key);
            row.dataset.methodRole = role;
            row.classList.add({
                primary: 'method-primary-row',
                supporting: 'method-support-row',
                secondary: 'method-secondary-row',
                extra: 'method-extra-row'
            }[role] || 'method-extra-row');
            const item = annotations.get(key);
            const verifying = state.verifyingFields.has(key);
            row.classList.toggle('verifying', verifying);
            if (!item && !verifying) {
                indicator.className = 'lint-indicator ok';
                indicator.title = '点击检查本行假设';
                return;
            }
            if (verifying && !item) {
                indicator.className = 'lint-indicator loading';
                indicator.title = '后台验证中';
                return;
            }
            const meta = levelMeta(item.level);
            row.classList.add(meta.className);
            input.classList.add(meta.className);
            indicator.className = `lint-indicator ${meta.className}${verifying ? ' loading' : ''}`;
            indicator.title = item.plain_take || meta.title;
            if (state.inlinePopoverField === key) {
                row.classList.add('active-lint');
                row.insertAdjacentHTML('afterend', renderAnnotationPopover(key, item));
            }
        });
        renderStatusBar();
        renderAssumptionDrawer();
        renderWorkflowRail();
    }

    function focusInlineAnnotation(field, open = true) {
        if (!assumptionMap[field]) return;
        state.inlinePopoverField = open ? field : '';
        const row = document.querySelector(`[data-assumption-row="${field}"]`);
        if (row) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
        if ($('coachField')) $('coachField').value = field;
        renderInlineAnnotations();
    }

    function renderCoachReferences() {
        const el = $('coachReferenceChips');
        if (!el) return;
        const field = $('coachField')?.value || 'dcf_growth';
        el.innerHTML = renderReferenceChips(field, 'coach');
    }

    function assumptionDisplayValue(field) {
        const value = currentUiAssumptions()[field];
        if (value === null || value === undefined || value === '') return '-';
        return `${value}${percentKeys.has(field) ? '%' : ''}`;
    }

    function drawerIssueLevel(item, fallback = 2) {
        const explicit = Number(item?.level);
        if ([1, 2, 3].includes(explicit)) return explicit;
        const status = String(item?.status || '').toLowerCase();
        if (status === 'hard_block' || status === 'conflict') return 1;
        if (status === 'too_conservative') return 3;
        if (['too_optimistic', 'missing', 'needs_evidence', 'needs_work', 'high_risk'].includes(status)) return 2;
        const severity = String(item?.severity || item?.priority || '').toLowerCase();
        if (severity === 'low') return 3;
        return fallback;
    }

    function makeDrawerIssue(kind, item, fallback = {}) {
        const level = drawerIssueLevel(item, fallback.level || 2);
        const meta = levelMeta(level);
        return {
            kind,
            level,
            className: meta.className,
            tag: fallback.tag || meta.label,
            title: String(fallback.title || item?.title || item?.label || item?.question || item?.gap || ''),
            body: String(fallback.body || item?.plain_take || item?.trigger_condition || item?.why_it_matters || item?.why || item?.source || item?.suggested_source || item?.reason || ''),
            detail: String(fallback.detail || item?.suggested_action || item?.reason || ''),
            raw: item || {}
        };
    }

    function addDrawerIssue(groups, field, issue, unassigned) {
        const normalized = normalizeAssumptionField(field);
        const target = normalized
            ? groups.get(normalized) || {
                field: normalized,
                label: assumptionLabel(normalized),
                value: assumptionDisplayValue(normalized),
                issues: []
            }
            : unassigned;
        const key = [issue.kind, issue.tag, issue.title, issue.body, issue.detail].join('|');
        if (!target.issues.some((item) => item.__key === key)) {
            target.issues.push(Object.assign({ __key: key }, issue));
        }
        if (normalized && !groups.has(normalized)) groups.set(normalized, target);
    }

    function collectAssumptionDrawerGroups() {
        const groups = new Map();
        const unassigned = { field: '', label: '整体检查', value: '-', issues: [] };
        const push = (field, issue) => addDrawerIssue(groups, field, issue, unassigned);
        const review = currentAssumptionReview();

        assumptionAnnotations().forEach((item) => {
            const field = relatedAssumptionField(item);
            const detail = [item.reason, item.suggested_action].filter(Boolean).join('；');
            push(field, makeDrawerIssue('review', item, {
                tag: reviewStatusLabel(item.status),
                title: item.label || assumptionLabel(field),
                body: item.plain_take || item.reason || '',
                detail,
                level: item.level
            }));
        });

        asList(review.evidence_todos).forEach((item) => {
            const field = relatedAssumptionField(item);
            push(field, makeDrawerIssue('evidence', item, {
                tag: priorityLabel(item?.priority),
                title: item?.title || '补证据',
                body: item?.source || '',
                level: item?.priority === 'low' ? 3 : 2
            }));
        });

        asList(review.counter_evidence).forEach((item) => {
            const field = relatedAssumptionField(item);
            push(field, makeDrawerIssue('counter', item, {
                tag: '反证',
                title: item?.title || '反证条件',
                body: item?.trigger_condition || '',
                level: item?.severity === 'low' ? 3 : 2
            }));
        });

        asList(review.key_risks).forEach((item) => {
            const field = relatedAssumptionField(item);
            push(field, makeDrawerIssue('risk', item, {
                tag: '风险',
                title: item?.title || '关键风险',
                body: item?.why_it_matters || item?.reason || '',
                level: item?.severity === 'low' ? 3 : 2
            }));
        });

        asList(state.currentCase?.ai_messages).slice(-8).forEach((msg) => {
            if (msg?.role !== 'assistant' || msg?.payload?.type === 'assumption_review') return;
            const payload = msg.payload || {};
            const baseField = normalizeAssumptionField(msg.related_field) || relatedAssumptionField(payload);
            asList(payload.questions).slice(0, 3).forEach((item) => {
                const field = relatedAssumptionField(item) || baseField;
                push(field, makeDrawerIssue('question', item, {
                    tag: '追问',
                    title: item?.question || String(item || ''),
                    body: item?.why || '',
                    level: 2
                }));
            });
            asList(payload.evidence_gaps).slice(0, 3).forEach((item) => {
                const field = relatedAssumptionField(item) || baseField;
                push(field, makeDrawerIssue('gap', item, {
                    tag: '缺口',
                    title: item?.gap || String(item || ''),
                    body: item?.suggested_source || '',
                    level: 2
                }));
            });
            asList(payload.counter_evidence).slice(0, 2).forEach((item) => {
                const field = relatedAssumptionField(item) || baseField;
                push(field, makeDrawerIssue('coach_counter', item, {
                    tag: '反证',
                    title: item?.title || String(item || ''),
                    body: item?.trigger_condition || '',
                    level: item?.severity === 'low' ? 3 : 2
                }));
            });
        });

        const ordered = assumptionRowOrder
            .map((field) => groups.get(field))
            .filter((group) => group && group.issues.length);
        if (unassigned.issues.length) ordered.push(unassigned);
        return ordered;
    }

    function renderDrawerIssue(item) {
        return `
            <div class="drawer-issue ${escapeAttr(item.className)}">
                <div class="drawer-issue-head">
                    <span>${escapeHtml(item.tag || '')}</span>
                    <strong>${escapeHtml(item.title || '')}</strong>
                </div>
                ${item.body ? `<p>${escapeHtml(item.body)}</p>` : ''}
                ${item.detail && item.detail !== item.body ? `<em>${escapeHtml(item.detail)}</em>` : ''}
            </div>
        `;
    }

    function renderDrawerGroup(group) {
        const field = group.field;
        const saved = field ? assumptionEvidenceFor(field) : '';
        return `
            <section class="drawer-assumption-group ${field ? '' : 'unassigned'}">
                <div class="drawer-assumption-head">
                    <button type="button" data-open-annotation="${escapeAttr(field)}" ${field ? '' : 'disabled'}>
                        <strong>${escapeHtml(group.label)}</strong>
                        <span>${escapeHtml(field ? `当前：${group.value}` : '未能自动归到具体参数')}</span>
                    </button>
                    <span>${group.issues.length}</span>
                </div>
                <div class="drawer-issue-list">
                    ${group.issues.map(renderDrawerIssue).join('')}
                </div>
                ${field ? `
                    <div class="drawer-feedback">
                        <label>
                            我的反馈/依据
                            <textarea data-drawer-feedback="${escapeAttr(field)}" placeholder="写证据、反驳或修正理由">${escapeHtml(saved)}</textarea>
                        </label>
                        <div class="drawer-feedback-actions">
                            <button type="button" data-drawer-save="${escapeAttr(field)}">保存反馈</button>
                            <button type="button" class="primary" data-drawer-ask="${escapeAttr(field)}">带反馈复查</button>
                        </div>
                    </div>
                ` : ''}
            </section>
        `;
    }

    function renderAssumptionDrawer() {
        const drawer = $('assumptionDrawer');
        const list = $('assumptionTodoList');
        if (!drawer || !list) return;
        drawer.classList.toggle('active', state.assumptionDrawerOpen);
        drawer.setAttribute('aria-hidden', state.assumptionDrawerOpen ? 'false' : 'true');
        const groups = collectAssumptionDrawerGroups();
        const total = groups.reduce((sum, group) => sum + group.issues.length, 0);
        const subtitle = $('drawerSubtitle');
        if (subtitle) subtitle.textContent = total ? `${groups.length} 个参数 · ${total} 条检查项` : '暂无待办';
        list.innerHTML = groups.length
            ? groups.map(renderDrawerGroup).join('')
            : '<div class="empty-state">暂无待办。AI 会保持安静。</div>';
        renderCoachThread();
    }

    function renderMethodDecision(guide) {
        const method = guide?.method_decision || {};
        if (!guide || !method.primary_method) {
            $('methodDecision').innerHTML = '<div class="empty-state">拉取数据后生成估值路径，这里会显示主估值锚、辅助验证方法和暂不适合的方法。</div>';
            return;
        }
        $('methodDecision').innerHTML = `
            <div class="method-choice">
                <div class="method-primary">
                    <span>主估值方法</span>
                    <strong>${escapeHtml(method.primary_name || method.primary_method)}</strong>
                    <div class="pill">${escapeHtml(method.score ?? '-')}</div>
                </div>
                <div>
                    <div class="muted">${asList(method.rationale).map(escapeHtml).join('；') || '暂无方法理由。'}</div>
                    <ul class="guide-list">
                        ${asList(method.secondary_methods).slice(0, 4).map((item) => `<li>辅助验证：${escapeHtml(item.name || item.method || '')}${item.reason ? ' - ' + escapeHtml(item.reason) : ''}</li>`).join('')}
                        ${asList(method.unsuitable_methods).slice(0, 4).map((item) => `<li>暂不适合：${escapeHtml(item.name || item.method || '')}${item.reason ? ' - ' + escapeHtml(item.reason) : ''}</li>`).join('')}
                    </ul>
                </div>
            </div>
            ${renderAssumptionSteps(guide.assumption_steps)}
        `;
    }

    function renderAssumptionSteps(steps) {
        const list = asList(steps).slice(0, 8);
        if (!list.length) return '';
        return `
            <div class="guide-grid">
                ${list.map((step) => `
                    <div class="guide-step-card">
                        <strong>${escapeHtml(step.label || step.key || '假设项')} ${step.suggested_value !== undefined ? `<span class="value">${escapeHtml(step.suggested_value)}${escapeHtml(step.unit || '')}</span>` : ''}</strong>
                        <div class="muted">${escapeHtml(step.why || '')}</div>
                        ${step.question ? `<div class="muted">验证：${escapeHtml(step.question)}</div>` : ''}
                        ${step.risk ? `<div class="muted">风险：${escapeHtml(step.risk)}</div>` : ''}
                    </div>
                `).join('')}
            </div>
        `;
    }

    function renderRecommendations(items) {
        const list = (items || []).slice(0, 6);
        if (!list.length) {
            $('recommendations').innerHTML = '<div class="recommendation"><div class="rec-desc">暂无推荐。</div></div>';
            return;
        }
        $('recommendations').innerHTML = list.map((item, idx) => `
            <div class="recommendation ${idx === 0 ? 'best' : ''}">
                <div class="rec-head">
                    <div class="rec-name">${escapeHtml(item.name)} · ${escapeHtml(item.title || '')}</div>
                    <span class="pill">${item.score}</span>
                </div>
                <div class="rec-desc">${escapeHtml(item.anchor || '')}</div>
                <div class="rec-desc">${(item.reasons || []).map(escapeHtml).join('；') || escapeHtml(item.description || '')}</div>
            </div>
        `).join('');
    }

    function renderScenariosFromGuide(guide) {
        const base = guide?.ui_assumptions || currentUiAssumptions();
        const list = [
            { scenario_key: 'bear', name: '悲观', assumptions: bumpScenario(base, 'bear') },
            { scenario_key: 'base', name: '基准', assumptions: base },
            { scenario_key: 'bull', name: '乐观', assumptions: bumpScenario(base, 'bull') }
        ];
        $('scenarioGrid').innerHTML = list.map((item) => scenarioCard(item)).join('');
    }

    function bumpScenario(base, mode) {
        const out = Object.assign({}, base || {});
        const multipleKeys = ['target_pe', 'target_pb', 'target_ps', 'target_pcf'];
        multipleKeys.forEach((key) => {
            const n = Number(out[key]);
            if (!Number.isFinite(n)) return;
            out[key] = round(mode === 'bear' ? n * 0.85 : n * 1.12, 2);
        });
        if (Number.isFinite(Number(out.dcf_growth))) out.dcf_growth = round(Number(out.dcf_growth) + (mode === 'bear' ? -2 : 2), 2);
        if (Number.isFinite(Number(out.discount_rate))) out.discount_rate = round(Number(out.discount_rate) + (mode === 'bear' ? 1 : -0.8), 2);
        if (Number.isFinite(Number(out.target_dividend_yield))) out.target_dividend_yield = round(Number(out.target_dividend_yield) + (mode === 'bear' ? 0.5 : -0.3), 2);
        return out;
    }

    function scenarioCard(item) {
        const fields = ['target_pe', 'target_pb', 'dcf_growth', 'discount_rate'];
        const labels = { target_pe: 'PE', target_pb: 'PB', dcf_growth: '增长率', discount_rate: '折现率' };
        return `
            <div class="scenario-card" data-scenario-key="${escapeAttr(item.scenario_key)}">
                <strong>${escapeHtml(item.name)}</strong>
                <div class="scenario-fields">
                    ${fields.map((key) => `
                        <label>${labels[key]}
                            <input data-scenario-field="${key}" value="${escapeAttr(item.assumptions?.[key] ?? '')}" inputmode="decimal">
                        </label>
                    `).join('')}
                </div>
                <div class="muted" data-scenario-output>等待测算</div>
            </div>
        `;
    }

    function renderResults(valuation) {
        const methods = valuation?.methods || [];
        const summary = valuation?.summary || {};
        state.lastValuation = valuation || state.lastValuation;
        if (!methods.length) {
            $('results').innerHTML = '<div class="empty-state">计算后显示各估值方法的合理价、安全边际和缺失字段。</div>';
            renderConclusion();
            return;
        }
        $('results').innerHTML = methods.map((item) => {
            const missing = !item.available;
            const tone = resultTone(item.margin_of_safety);
            const notes = (item.notes || []).join(' ');
            return `
                <div class="result-card ${missing ? 'missing' : ''}">
                    <div class="result-head">
                        <div class="result-name">${escapeHtml(item.name || item.method)}</div>
                        <span class="pill">${missing ? '待补字段' : fmtPct(item.margin_of_safety)}</span>
                    </div>
                    <div class="result-grid">
                        <div><div class="result-value ${tone}">${fmtNumber(item.fair_price, 2)}</div><div class="result-sub">合理价</div></div>
                        <div><div class="result-value neutral">${fmtNumber(item.band_low, 2)}</div><div class="result-sub">低位</div></div>
                        <div><div class="result-value neutral">${fmtNumber(item.band_high, 2)}</div><div class="result-sub">高位</div></div>
                    </div>
                    <div class="muted">${escapeHtml(notes)}</div>
                </div>
            `;
        }).join('');
        renderDcfDetail(valuation.dcf_detail);
        renderConclusion(summary);
    }

    function renderDcfDetail(detail) {
        if (!detail || !detail.model) {
            $('dcfDetail').innerHTML = '';
            return;
        }
        const wacc = detail.wacc || {};
        $('dcfDetail').innerHTML = `
            <div class="dcf-detail-card">
                <strong>${detail.model.toUpperCase()} 明细</strong>
                <pre>现金流：${(detail.cash_flows || []).map((x) => fmtNumber(x, 2)).join(' / ')}
终值：${fmtNumber(detail.terminal_value, 2)}
权益价值：${fmtNumber(detail.equity_value, 2)}
每股价值：${fmtNumber(detail.per_share_value, 2)}</pre>
            </div>
            <div class="dcf-detail-card">
                <strong>WACC 推导</strong>
                <pre>股权成本：${fmtPct(wacc.cost_of_equity)}
税后债务成本：${fmtPct(wacc.after_tax_cost_of_debt)}
债务权重：${fmtPct(wacc.debt_weight)}
股权权重：${fmtPct(wacc.equity_weight)}
WACC：${fmtPct(wacc.wacc)}</pre>
            </div>
        `;
    }

    function renderConclusion(summaryOverride) {
        const valuation = state.lastValuation || {};
        const summary = summaryOverride || valuation.summary || {};
        const guideConclusion = state.guide?.conclusion || {};
        const fair = summary.blended_fair_price;
        const margin = summary.blended_margin_of_safety;
        const available = summary.available_methods || 0;
        const quality = state.guide?.data_quality || {};
        const stance = guideConclusion.stance || (available >= 2 ? '待验证' : '不可判断');
        $('conclusionBox').innerHTML = `
            <h3>${escapeHtml(stance)}</h3>
            <div class="snapshot" style="grid-template-columns: repeat(3, minmax(0, 1fr));">
                <div class="metric"><span>综合估值锚</span><strong>${fmtNumber(fair, 2)}</strong></div>
                <div class="metric"><span>安全边际</span><strong>${fmtPct(margin)}</strong></div>
                <div class="metric"><span>可用方法</span><strong>${available}</strong></div>
            </div>
            <div class="muted" style="margin-top:10px;">${escapeHtml(guideConclusion.text || '请完成方法确认、假设证据和情景测算后，再形成正式结论。')}</div>
            <div class="muted" style="margin-top:6px;">数据完整度：${quality.score ?? '-'}；结论必须受数据缺口和反证条件约束。</div>
        `;
        renderCounterEvidence();
    }

    function renderCounterEvidence() {
        const items = state.currentCase?.counter_evidence || (state.guide?.conclusion?.watch_items || []).map((title) => ({
            title,
            trigger_condition: title,
            severity: 'medium'
        }));
        if (!items.length) {
            $('counterList').innerHTML = '<div class="empty-state">AI 追问或生成路径后，会自动沉淀反证条件。</div>';
            return;
        }
        $('counterList').innerHTML = items.map((item) => `
            <div class="counter-item">
                <strong>${escapeHtml(item.title)}</strong>
                <div class="muted">${escapeHtml(item.trigger_condition || '')}</div>
                <span class="pill">${escapeHtml(item.severity || 'medium')}</span>
            </div>
        `).join('');
    }

    function coachFieldLabel(field) {
        if (field === 'all') return '全部假设';
        return field ? assumptionLabel(field) : '当前假设';
    }

    function coachChallengeLabel(level) {
        const key = String(level || '').toLowerCase();
        if (key === 'high') return '强挑战';
        if (key === 'low') return '轻追问';
        return '中等挑战';
    }

    function reviewStatusLabel(status) {
        const map = {
            pass: '基本通过',
            needs_work: '需要补证',
            high_risk: '高风险',
            needs_evidence: '缺证据',
            too_optimistic: '偏乐观',
            too_conservative: '偏保守',
            conflict: '有冲突',
            missing: '未填写'
        };
        return map[String(status || '').toLowerCase()] || '待审';
    }

    function priorityLabel(priority) {
        const map = {
            high: '高优先级',
            medium: '中优先级',
            low: '低优先级'
        };
        return map[String(priority || '').toLowerCase()] || '中优先级';
    }

    function reviewStatusTone(status) {
        const key = String(status || '').toLowerCase();
        if (key === 'pass') return 'good';
        if (key === 'high_risk' || key === 'too_optimistic' || key === 'conflict' || key === 'missing') return 'bad';
        return 'warn';
    }

    function renderAssumptionReview() {
        const modeEl = $('reviewModeLabel');
        if (modeEl) {
            modeEl.textContent = $('useAiGuide')?.checked
                ? '在线 AI 审稿：失败时自动用规则审稿'
                : '规则审稿：不调用在线模型';
        }
        renderInlineAnnotations();
    }

    function coachSourceLabel(payload) {
        if (payload?.source === 'online_ai') return '在线 AI';
        if (payload?.source === 'rule_fallback' || payload?.source === 'rule') return '规则追问';
        if (payload?.ai_error) return '规则兜底';
        return 'AI Coach';
    }

    function renderCoachFocus() {
        const el = $('coachFocus');
        if (!el) return;
        const field = $('coachField')?.value || 'dcf_growth';
        const label = coachFieldLabel(field);
        const value = currentUiAssumptions()[field];
        const logic = ($('assumptionLogic')?.value || '').trim();
        const saved = (state.currentCase?.assumptions || []).find((item) => item.assumption_key === field && item.scenario_key === 'base');
        const mode = $('useAiGuide')?.checked
            ? '在线 AI：调用模型，失败时自动转规则追问'
            : '规则追问：不调用在线模型';
        const modeEl = $('coachModeLabel');
        if (modeEl) modeEl.textContent = mode;
        el.innerHTML = `
            <div class="coach-focus-head">
                <span>当前挑战对象</span>
                <strong>${escapeHtml(label)}</strong>
            </div>
            <div class="coach-focus-grid">
                <div><span>假设值</span><strong>${escapeHtml(value ?? '-')}</strong></div>
                <div><span>证据状态</span><strong>${escapeHtml((saved?.user_logic || logic) ? '已有解释' : '缺少解释')}</strong></div>
                <div><span>保存状态</span><strong>${escapeHtml(saved?.status || (state.currentCase?.id ? '未保存' : '未建案例'))}</strong></div>
            </div>
        `;
    }

    function renderCoachPayload(payload) {
        const questions = asList(payload.questions).filter(Boolean).slice(0, 6);
        const gaps = asList(payload.evidence_gaps).filter(Boolean).slice(0, 6);
        const counter = asList(payload.counter_evidence).filter(Boolean).slice(0, 6);
        const revision = payload.suggested_revision || {};
        const revisionValue = revision.value === null || revision.value === undefined || revision.value === '' ? '' : `建议值：${revision.value}`;
        const revisionText = [revisionValue, revision.reason].filter(Boolean).join('；');
        return `
            ${questions.length ? `
                <div class="coach-block questions">
                    <div class="coach-block-title">追问</div>
                    <div class="coach-card-list">
                        ${questions.map((item) => `
                            <div class="coach-mini-card">
                                <b>${escapeHtml(item.question || item)}</b>
                                ${item.why ? `<p>${escapeHtml(item.why)}</p>` : ''}
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
            ${gaps.length ? `
                <div class="coach-block gaps">
                    <div class="coach-block-title">证据缺口</div>
                    <div class="coach-card-list">
                        ${gaps.map((item) => `
                            <div class="coach-mini-card">
                                <b>${escapeHtml(item.gap || item)}</b>
                                ${item.suggested_source ? `<p>${escapeHtml(item.suggested_source)}</p>` : ''}
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
            ${counter.length ? `
                <div class="coach-block counter">
                    <div class="coach-block-title">反证条件</div>
                    <div class="coach-card-list">
                        ${counter.map((item) => `
                            <div class="coach-mini-card">
                                <b>${escapeHtml(item.title || item)}</b>
                                ${item.trigger_condition ? `<p>${escapeHtml(item.trigger_condition)}</p>` : ''}
                                ${item.severity ? `<span>${escapeHtml(item.severity)}</span>` : ''}
                            </div>
                        `).join('')}
                    </div>
                </div>
            ` : ''}
            ${revisionText ? `
                <div class="coach-block revision">
                    <div class="coach-block-title">建议修正</div>
                    <div class="coach-mini-card">
                        <b>${escapeHtml(coachFieldLabel(revision.field || ''))}</b>
                        <p>${escapeHtml(revisionText)}</p>
                    </div>
                </div>
            ` : ''}
            ${payload.ai_error ? `<div class="coach-error">在线 AI 调用失败，已使用规则追问：${escapeHtml(payload.ai_error)}</div>` : ''}
        `;
    }

    function renderCoachThread() {
        const messages = state.currentCase?.ai_messages || [];
        const target = $('coachThreadDrawer') || $('coachThread');
        renderCoachFocus();
        if (!messages.length) {
            if (target) target.innerHTML = '<div class="empty-state">暂无 AI 历史。字段有问题时点击状态灯处理。</div>';
            return;
        }
        if (!target) return;
        target.innerHTML = messages.map((msg) => {
            const payload = msg.payload || {};
            const isAssistant = msg.role === 'assistant';
            const field = coachFieldLabel(msg.related_field || payload.related_field || payload.suggested_revision?.field || '');
            return `
                <div class="coach-message ${escapeAttr(msg.role)}">
                    <div class="coach-message-head">
                        <strong>${isAssistant ? coachSourceLabel(payload) : '你的论点'} · ${escapeHtml(field)}</strong>
                        ${isAssistant ? `<span class="pill">${escapeHtml(coachChallengeLabel(payload.challenge_level))}</span>` : ''}
                    </div>
                    <div class="coach-content">${escapeHtml(msg.content || '')}</div>
                    ${isAssistant ? renderCoachPayload(payload) : ''}
                </div>
            `;
        }).join('');
        target.scrollTop = target.scrollHeight;
    }

    function resultTone(margin) {
        const n = Number(margin);
        if (!Number.isFinite(n)) return 'neutral';
        if (n >= 0.15) return 'good';
        if (n < -0.05) return 'bad';
        return 'neutral';
    }

    function configFromInputs() {
        const out = {};
        document.querySelectorAll('[data-config-group]').forEach((input) => {
            const group = input.dataset.configGroup;
            const key = input.dataset.configKey;
            out[group] = out[group] || {};
            out[group][key] = input.value.trim();
        });
        return out;
    }

    function renderConfig(config) {
        const cfg = config || {};
        $('configGrid').innerHTML = Object.keys(cfg).map((group) => {
            const fields = cfg[group] || {};
            const inputs = Object.keys(fields).map((key) => `
                <label>${escapeHtml(key)}
                    <input data-config-group="${escapeAttr(group)}" data-config-key="${escapeAttr(key)}" value="${escapeAttr(fields[key] || '')}">
                </label>
            `).join('');
            return `
                <div class="config-group">
                    <div class="config-group-title">${escapeHtml(configLabels[group] || group)}</div>
                    ${inputs}
                </div>
            `;
        }).join('');
    }

    async function loadConfig() {
        const data = await apiFetch('/api/stock_valuation/config', { method: 'GET', headers: {} });
        state.config = data.config || {};
        state.defaults = data.defaults || {};
        renderConfig(state.config);
    }

    async function saveConfig() {
        setLoading(true);
        try {
            const data = await apiFetch('/api/stock_valuation/config', {
                method: 'POST',
                body: JSON.stringify({ config: configFromInputs() })
            });
            state.config = data.config || {};
            renderConfig(state.config);
            setStatus('字段配置已保存', 'ok');
        } catch (err) {
            setStatus(err.message, 'err');
        } finally {
            setLoading(false);
        }
    }

    async function searchStocks(query) {
        if (!query || query.length < 2) {
            $('suggestions').classList.remove('active');
            return;
        }
        try {
            const data = await apiFetch('/api/data_query/search_stock', {
                method: 'POST',
                body: JSON.stringify({ query })
            });
            const stocks = data.success ? (data.stocks || []).slice(0, 8) : [];
            if (!stocks.length) {
                $('suggestions').classList.remove('active');
                return;
            }
            $('suggestions').innerHTML = stocks.map((s) => `
                <button type="button" class="suggestion" data-code="${escapeAttr(s.code || '')}" data-name="${escapeAttr(s.name || '')}">
                    <span class="code">${escapeHtml(s.code || '')}</span>
                    <span>${escapeHtml(s.name || '')}</span>
                </button>
            `).join('');
            $('suggestions').classList.add('active');
        } catch (_) {
            $('suggestions').classList.remove('active');
        }
    }

    async function fetchFacts() {
        const code = normalizeCode($('stockInput').value);
        if (!code) {
            setStatus('请输入 6 位股票代码', 'warn');
            return;
        }
        state.stockCode = code;
        setLoading(true);
        setStatus('正在从聚源拉取数据...');
        try {
            const data = await apiFetch('/api/stock_valuation/fetch', {
                method: 'POST',
                body: JSON.stringify({
                    stock_code: code,
                    as_of: $('asOfInput').value,
                    field_config: configFromInputs()
                })
            });
            applyFacts(data.facts || {});
            renderWarnings(data.warnings || []);
            markCompleted('profile');
            invalidateFrom('profile');
            setStatus('聚源数据已填入，请先核对数据日期和缺口', 'ok');
            switchTab('profile');
        } catch (err) {
            setStatus(err.message, 'err');
        } finally {
            setLoading(false);
        }
    }

    async function generateGuide() {
        const code = normalizeCode($('stockInput').value) || state.stockCode;
        if (!code && state.source !== 'manual') {
            setStatus('请输入股票代码', 'warn');
            return;
        }
        setLoading(true);
        setStatus($('useAiGuide').checked ? '正在生成 AI 估值路径...' : '正在生成估值路径...');
        try {
            const data = await apiFetch('/api/stock_valuation/guide', {
                method: 'POST',
                body: JSON.stringify({
                    stock_code: code || '000000',
                    source: state.source,
                    as_of: $('asOfInput').value,
                    field_config: configFromInputs(),
                    manual_fields: currentManualFields(),
                    assumptions: currentCalcAssumptions(),
                    use_ai: $('useAiGuide').checked
                })
            });
            applyFacts(data.facts || data.valuation?.facts || {});
            state.lastValuation = data.valuation || null;
            state.recommendations = data.recommendations || [];
            state.guide = data.guide || null;
            renderWarnings(data.warnings || []);
            renderRecommendations(state.recommendations);
            renderMethodDecision(state.guide);
            renderScenariosFromGuide(state.guide);
            renderResults(data.valuation || {});
            renderDataQuality();
            renderGuidedAssumptions();
            markCompleted('methods');
            await saveCaseState(true);
            setStatus('估值路径已生成：先确认主方法，再进入假设工作纸', 'ok');
            switchTab('methods');
        } catch (err) {
            setStatus(err.message, 'err');
        } finally {
            setLoading(false);
        }
    }

    async function createCase() {
        const code = normalizeCode($('stockInput').value) || state.stockCode;
        if (!code && state.source !== 'manual') {
            setStatus('请输入股票代码后再创建案例', 'warn');
            return;
        }
        setLoading(true);
        setStatus('正在创建完整估值工作纸...');
        try {
            const data = await apiFetch('/api/stock_valuation/cases', {
                method: 'POST',
                body: JSON.stringify({
                    stock_code: code || '000000',
                    source: state.source,
                    as_of: $('asOfInput').value,
                    field_config: configFromInputs(),
                    manual_fields: currentManualFields(),
                    assumptions: currentCalcAssumptions(),
                    use_ai: $('useAiGuide').checked
                })
            });
            applyCase(data.case);
            renderWarnings(data.warnings || []);
            markCompleted('methods');
            await saveCaseState(true);
            setStatus('估值工作纸已创建，后续假设和 AI 辩论会保存进案例库', 'ok');
            switchTab('methods');
        } catch (err) {
            setStatus(err.message, 'err');
        } finally {
            setLoading(false);
        }
    }

    function applyCase(caseData) {
        state.hydrating = true;
        state.currentCase = caseData || null;
        const caseState = caseData?.state || {};
        state.guide = caseState.guide || state.guide;
        state.lastValuation = caseState.valuation || state.lastValuation;
        state.recommendations = caseState.recommendations || state.recommendations || [];
        state.workflow = normalizeWorkflow(caseState.workflow);
        applyFacts(caseState.facts || (caseData?.facts_history?.[0]?.facts) || state.facts || {});
        if (state.guide?.ui_assumptions) setAssumptionInputs(state.guide.ui_assumptions);
        if (caseState.tabs?.assumptions?.logic !== undefined) $('assumptionLogic').value = caseState.tabs.assumptions.logic || '';
        state.pbProcessStepIndex = Number(caseState.tabs?.assumptions?.pb_process?.active_index || 0) || 0;
        state.assumptionEvidenceDrafts = Object.assign({}, savedAssumptionEvidence(), caseState.tabs?.assumptions?.evidence || {});
        setAssumptionEvidence(state.assumptionEvidenceDrafts);
        if (caseData?.latest_results?.length) {
            const baseResult = caseData.latest_results.find((item) => item.scenario_key === 'base') || caseData.latest_results[0];
            if (baseResult?.result) state.lastValuation = baseResult.result;
        }
        renderRecommendations(state.recommendations);
        renderMethodDecision(state.guide);
        renderScenariosFromGuide(state.guide);
        renderResults(state.lastValuation || {});
        renderAssumptionReview();
        renderGuidedAssumptions();
        renderCoachThread();
        renderCounterEvidence();
        renderCaseHeader();
        renderWorkflowRail();
        state.hydrating = false;
    }

    async function calculate(saveSnapshot = false) {
        const code = normalizeCode($('stockInput').value) || state.stockCode;
        if (!code && state.source !== 'manual') {
            setStatus('请输入股票代码', 'warn');
            return;
        }
        setLoading(true);
        setStatus(saveSnapshot ? '正在计算并保存快照...' : '正在计算估值...');
        try {
            const data = await apiFetch('/api/stock_valuation/calculate', {
                method: 'POST',
                body: JSON.stringify({
                    stock_code: code || '000000',
                    source: state.source,
                    as_of: $('asOfInput').value,
                    field_config: configFromInputs(),
                    manual_fields: currentManualFields(),
                    assumptions: currentCalcAssumptions(),
                    save_snapshot: saveSnapshot
                })
            });
            applyFacts(data.valuation?.facts || {});
            renderWarnings(data.warnings || []);
            renderRecommendations(data.recommendations || []);
            renderResults(data.valuation || {});
            state.recommendations = data.recommendations || [];
            if (saveSnapshot) markCompleted('conclusion');
            else markCompleted('scenarios');
            await saveCaseState(true);
            setStatus(saveSnapshot ? '估值快照已保存' : '估值已完成', 'ok');
            switchTab(saveSnapshot ? 'conclusion' : 'scenarios');
        } catch (err) {
            setStatus(err.message, 'err');
        } finally {
            setLoading(false);
        }
    }

    async function saveAssumptions(advanceAfterSave = true) {
        if (!state.currentCase?.id) {
            setStatus('请先创建估值案例，再保存假设', 'warn');
            return;
        }
        const pbGate = pbProcessGate();
        if (!pbGate.ok) {
            const first = pbGate.blockers[0] || pbGate.missing[0];
            setStatus(`PB 主锚还没闭环：请先完成「${first?.title || 'PB 推导流程'}」`, 'warn');
            state.activeTab = 'assumptions';
            renderGuidedAssumptions();
            renderWorkflowRail();
            return;
        }
        if (advanceAfterSave) {
            const incomplete = firstIncompleteAssumptionStep();
            if (incomplete) {
                const idx = visibleAssumptionSteps().findIndex((step) => step.key === incomplete.key);
                if (idx >= 0) state.assumptionStepIndex = idx;
                setStatus(`交叉验证还没完成：请先写「${incomplete.label || assumptionLabel(incomplete.key)}」的结论。`, 'warn');
                state.activeTab = 'assumptions';
                renderGuidedAssumptions();
                renderWorkflowRail();
                return;
            }
        }
        setLoading(true);
        try {
            const logic = $('assumptionLogic').value.trim();
            const values = currentUiAssumptions();
            const evidenceByKey = currentAssumptionEvidence();
            for (const [key, value] of Object.entries(values)) {
                const fieldLogic = evidenceByKey[key] || logic;
                await apiFetch(`/api/stock_valuation/cases/${state.currentCase.id}/assumptions`, {
                    method: 'POST',
                    body: JSON.stringify({
                        scenario_key: 'base',
                        assumption_key: key,
                        label: assumptionLabel(key),
                        value,
                        unit: percentKeys.has(key) ? '%' : '',
                        source: 'user',
                        user_logic: fieldLogic,
                        evidence_text: fieldLogic,
                        status: fieldLogic ? 'reviewed' : 'draft'
                    })
                });
            }
            const refreshed = await apiFetch(`/api/stock_valuation/cases/${state.currentCase.id}`, { method: 'GET', headers: {} });
            applyCase(refreshed.case);
            state.assumptionEvidenceDrafts = Object.assign({}, state.assumptionEvidenceDrafts || {}, evidenceByKey);
            setAssumptionEvidence(state.assumptionEvidenceDrafts);
            if (advanceAfterSave) markCompleted('assumptions');
            await saveCaseState(true);
            setStatus(advanceAfterSave ? '假设已保存到工作纸' : 'PB 结论已保存。继续做每股净资产、PE 等交叉验证。', 'ok');
            if (advanceAfterSave) switchTab('scenarios');
            else {
                state.activeTab = 'assumptions';
                renderGuidedAssumptions();
                renderWorkflowRail();
            }
        } catch (err) {
            setStatus(err.message, 'err');
        } finally {
            setLoading(false);
        }
    }

    async function reviewAssumptions() {
        if (!state.currentCase?.id) {
            setStatus('请先创建估值案例，再让 AI 审稿', 'warn');
            return;
        }
        const pbGate = pbProcessGate();
        if (!pbGate.ok) {
            const first = pbGate.next || pbGate.blockers[0] || pbGate.missing[0];
            setStatus(`PB 主锚还没闭环：请先完成「${first?.title || 'PB 推导流程'}」，再检查交叉验证假设。`, 'warn');
            state.activeTab = 'assumptions';
            renderGuidedAssumptions();
            renderWorkflowRail();
            return;
        }
        const incomplete = firstIncompleteAssumptionStep();
        if (incomplete) {
            const idx = visibleAssumptionSteps().findIndex((step) => step.key === incomplete.key);
            if (idx >= 0) state.assumptionStepIndex = idx;
            setStatus(`交叉验证还没完成：请先写「${incomplete.label || assumptionLabel(incomplete.key)}」的结论，再检查。`, 'warn');
            state.activeTab = 'assumptions';
            renderGuidedAssumptions();
            renderWorkflowRail();
            return;
        }
        const assumptions = currentUiAssumptions();
        if (!Object.keys(assumptions).length) {
            setStatus('请先填写或套用估值假设', 'warn');
            return;
        }
        setLoading(true);
        setStatus($('useAiGuide').checked ? 'AI 正在审稿全部估值假设...' : '正在用规则审稿全部估值假设...');
        try {
            const data = await apiFetch(`/api/stock_valuation/cases/${state.currentCase.id}/assumption_review`, {
                method: 'POST',
                body: JSON.stringify({
                    ui_assumptions: assumptions,
                    assumption_evidence: currentAssumptionEvidence(),
                    user_logic: $('assumptionLogic').value.trim(),
                    use_ai: $('useAiGuide').checked
                })
            });
            state.currentCase = data.case || state.currentCase;
            renderAssumptionReview();
            renderCoachThread();
            renderCounterEvidence();
            markCompleted('assumptions');
            await saveCaseState(true);
            setStatus(data.review?.summary || '假设审稿已完成', data.review?.review_status === 'high_risk' ? 'warn' : 'ok');
        } catch (err) {
            setStatus(err.message, 'err');
        } finally {
            setLoading(false);
        }
    }

    async function askCoach() {
        if (!state.currentCase?.id) {
            setStatus('请先创建估值案例，再进行 AI 辩论', 'warn');
            return null;
        }
        const field = $('coachField').value;
        const userText = $('coachMessage').value.trim();
        const value = currentUiAssumptions()[field];
        const message = userText || `${assumptionLabel(field)} = ${value ?? '-'}，请检查这个假设是否站得住。`;
        const btn = $('coachBtn');
        const originalText = btn?.textContent || '';
        state.activeCoachJobs += 1;
        state.verifyingFields.add(field);
        renderInlineAnnotations();
        if (btn) {
            btn.disabled = true;
            btn.textContent = '后台验证中';
        }
        setStatus(`已提交 ${assumptionLabel(field)} 的后台验证，可继续调整其它参数`, 'ok');
        try {
            const data = await apiFetch(`/api/stock_valuation/cases/${state.currentCase.id}/ai_coach`, {
                method: 'POST',
                body: JSON.stringify({
                    message,
                    related_field: field,
                    tab_key: 'assumptions',
                    use_ai: $('useAiGuide').checked
                })
            });
            const refreshed = await apiFetch(`/api/stock_valuation/cases/${state.currentCase.id}`, { method: 'GET', headers: {} });
            applyCase(refreshed.case);
            $('coachMessage').value = '';
            await saveCaseState(true);
            setStatus(data.coach?.summary || 'AI Coach 已追问', 'ok');
            return data;
        } catch (err) {
            setStatus(err.message, 'err');
            return null;
        } finally {
            state.activeCoachJobs = Math.max(0, state.activeCoachJobs - 1);
            state.verifyingFields.delete(field);
            if (btn) {
                btn.disabled = false;
                btn.textContent = originalText || '发起追问';
            }
            renderInlineAnnotations();
        }
    }

    async function saveSingleAssumptionEvidence(field, text) {
        if (!state.currentCase?.id) {
            setStatus('请先创建估值案例，再保存字段依据', 'warn');
            return;
        }
        if (!assumptionMap[field]) return;
        const value = currentUiAssumptions()[field];
        if (value === undefined) {
            setStatus('请先填写这个假设的数值', 'warn');
            return;
        }
        state.assumptionEvidenceDrafts[field] = text || '';
        await apiFetch(`/api/stock_valuation/cases/${state.currentCase.id}/assumptions`, {
            method: 'POST',
            body: JSON.stringify({
                scenario_key: 'base',
                assumption_key: field,
                label: assumptionLabel(field),
                value,
                unit: percentKeys.has(field) ? '%' : '',
                source: 'user',
                user_logic: text || '',
                evidence_text: text || '',
                status: text ? 'reviewed' : 'draft'
            })
        });
        const refreshed = await apiFetch(`/api/stock_valuation/cases/${state.currentCase.id}`, { method: 'GET', headers: {} });
        applyCase(refreshed.case);
        await saveCaseState(true);
        setStatus(`${assumptionLabel(field)} 的依据已保存`, 'ok');
    }

    async function askInlineCoach(field) {
        if (!assumptionMap[field]) return;
        const textarea = document.querySelector(`[data-inline-rebuttal="${cssEscape(field)}"]`);
        const text = (textarea?.value || '').trim();
        if (text) {
            state.assumptionEvidenceDrafts[field] = text;
            const logicInput = document.querySelector(`[data-assumption-logic="${cssEscape(field)}"]`);
            if (logicInput) logicInput.value = text;
            syncAssumptionLogicFromRows();
            setAssumptionEvidence(state.assumptionEvidenceDrafts);
        }
        $('coachField').value = field;
        $('coachMessage').value = text || `${assumptionLabel(field)} = ${currentUiAssumptions()[field] ?? '-'}，请验证这条反驳是否足够。`;
        renderCoachFocus();
        await askCoach();
        state.inlinePopoverField = field;
        renderInlineAnnotations();
    }

    function syncAssumptionEvidenceField(field, text) {
        if (!assumptionMap[field]) return;
        state.assumptionEvidenceDrafts[field] = text || '';
        const logicInput = document.querySelector(`[data-assumption-logic="${cssEscape(field)}"]`);
        const inlineInput = document.querySelector(`[data-inline-rebuttal="${cssEscape(field)}"]`);
        if (logicInput && logicInput.value !== text) logicInput.value = text || '';
        if (inlineInput && inlineInput.value !== text) inlineInput.value = text || '';
        syncAssumptionLogicFromRows();
    }

    async function askDrawerCoach(field) {
        if (!assumptionMap[field]) return;
        const textarea = document.querySelector(`[data-drawer-feedback="${cssEscape(field)}"]`);
        const text = (textarea?.value || '').trim();
        syncAssumptionEvidenceField(field, text);
        $('coachField').value = field;
        $('coachMessage').value = text
            ? `${assumptionLabel(field)} = ${currentUiAssumptions()[field] ?? '-'}。我的反馈/依据：${text}。请复查这个参数还有没有证据缺口或逻辑冲突。`
            : `${assumptionLabel(field)} = ${currentUiAssumptions()[field] ?? '-'}，请只检查这一项假设是否有硬错误或证据缺口。`;
        await askCoach();
        state.assumptionDrawerOpen = true;
        renderAssumptionDrawer();
    }

    async function askRowCoach(field) {
        if (!assumptionMap[field]) return;
        if (!state.currentCase?.id) {
            setStatus('请先创建估值案例，再点击状态灯进行行级检查', 'warn');
            return;
        }
        const logicInput = document.querySelector(`[data-assumption-logic="${cssEscape(field)}"]`);
        const text = (logicInput?.value || '').trim();
        const value = currentUiAssumptions()[field];
        $('coachField').value = field;
        $('coachMessage').value = text || `${assumptionLabel(field)} = ${value ?? '-'}，请只检查这一项假设是否有硬错误或证据缺口。`;
        await askCoach();
        const issue = assumptionAnnotationFor(field);
        state.inlinePopoverField = issue ? field : '';
        renderInlineAnnotations();
    }

    async function runScenarios() {
        if (!state.currentCase?.id) {
            setStatus('请先创建估值案例，再保存情景测算', 'warn');
            return;
        }
        const pbGate = pbProcessGate();
        if (!pbGate.ok) {
            const first = pbGate.blockers[0] || pbGate.missing[0];
            setStatus(`PB 主锚还没闭环：请先完成「${first?.title || 'PB 推导流程'}」`, 'warn');
            switchTab('assumptions');
            return;
        }
        const scenarios = Array.from(document.querySelectorAll('[data-scenario-key]')).map((card) => {
            const assumptions = Object.assign({}, currentUiAssumptions());
            card.querySelectorAll('[data-scenario-field]').forEach((input) => {
                const value = Number(input.value);
                if (Number.isFinite(value)) assumptions[input.dataset.scenarioField] = value;
            });
            return {
                scenario_key: card.dataset.scenarioKey,
                name: card.querySelector('strong')?.textContent || card.dataset.scenarioKey,
                ui_assumptions: assumptions
            };
        });
        setLoading(true);
        try {
            const data = await apiFetch(`/api/stock_valuation/cases/${state.currentCase.id}/scenarios`, {
                method: 'POST',
                body: JSON.stringify({ scenarios })
            });
            state.currentCase = data.case || state.currentCase;
            (data.items || []).forEach((item) => {
                const card = document.querySelector(`[data-scenario-key="${cssEscape(item.scenario?.scenario_key || '')}"]`);
                const output = card?.querySelector('[data-scenario-output]');
                const summary = item.valuation?.summary || {};
                if (output) output.textContent = `综合锚 ${fmtNumber(summary.blended_fair_price, 2)} / 安全边际 ${fmtPct(summary.blended_margin_of_safety)}`;
            });
            if (data.items?.[1]?.valuation) renderResults(data.items[1].valuation);
            renderCounterEvidence();
            markCompleted('scenarios');
            await saveCaseState(true);
            setStatus('三情景测算已保存到工作纸', 'ok');
            switchTab('conclusion');
        } catch (err) {
            setStatus(err.message, 'err');
        } finally {
            setLoading(false);
        }
    }

    async function loadCases() {
        const code = state.caseScope === 'current' ? (normalizeCode($('stockInput').value) || state.stockCode) : '';
        const qs = code ? `?stock_code=${encodeURIComponent(code)}` : '';
        const data = await apiFetch(`/api/stock_valuation/cases${qs}`, { method: 'GET', headers: {} });
        state.cases = data.items || [];
        renderCases();
    }

    function renderCases() {
        if (!state.cases.length) {
            const currentCode = normalizeCode($('stockInput').value) || state.stockCode;
            const emptyText = state.caseScope === 'current' && currentCode
                ? `暂无 ${escapeHtml(currentCode)} 的案例。切到“全部案例”可查看其他股票。`
                : '暂无案例。创建工作纸后会显示在这里。';
            $('caseList').innerHTML = `<div class="empty-state">${emptyText}</div>`;
            return;
        }
        $('caseList').innerHTML = state.cases.map((item) => `
            <div class="case-item">
                <div>
                    <strong>${escapeHtml(item.stock_code)} ${escapeHtml(item.stock_name || '')}</strong>
                    <div class="muted">${escapeHtml(item.title || '')} · ${escapeHtml(item.valuation_date || '')} · ${escapeHtml(item.updated_at || '')}</div>
                </div>
                <div class="case-actions">
                    <button type="button" data-open-case="${item.id}">打开</button>
                    <button type="button" class="danger" data-delete-case="${item.id}" data-case-label="${escapeAttr(`${item.stock_code} ${item.stock_name || ''}`)}">删除</button>
                </div>
            </div>
        `).join('');
    }

    function renderCaseScope() {
        document.querySelectorAll('[data-case-scope]').forEach((btn) => {
            const active = btn.dataset.caseScope === state.caseScope;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    }

    async function openCase(caseId) {
        setLoading(true);
        try {
            const data = await apiFetch(`/api/stock_valuation/cases/${caseId}`, { method: 'GET', headers: {} });
            applyCase(data.case);
            setStatus('案例已载入', 'ok');
            switchTab(data.case?.current_tab || 'profile');
        } catch (err) {
            setStatus(err.message, 'err');
        } finally {
            setLoading(false);
        }
    }

    async function deleteCase(caseId, label) {
        if (!caseId) return;
        const ok = window.confirm(`确定删除案例「${label || caseId}」吗？此操作会删除该案例的假设、情景、AI 对话和反证记录。`);
        if (!ok) return;
        setLoading(true);
        try {
            await apiFetch(`/api/stock_valuation/cases/${caseId}`, { method: 'DELETE', body: '{}' });
            if (String(state.currentCase?.id || '') === String(caseId)) {
                state.currentCase = null;
                state.guide = null;
                state.lastValuation = null;
                state.recommendations = [];
                state.assumptionEvidenceDrafts = {};
                state.workflow = normalizeWorkflow({ completed_tabs: [], unlocked_tabs: ['profile', 'cases'] });
                renderCaseHeader();
                renderWorkflowRail();
                renderAssumptionReview();
                renderGuidedAssumptions();
                renderCoachThread();
                renderCounterEvidence();
                renderResults({ methods: [] });
                renderMethodDecision(null);
                renderRecommendations([]);
            }
            await loadCases();
            setStatus('案例已删除', 'ok');
        } catch (err) {
            setStatus(err.message, 'err');
        } finally {
            setLoading(false);
        }
    }

    function assumptionLabel(key) {
        const id = assumptionMap[key];
        return $(id)?.dataset.assumptionLabel || key;
    }

    function round(value, digits) {
        const n = Number(value);
        if (!Number.isFinite(n)) return value;
        const base = Math.pow(10, digits || 2);
        return Math.round(n * base) / base;
    }

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[ch]));
    }

    function escapeAttr(value) {
        return escapeHtml(value).replace(/`/g, '&#96;');
    }

    function cssEscape(value) {
        if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(value);
        return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
    }

    function bindEvents() {
        document.querySelectorAll('[data-tab-button]').forEach((btn) => {
            btn.addEventListener('click', () => switchTab(btn.dataset.tabButton));
        });
        document.querySelectorAll('[data-case-scope]').forEach((btn) => {
            btn.addEventListener('click', () => {
                state.caseScope = btn.dataset.caseScope === 'all' ? 'all' : 'current';
                renderCaseScope();
                loadCases().catch((err) => setStatus(err.message, 'err'));
            });
        });
        document.querySelectorAll('.segmented [data-source]').forEach((btn) => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.segmented [data-source]').forEach((x) => x.classList.remove('active'));
                btn.classList.add('active');
                state.source = btn.dataset.source;
                invalidateFrom('profile');
            });
        });
        document.querySelectorAll('[data-manual]').forEach((input) => {
            input.addEventListener('input', () => invalidateFrom('profile'));
        });
        Object.values(assumptionMap).forEach((id) => {
            const input = $(id);
            if (input) input.addEventListener('input', () => {
                invalidateFrom('assumptions', false);
                renderInlineAnnotations();
            });
        });
        $('assumptionLogic').addEventListener('input', () => {
            invalidateFrom('assumptions', false);
            renderInlineAnnotations();
        });
        $('useAiGuide').addEventListener('change', () => {
            renderAssumptionReview();
        });
        document.querySelectorAll('[data-assumption-logic]').forEach((input) => {
            input.addEventListener('input', () => {
                state.assumptionEvidenceDrafts[input.dataset.assumptionLogic] = input.value.trim();
                syncAssumptionLogicFromRows();
                invalidateFrom('assumptions', false);
                renderInlineAnnotations();
            });
        });
        $('scenarioGrid').addEventListener('input', (event) => {
            if (event.target.closest('[data-scenario-key]')) invalidateFrom('scenarios', false);
        });
        $('stockInput').addEventListener('input', () => invalidateFrom('profile'));
        $('asOfInput').addEventListener('change', () => invalidateFrom('profile'));
        $('fetchBtn').addEventListener('click', fetchFacts);
        $('createCaseBtn').addEventListener('click', createCase);
        $('guideBtn').addEventListener('click', generateGuide);
        $('applyGuideBtn').addEventListener('click', () => {
            if (!state.guide?.ui_assumptions) {
                setStatus('请先生成估值路径', 'warn');
                return;
            }
            setAssumptionInputs(state.guide.ui_assumptions);
            renderScenariosFromGuide(state.guide);
            renderGuidedAssumptions();
            setStatus('已套用建议假设，请逐项写逻辑并保存', 'ok');
            switchTab('assumptions');
        });
        $('calcBtn').addEventListener('click', () => calculate(false));
        $('saveSnapshotBtn').addEventListener('click', () => calculate(true));
        $('runScenariosBtn').addEventListener('click', runScenarios);
        $('saveAssumptionsBtn').addEventListener('click', saveAssumptions);
        $('reviewAssumptionsBtn').addEventListener('click', reviewAssumptions);
        $('coachBtn').addEventListener('click', askCoach);
        $('assumptionStatusBar').addEventListener('click', () => {
            state.assumptionDrawerOpen = true;
            renderAssumptionDrawer();
            renderStatusBar();
        });
        $('assumptionStatusBar').addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                state.assumptionDrawerOpen = true;
                renderAssumptionDrawer();
                renderStatusBar();
            }
        });
        document.addEventListener('input', (event) => {
            const pbStep = event.target.closest('[data-pb-step]');
            if (pbStep) {
                state.assumptionEvidenceDrafts[pbStepEvidenceKey(pbStep.dataset.pbStep)] = pbStep.value.trim();
                invalidateFrom('assumptions', false);
                return;
            }
            const pbMetric = event.target.closest('[data-pb-metric]');
            if (pbMetric) {
                syncPbMetricInput(pbMetric);
                return;
            }
            const drawerFeedback = event.target.closest('[data-drawer-feedback]');
            if (!drawerFeedback) return;
            const field = drawerFeedback.dataset.drawerFeedback;
            syncAssumptionEvidenceField(field, drawerFeedback.value.trim());
            invalidateFrom('assumptions', false);
            renderCoachFocus();
        });
        document.addEventListener('click', async (event) => {
            const openBtn = event.target.closest('[data-open-annotation]');
            if (openBtn) {
                state.assumptionDrawerOpen = false;
                focusInlineAnnotation(openBtn.dataset.openAnnotation, true);
                return;
            }
            const toggle = event.target.closest('[data-lint-toggle]');
            if (toggle) {
                const key = toggle.dataset.lintToggle;
                const hasIssue = Boolean(assumptionAnnotationFor(key));
                if (!hasIssue) {
                    await askRowCoach(key);
                    return;
                }
                state.inlinePopoverField = state.inlinePopoverField === key ? '' : key;
                renderInlineAnnotations();
                return;
            }
            if (event.target.closest('[data-close-assumption-drawer]')) {
                state.assumptionDrawerOpen = false;
                renderAssumptionDrawer();
                renderStatusBar();
                return;
            }
            const drawerSave = event.target.closest('[data-drawer-save]');
            if (drawerSave) {
                const field = drawerSave.dataset.drawerSave;
                const textarea = document.querySelector(`[data-drawer-feedback="${cssEscape(field)}"]`);
                drawerSave.disabled = true;
                try {
                    const text = (textarea?.value || '').trim();
                    syncAssumptionEvidenceField(field, text);
                    await saveSingleAssumptionEvidence(field, text);
                    state.assumptionDrawerOpen = true;
                    renderAssumptionDrawer();
                } catch (err) {
                    setStatus(err.message, 'err');
                } finally {
                    drawerSave.disabled = false;
                }
                return;
            }
            const drawerAsk = event.target.closest('[data-drawer-ask]');
            if (drawerAsk) {
                drawerAsk.disabled = true;
                try {
                    await askDrawerCoach(drawerAsk.dataset.drawerAsk);
                } finally {
                    drawerAsk.disabled = false;
                }
                return;
            }
            const inlineTag = event.target.closest('[data-inline-tag]');
            if (inlineTag) {
                const field = inlineTag.dataset.inlineField;
                const textarea = document.querySelector(`[data-inline-rebuttal="${cssEscape(field)}"]`);
                insertComposerText(textarea, `[${inlineTag.dataset.inlineTag}]`);
                return;
            }
            const chip = event.target.closest('[data-reference-chip]');
            if (chip) {
                const target = chip.dataset.referenceTarget || 'coach';
                if (target.startsWith('inline:')) {
                    const field = target.slice(7);
                    insertComposerText(document.querySelector(`[data-inline-rebuttal="${cssEscape(field)}"]`), `{${chip.dataset.referenceChip}}`);
                } else if (target.startsWith('guide:')) {
                    const field = target.slice(6);
                    insertComposerText(document.querySelector(`[data-assumption-evidence="${cssEscape(field)}"]`), `{${chip.dataset.referenceChip}}`);
                } else {
                    insertComposerText($('coachMessage'), `{${chip.dataset.referenceChip}}`);
                }
                return;
            }
            const saveInline = event.target.closest('[data-inline-save]');
            if (saveInline) {
                const field = saveInline.dataset.inlineSave;
                const textarea = document.querySelector(`[data-inline-rebuttal="${cssEscape(field)}"]`);
                saveInline.disabled = true;
                try {
                    await saveSingleAssumptionEvidence(field, (textarea?.value || '').trim());
                } catch (err) {
                    setStatus(err.message, 'err');
                } finally {
                    saveInline.disabled = false;
                }
                return;
            }
            const askInline = event.target.closest('[data-inline-ask]');
            if (askInline) {
                askInline.disabled = true;
                try {
                    await askInlineCoach(askInline.dataset.inlineAsk);
                } finally {
                    askInline.disabled = false;
                }
                return;
            }
            const applyInline = event.target.closest('[data-inline-apply]');
            if (applyInline) {
                const field = applyInline.dataset.inlineApply;
                const review = assumptionAnnotationFor(field);
                const suggested = review?.suggested_value;
                if (suggested !== null && suggested !== undefined && suggested !== '') {
                    const input = $(assumptionMap[field]);
                    if (input) input.value = suggested;
                }
                state.inlinePopoverField = '';
                invalidateFrom('assumptions', false);
                renderInlineAnnotations();
            }
        });
        $('assumptionGuidePanel').addEventListener('input', (event) => {
            const valueInput = event.target.closest('[data-guided-value]');
            if (valueInput) {
                syncGuidedValue(valueInput.dataset.guidedValue, valueInput.value);
                return;
            }
            const evidenceInput = event.target.closest('[data-assumption-evidence]');
            if (evidenceInput) {
                state.assumptionEvidenceDrafts[evidenceInput.dataset.assumptionEvidence] = evidenceInput.value.trim();
                invalidateFrom('assumptions', false);
                renderCoachFocus();
                renderInlineAnnotations();
            }
        });
        $('assumptionGuidePanel').addEventListener('click', (event) => {
            const stepBtn = event.target.closest('[data-assumption-step]');
            if (stepBtn) {
                focusAssumptionStep(stepBtn.dataset.assumptionStep);
                return;
            }
            const focusBtn = event.target.closest('[data-focus-assumption]');
            if (focusBtn) {
                const steps = visibleAssumptionSteps();
                const idx = steps.findIndex((step) => step.key === focusBtn.dataset.focusAssumption);
                if (idx >= 0) focusAssumptionStep(idx);
                else focusInlineAnnotation(focusBtn.dataset.focusAssumption, false);
                return;
            }
            if (event.target.closest('[data-prev-assumption]')) {
                focusAssumptionStep(state.assumptionStepIndex - 1);
                return;
            }
            if (event.target.closest('[data-skip-assumption]')) {
                skipActiveAssumptionMetric();
                return;
            }
            const pbJump = event.target.closest('[data-pb-jump]');
            if (pbJump && !pbJump.disabled) {
                setPbProcessStep(pbJump.dataset.pbJump);
                return;
            }
            if (event.target.closest('[data-prev-pb-step]')) {
                setPbProcessStep(state.pbProcessStepIndex - 1);
                return;
            }
            const pbSkipStep = event.target.closest('[data-pb-skip-step]');
            if (pbSkipStep) {
                skipBlockedPbStep(pbSkipStep.dataset.pbSkipStep);
                return;
            }
            const pbSkipMetric = event.target.closest('[data-pb-skip-metric]');
            if (pbSkipMetric) {
                skipPbMetric(pbSkipMetric.dataset.pbStepKey, pbSkipMetric.dataset.pbSkipMetric);
                return;
            }
            if (event.target.closest('[data-next-pb-step]')) {
                const finished = advancePbStep();
                if (finished) {
                    state.assumptionStepIndex = 0;
                    renderGuidedAssumptions();
                    renderWorkflowRail();
                    saveAssumptions(false);
                }
                return;
            }
            if (event.target.closest('[data-coach-assumption]')) {
                const step = visibleAssumptionSteps()[state.assumptionStepIndex];
                if (step?.key) {
                    $('coachField').value = step.key;
                    const evidence = currentAssumptionEvidence()[step.key] || '';
                    $('coachMessage').value = evidence || `${assumptionLabel(step.key)} = ${currentUiAssumptions()[step.key] ?? '-'}，请追问这个假设的证据是否充分。`;
                    renderCoachFocus();
                    askCoach();
                }
                return;
            }
            if (event.target.closest('[data-next-assumption]')) {
                if (advanceAssumptionStep()) {
                    saveAssumptions();
                }
            }
        });
        $('saveConfigBtn').addEventListener('click', saveConfig);
        $('refreshCasesBtn').addEventListener('click', () => loadCases().catch((err) => setStatus(err.message, 'err')));
        $('toggleConfigBtn').addEventListener('click', () => $('configPanel').classList.toggle('active'));
        $('resetConfigBtn').addEventListener('click', () => {
            state.config = JSON.parse(JSON.stringify(state.defaults || {}));
            renderConfig(state.config);
            setStatus('已恢复默认字段，保存后生效', 'warn');
        });
        $('stockInput').addEventListener('input', (event) => {
            window.clearTimeout(window.__valuationSearchTimer);
            const value = event.target.value.trim();
            window.__valuationSearchTimer = window.setTimeout(() => searchStocks(value), 220);
        });
        $('stockInput').addEventListener('keydown', (event) => {
            if (event.key === 'Enter') fetchFacts();
        });
        $('suggestions').addEventListener('click', (event) => {
            const btn = event.target.closest('.suggestion');
            if (!btn) return;
            const code = btn.dataset.code || '';
            const name = btn.dataset.name || '';
            $('stockInput').value = `${code} ${name}`.trim();
            state.stockCode = code;
            $('suggestions').classList.remove('active');
            fetchFacts();
        });
        $('caseList').addEventListener('click', (event) => {
            const btn = event.target.closest('[data-open-case]');
            if (btn) openCase(btn.dataset.openCase);
            const deleteBtn = event.target.closest('[data-delete-case]');
            if (deleteBtn) deleteCase(deleteBtn.dataset.deleteCase, deleteBtn.dataset.caseLabel);
        });
        document.addEventListener('click', (event) => {
            if (!event.target.closest('.stock-search')) $('suggestions').classList.remove('active');
        });
    }

    function init() {
        $('asOfInput').value = new Date().toISOString().slice(0, 10);
        bindEvents();
        renderDataDates({});
        renderScenariosFromGuide(null);
        renderResults({ methods: [] });
        renderConclusion();
        renderCounterEvidence();
        renderAssumptionReview();
        renderCoachThread();
        renderMethodDecision(null);
        renderRecommendations([]);
        renderCaseScope();
        methodDefinitions.length;
        loadConfig().catch((err) => setStatus(err.message, 'err'));
        loadCases().catch(() => {});
    }

    init();
})();
