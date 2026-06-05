# -*- coding: utf-8 -*-
# AUTO-SPLIT from legacy app.py lines 2604-4864.
# Section: security tables, login helpers, RBAC, tenant migration, init_db, health checks.
# Loaded by root app.py; keep project-root paths based on root app.py.

# ==================== 动量评分日志收集器 ====================
# 用于在前端显示执行进度
momentum_logs = {}  # {task_id: deque([log1, log2, ...])}
momentum_logs_lock = threading.Lock()
MOMENTUM_LOG_MAX_SIZE = 1000  # 每个任务最多保存1000条日志


class MomentumLogHandler(logging.Handler):
    """自定义日志处理器，将日志收集到内存中"""
    def __init__(self, task_id):
        super().__init__()
        self.task_id = task_id
    
    def emit(self, record):
        try:
            log_msg = self.format(record)
            # 过滤掉一些不重要的日志
            if any(skip in log_msg for skip in ['GET /', 'POST /', 'HTTP/1.1', '172.16.', '127.0.0.1']):
                return
            
            timestamp = datetime.now().strftime('%H:%M:%S')
            log_entry = f"[{timestamp}] {log_msg}"
            
            with momentum_logs_lock:
                if self.task_id not in momentum_logs:
                    momentum_logs[self.task_id] = deque(maxlen=MOMENTUM_LOG_MAX_SIZE)
                momentum_logs[self.task_id].append(log_entry)
        except Exception:
            pass  # 忽略日志收集错误，避免影响主流程


def get_momentum_logs(task_id, last_index=0):
    """获取任务日志（从指定索引开始）"""
    with momentum_logs_lock:
        if task_id not in momentum_logs:
            return [], 0
        
        logs = list(momentum_logs[task_id])
        if last_index >= len(logs):
            return [], len(logs)
        
        return logs[last_index:], len(logs)


def clear_momentum_logs(task_id):
    """清理任务日志"""
    with momentum_logs_lock:
        if task_id in momentum_logs:
            del momentum_logs[task_id]

# 访问日志表
def init_security_tables(conn, c):
    """初始化安全相关的表"""
    # 登录尝试记录表
    c.execute('''CREATE TABLE IF NOT EXISTS login_attempts
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 ip_address TEXT NOT NULL,
                 username TEXT,
                 attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 success INTEGER DEFAULT 0)''')
    
    # 访问日志表
    c.execute('''CREATE TABLE IF NOT EXISTS access_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT,
                 ip_address TEXT,
                 endpoint TEXT,
                 method TEXT,
                 access_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS audit_events
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 request_id TEXT,
                 username TEXT,
                 ip_address TEXT,
                 endpoint TEXT,
                 method TEXT,
                 path TEXT,
                 action TEXT NOT NULL,
                 resource_type TEXT,
                 resource_id TEXT,
                 success INTEGER DEFAULT 1,
                 details_json TEXT,
                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()

# 密码哈希函数
def _is_legacy_sha256_password_hash(stored_hash):
    parts = (stored_hash or "").split(":")
    if len(parts) != 2:
        return False
    salt, digest = parts
    return bool(
        re.fullmatch(r"[0-9a-fA-F]{32}", salt or "")
        and re.fullmatch(r"[0-9a-fA-F]{64}", digest or "")
    )


def hash_password(password):
    """Hash passwords with Werkzeug when available; keep a legacy fallback for old installs."""
    password = password or ""
    if generate_password_hash is not None:
        return generate_password_hash(password)
    salt = secrets.token_hex(16)
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}:{password_hash}"

def verify_password(password, stored_hash):
    """验证密码"""
    password = password or ""
    stored_hash = stored_hash or ""
    try:
        if _is_legacy_sha256_password_hash(stored_hash):
            salt, password_hash = stored_hash.split(':')
            return hashlib.sha256((password + salt).encode()).hexdigest() == password_hash
        if check_password_hash is not None:
            return check_password_hash(stored_hash, password)
    except Exception:
        return False
    return False


def _password_hash_needs_upgrade(stored_hash):
    return not stored_hash or _is_legacy_sha256_password_hash(stored_hash) or ":" not in stored_hash

# 检查登录尝试次数
def check_login_attempts(ip_address, username=None):
    """检查登录尝试次数是否超限"""
    conn = get_sqlite_connection()
    try:
        c = conn.cursor()
        c.execute("""SELECT COUNT(*) FROM login_attempts
                     WHERE ip_address = ? AND success = 0
                     AND attempt_time > datetime('now', '-15 minutes')""",
                  (ip_address,))
        failed_attempts = c.fetchone()[0]
    finally:
        conn.close()
    return failed_attempts < MAX_LOGIN_ATTEMPTS

# 记录登录尝试
def log_login_attempt(ip_address, username, success):
    """记录登录尝试"""
    conn = get_sqlite_connection()
    try:
        c = conn.cursor()
        c.execute("INSERT INTO login_attempts (ip_address, username, success) VALUES (?, ?, ?)",
                  (ip_address, username, 1 if success else 0))
        conn.commit()
    finally:
        conn.close()

# 记录访问日志
def log_access(username, endpoint, method):
    """记录访问日志"""
    if not ACCESS_LOG_ENABLED:
        return
    try:
        ip_address = request.remote_addr
        with _access_log_lock:
            _access_log_buffer.append((username, ip_address, endpoint, method))
        _access_log_flush()
    except:
        pass  # 日志记录失败不影响主功能

# 登录验证装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return _auth_login_required_response()
        return f(*args, **kwargs)
    return decorated_function


# ==================== RBAC 权限模型（用户-角色-权限）====================

def _init_rbac_tables(c):
    """创建角色、权限及关联表。"""
    c.execute('''CREATE TABLE IF NOT EXISTS permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        module TEXT,
        description TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT NOT NULL UNIQUE,
        description TEXT,
        is_system INTEGER NOT NULL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS role_permissions (
        role_id INTEGER NOT NULL,
        permission_id INTEGER NOT NULL,
        PRIMARY KEY (role_id, permission_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS user_roles (
        user_id INTEGER NOT NULL,
        role_id INTEGER NOT NULL,
        PRIMARY KEY (user_id, role_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS rbac_migrations (
        name TEXT PRIMARY KEY
    )''')


# 权限字典：代码中新增权限码时由 init_db 写入 permissions；admin 始终拥有全部。member 的默认授权由迁移/管理员显式配置决定，不再自动「全家桶」。
_RBAC_LEGACY_PERMS = [
    ('app:access', '基础访问', 'app', '写随笔/复盘、AI 分析、导出、市场基调与指数设置、首页内联编辑等'),
    ('app:index', '首页入口', 'app', '登录后可进入首页与统计壳；不含写随笔/复盘/AI/导出'),
    ('diary:content', '首页日记区', 'diary', '首页「今日市场数据」与「最近记录」等日记相关展示'),
    ('rbac:admin', '系统权限管理', 'rbac', '用户管理、角色管理、权限分配（全局）'),
    ('crawler:dashboard', '爬虫看板', 'crawler', '爬虫数据看板、主线分析与主线延续'),
    ('calendar:module', '投资日历', 'calendar', '日历视图与提醒'),
    ('plans:module', '投资计划', 'plans', '投资计划与进度'),
    ('reports:module', '深度报告', 'reports', '深度报告管理'),
    ('ai_research:module', 'AI 研究助理', 'ai_research', '收盘复盘草稿、新闻主线记忆、交易教练、个股档案、GRU解释、报告精读、明日观察和运维巡检'),
    ('trading_agents:module', '交易体系 Agent', 'trading_agents', '书籍交易体系蒸馏、规则库与实盘决策内参'),
    ('concept_stocks:module', '概念板块', 'concept', '概念板块与行业树'),
    ('market_sentiment:module', '市场情绪', 'sentiment', '市场情绪看板与相关接口'),
    ('topics:module', '脑图', 'topics', '脑图与关系卡片'),
    ('industry_inventory:module', '库存分析', 'industry', '库存分析'),
    ('data_center:module', '数据中枢', 'data_center', '统一查看数据状态、任务健康与单票跨模块画像'),
    ('data_query:module', '数据查询', 'data_query', '数据查询构建器'),
    ('screening_tasks:module', '筛选任务', 'screening', '筛选任务与历史'),
    ('momentum_scores:module', '动量评分', 'momentum', '动量评分'),
    ('holding_costs:module', '持仓成本', 'holding_costs', '聚源收盘价平均持仓成本与成交量加权成本'),
    ('valuation:module', '估值锚', 'valuation', '聚源字段、手工输入与 DCF/PE/PB/PS 等主流估值方法'),
    ('gru:module', 'GRU 选股器', 'gru', 'GRU 回测、股票清单、任务队列与本地 worker 状态'),
    ('portfolio:module', '组合分析', 'portfolio', '组合导入与分析'),
]


_RBAC_SPLIT_MODULES = [
    ('app', '基础与首页', 'app:view', '基础查看', '进入首页与基础工作台壳', 'app:operate', '基础操作', '写随笔/复盘、AI 分析、导出、市场基调与指数设置'),
    ('crawler', '爬虫看板', 'crawler:view', '爬虫查看', '查看爬虫看板、资讯流、主线分析与主线延续', 'crawler:operate', '爬虫操作', '执行 AI 分析、导出、监控、清理规则、删除资讯和维护词云黑名单'),
    ('calendar', '投资日历', 'calendar:view', '日历查看', '查看日历、提醒和月度上下文', 'calendar:operate', '日历操作', '新增、编辑、删除日历事件和快捷记录'),
    ('plans', '投资计划', 'plans:view', '计划查看', '查看投资计划、图谱和工作台', 'plans:operate', '计划操作', '新增、编辑、删除计划，更新进度和重建关联'),
    ('reports', '深度报告', 'reports:view', '报告查看', '查看报告、PDF、EPUB、对比和阅读器', 'reports:operate', '报告操作', '新增、上传、删除、标注、关联、导出和保存深度报告'),
    ('ai_research', 'AI 研究助理', 'ai_research:view', 'AI 研究查看', '查看 AI 研究助理模块和历史输出', 'ai_research:operate', 'AI 研究操作', '启动 AI 研究任务和生成输出'),
    ('trading_agents', '交易体系 Agent', 'trading_agents:view', 'Agent 查看', '查看交易体系 Agent、规则库和任务结果', 'trading_agents:operate', 'Agent 操作', '创建蒸馏、决策、协作报告和删除 Agent'),
    ('concept_stocks', '概念板块', 'concept_stocks:view', '概念查看', '查看概念板块、行业树和概念股列表', 'concept_stocks:operate', '概念操作', '新增、删除概念，识别图片和更新行业股票'),
    ('market_sentiment', '市场情绪', 'market_sentiment:view', '情绪查看', '查看市场情绪看板、缓存、报表和历史指标', 'market_sentiment:operate', '情绪操作', '计算情绪评分、区间评分、AI 报告和导出'),
    ('topics', '脑图', 'topics:view', '脑图查看', '查看脑图、深度思考和关系卡片', 'topics:operate', '脑图操作', '新增、编辑、删除、导入导出脑图，生成深度思考内容'),
    ('industry_inventory', '库存分析', 'industry_inventory:view', '库存查看', '查看库存分析页面与行业数据', 'industry_inventory:operate', '库存操作', '执行股票、行业搜索和分析'),
    ('data_center', '数据中枢', 'data_center:view', '数据中枢查看', '查看数据状态、任务健康与单票画像', 'data_center:operate', '数据中枢操作', '启动全市场 AI 复盘和每日数据任务'),
    ('data_query', '数据查询', 'data_query:view', '数据查询查看', '查看查询构建器、表配置、字段和模板', 'data_query:operate', '数据查询操作', '保存/删除配置，执行查询，识别表结构和初始化预设'),
    ('screening_tasks', '筛选任务', 'screening_tasks:view', '筛选查看', '查看筛选任务、历史和结果', 'screening_tasks:operate', '筛选操作', '执行筛选任务、清理任务和下载结果'),
    ('momentum_scores', '动量评分', 'momentum_scores:view', '动量查看', '查看动量评分、配置、日志和历史', 'momentum_scores:operate', '动量操作', '运行评分、计算性格、创建计划'),
    ('holding_costs', '持仓成本', 'holding_costs:view', '持仓成本查看', '查看平均持仓成本、日期和汇总', 'holding_costs:operate', '持仓成本操作', '预留给持仓成本维护与批处理操作'),
    ('valuation', '估值锚', 'valuation:view', '估值查看', '查看估值工作台、聚源字段和估值结果', 'valuation:operate', '估值操作', '保存字段配置、计算估值和保存估值快照'),
    ('gru', 'GRU 选股器', 'gru:view', 'GRU 查看', '查看 GRU 配置、队列、回测和股票清单', 'gru:operate', 'GRU 操作', '执行 GRU 任务、取消队列和恢复任务'),
    ('portfolio', '组合分析', 'portfolio:view', '组合查看', '查看组合、映射、日期范围和分析结果', 'portfolio:operate', '组合操作', '导入组合、保存映射、预处理和执行组合分析'),
    ('rbac', '权限管理', 'rbac:view', '权限查看', '查看用户、角色、权限和审计', 'rbac:operate', '权限操作', '创建/删除角色，修改角色权限，创建/禁用/删除用户'),
]


def _rbac_split_permissions():
    rows = []
    for module, _title, view_code, view_name, view_desc, operate_code, operate_name, operate_desc in _RBAC_SPLIT_MODULES:
        rows.append((view_code, view_name, module, view_desc))
        rows.append((operate_code, operate_name, module, operate_desc))
    return rows


_RBAC_ALL_PERMS = _RBAC_LEGACY_PERMS + _rbac_split_permissions()

_RBAC_LEGACY_PERMISSION_ALIASES = {
    'app:index': ('app:view',),
    'app:access': ('app:view', 'app:operate'),
    'crawler:dashboard': ('crawler:view', 'crawler:operate'),
    'calendar:module': ('calendar:view', 'calendar:operate'),
    'plans:module': ('plans:view', 'plans:operate'),
    'reports:module': ('reports:view', 'reports:operate'),
    'ai_research:module': ('ai_research:view', 'ai_research:operate'),
    'trading_agents:module': ('trading_agents:view', 'trading_agents:operate'),
    'concept_stocks:module': ('concept_stocks:view', 'concept_stocks:operate'),
    'market_sentiment:module': ('market_sentiment:view', 'market_sentiment:operate'),
    'topics:module': ('topics:view', 'topics:operate'),
    'industry_inventory:module': ('industry_inventory:view', 'industry_inventory:operate'),
    'data_center:module': ('data_center:view', 'data_center:operate'),
    'data_query:module': ('data_query:view', 'data_query:operate'),
    'screening_tasks:module': ('screening_tasks:view', 'screening_tasks:operate'),
    'momentum_scores:module': ('momentum_scores:view', 'momentum_scores:operate'),
    'holding_costs:module': ('holding_costs:view', 'holding_costs:operate'),
    'valuation:module': ('valuation:view', 'valuation:operate'),
    'gru:module': ('gru:view', 'gru:operate'),
    'portfolio:module': ('portfolio:view', 'portfolio:operate'),
}

_RBAC_TEMPLATE_PERMISSION_ALIASES = {
    **_RBAC_LEGACY_PERMISSION_ALIASES,
    'app:access': ('app:operate',),
    'app:index': ('app:view',),
}

_RBAC_OPERATE_TO_VIEW_ALIASES = {
    operate_code: (view_code,)
    for _module, _title, view_code, _view_name, _view_desc, operate_code, _operate_name, _operate_desc in _RBAC_SPLIT_MODULES
}


def _rbac_permission_code_grants(owned_codes, required_code, include_descendants=False):
    owned = set(owned_codes or ())
    code = (required_code or '').strip()
    if not code:
        return False
    if code in owned or 'rbac:admin' in owned:
        return True
    # 兼容旧角色：旧的 module 权限等价于该模块的查看 + 操作。
    for legacy_code, split_codes in _RBAC_LEGACY_PERMISSION_ALIASES.items():
        if code in split_codes and legacy_code in owned:
            return True
    # 操作权限天然包含查看权限：否则可以提交任务，却无法读取任务状态或页面数据。
    if any(operate_code in owned for operate_code, view_codes in _RBAC_OPERATE_TO_VIEW_ALIASES.items() if code in view_codes):
        return True
    # 模板入口仍有大量 has_perm('xxx:module')，这里让新 view/operate 权限可以点亮入口。
    if include_descendants:
        return any(alias in owned for alias in _RBAC_TEMPLATE_PERMISSION_ALIASES.get(code, ()))
    return False


def _index_entry_permission_codes():
    """进入首页 `/`：持有任一已登记权限即可（OR），便于「仅有模块权」用户进入壳页。"""
    return tuple(p[0] for p in _RBAC_ALL_PERMS)


# 该用户名始终绑定「系统管理员」角色（即使库中曾缺失，也会在 init_db / 登录时补全）。匹配时不区分大小写、忽略首尾空格。
RBAC_SUPERUSER_USERNAME = 'tanjiarong'

# ---------- users 主键约定（全链路一致）----------
# SQLite 下 API 返回的「用户 id」= COALESCE(users.id, users.rowid)。user_roles.user_id 存同一数值。
# 任意「按用户查 / 改 / 删」必须用 WHERE COALESCE(id,rowid)=?；与 user_roles 连接必须用 COALESCE(u.id,u.rowid)=ur.user_id。
# 避免出现列表里是 1、PUT 却 WHERE id=1 查不到（id 为 NULL 时）→「用户不存在」。


def _safe_int(value, default=None):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _rbac_is_configured_superuser_login_name(name):
    su = (RBAC_SUPERUSER_USERNAME or '').strip().lower()
    if not su:
        return False
    return (name or '').strip().lower() == su


def _rbac_ensure_superuser_admin_for_user_id(user_id):
    """为指定用户 id 绑定 admin 角色（INSERT OR IGNORE）。"""
    now = time.time()
    cached_at = _rbac_superuser_admin_cache.get(user_id)
    if cached_at and now - cached_at < RBAC_SUPERUSER_CACHE_TTL:
        return
    try:
        conn = get_sqlite_connection()
        c = conn.cursor()
        _ensure_core_roles(c)
        _sync_permission_definitions_and_grants(c)
        c.execute('SELECT id FROM roles WHERE slug=?', ('admin',))
        ra = c.fetchone()
        if ra:
            c.execute(
                'INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?,?)',
                (user_id, ra[0]),
            )
        conn.commit()
        conn.close()
        _rbac_superuser_admin_cache[user_id] = now
        _rbac_invalidate_permission_cache()
    except Exception as e:
        logging.error('_rbac_ensure_superuser_admin_for_user_id: %s', e, exc_info=True)


def _ensure_core_roles(c):
    c.execute('SELECT id FROM roles WHERE slug=?', ('admin',))
    if c.fetchone() is None:
        c.execute(
            "INSERT INTO roles (name, slug, description, is_system) VALUES (?,?,?,?)",
            ('系统管理员', 'admin', '拥有 rbac:admin，可管理用户与权限', 1),
        )
    c.execute('SELECT id FROM roles WHERE slug=?', ('member',))
    if c.fetchone() is None:
        c.execute(
            "INSERT INTO roles (name, slug, description, is_system) VALUES (?,?,?,?)",
            ('普通成员', 'member', '默认业务访问', 1),
        )


def _rbac_migrate_scrub_member_overgrants_once(c):
    """一次性迁移：历史上误把大量权限同步到 member，先清空仅保留 app:access，由管理员在后台再精细分配。"""
    c.execute('SELECT 1 FROM rbac_migrations WHERE name=? LIMIT 1', ('scrub_member_overgrants_v1',))
    if c.fetchone():
        return
    c.execute('SELECT id FROM roles WHERE slug=?', ('member',))
    mr = c.fetchone()
    if not mr:
        return
    member_id = mr[0]
    c.execute('DELETE FROM role_permissions WHERE role_id=?', (member_id,))
    c.execute('SELECT id FROM permissions WHERE code=?', ('app:access',))
    row_ac = c.fetchone()
    if row_ac:
        c.execute(
            'INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?,?)',
            (member_id, row_ac[0]),
        )
    c.execute('INSERT OR IGNORE INTO rbac_migrations (name) VALUES (?)', ('scrub_member_overgrants_v1',))
    logging.info(
        '[rbac_sync] scrub_member_overgrants_v1: reset member role_permissions to app:access only (member_id=%s)',
        member_id,
    )


def _rbac_migrate_member_shell_index_v2(c):
    """一次性：member 默认不应持有 app:access（否则首页写随笔/复盘/AI 始终可点）。改为仅 app:index，写操作需显式授予 app:access。"""
    c.execute('SELECT 1 FROM rbac_migrations WHERE name=? LIMIT 1', ('member_shell_app_index_v2',))
    if c.fetchone():
        return
    c.execute('SELECT id FROM roles WHERE slug=?', ('member',))
    mr = c.fetchone()
    if not mr:
        return
    member_id = mr[0]
    c.execute(
        'DELETE FROM role_permissions WHERE role_id=? AND permission_id IN (SELECT id FROM permissions WHERE code=?)',
        (member_id, 'app:access'),
    )
    c.execute('SELECT id FROM permissions WHERE code=?', ('app:index',))
    row_ix = c.fetchone()
    if row_ix:
        c.execute(
            'INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?,?)',
            (member_id, row_ix[0]),
        )
    c.execute('INSERT OR IGNORE INTO rbac_migrations (name) VALUES (?)', ('member_shell_app_index_v2',))
    logging.info(
        '[rbac_sync] member_shell_app_index_v2: member role no longer defaults to app:access; ensured app:index (member_id=%s)',
        member_id,
    )


def _rbac_migrate_ai_workbench_owner_access_v1(c):
    """一次性：把 AI 研究助理和数据中枢补给主账号/首个管理员，避免老库升级后入口隐身。"""
    c.execute('SELECT 1 FROM rbac_migrations WHERE name=? LIMIT 1', ('ai_workbench_owner_access_v1',))
    if c.fetchone():
        return
    needed_codes = ('ai_research:module', 'data_center:module')
    c.execute('SELECT id FROM roles WHERE slug=?', ('admin',))
    admin_row = c.fetchone()
    admin_id = admin_row[0] if admin_row else None
    user_ids = set()
    c.execute(
        'SELECT COALESCE(id, rowid) FROM users WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1',
        ((RBAC_SUPERUSER_USERNAME or '').strip(),),
    )
    row_su = c.fetchone()
    su_id = _safe_int(row_su[0] if row_su else None)
    if su_id is not None:
        user_ids.add(su_id)
    c.execute('SELECT COALESCE(id, rowid) FROM users ORDER BY COALESCE(id, rowid) ASC LIMIT 1')
    row_first = c.fetchone()
    first_id = _safe_int(row_first[0] if row_first else None)
    if first_id is not None:
        user_ids.add(first_id)
    if admin_id and user_ids:
        for uid in sorted(user_ids):
            c.execute(
                'INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?,?)',
                (uid, admin_id),
            )
    c.execute('INSERT OR IGNORE INTO rbac_migrations (name) VALUES (?)', ('ai_workbench_owner_access_v1',))
    logging.info(
        '[rbac_sync] ai_workbench_owner_access_v1: ensured %s for owner/admin users %s',
        ','.join(needed_codes),
        sorted(user_ids),
    )


def _rbac_migrate_split_permissions_v1(c):
    """把旧模块权限复制成 view/operate，升级后保留原有角色能力。"""
    c.execute('SELECT 1 FROM rbac_migrations WHERE name=? LIMIT 1', ('split_view_operate_permissions_v1',))
    if c.fetchone():
        return
    for legacy_code, split_codes in _RBAC_LEGACY_PERMISSION_ALIASES.items():
        c.execute('SELECT id FROM permissions WHERE code=?', (legacy_code,))
        legacy_row = c.fetchone()
        if not legacy_row:
            continue
        legacy_pid = legacy_row[0]
        c.execute('SELECT role_id FROM role_permissions WHERE permission_id=?', (legacy_pid,))
        role_ids = [row[0] for row in c.fetchall() if row and row[0] is not None]
        if not role_ids:
            continue
        for split_code in split_codes:
            c.execute('SELECT id FROM permissions WHERE code=?', (split_code,))
            split_row = c.fetchone()
            if not split_row:
                continue
            split_pid = split_row[0]
            for role_id in role_ids:
                c.execute(
                    'INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?,?)',
                    (role_id, split_pid),
                )
    c.execute('INSERT OR IGNORE INTO rbac_migrations (name) VALUES (?)', ('split_view_operate_permissions_v1',))
    logging.info('[rbac_sync] split_view_operate_permissions_v1: copied legacy module grants to view/operate grants')


def _sync_permission_definitions_and_grants(c):
    """确保 permissions 表与代码一致；admin 拥有全部权限；member 不再因「新权限码」自动获权。"""
    c.execute('SELECT id FROM roles WHERE slug=?', ('admin',))
    ra = c.fetchone()
    c.execute('SELECT id FROM roles WHERE slug=?', ('member',))
    rm = c.fetchone()
    if not ra or not rm:
        return False
    admin_id, member_id = ra[0], rm[0]
    for code, name, module, desc in _RBAC_ALL_PERMS:
        c.execute('SELECT id FROM permissions WHERE code=?', (code,))
        row = c.fetchone()
        if row:
            pid = row[0]
        else:
            c.execute(
                'INSERT INTO permissions (code, name, module, description) VALUES (?,?,?,?)',
                (code, name, module, desc),
            )
            pid = c.lastrowid
        c.execute(
            'INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?,?)',
            (admin_id, pid),
        )
    _rbac_migrate_scrub_member_overgrants_once(c)
    _rbac_migrate_member_shell_index_v2(c)
    _rbac_migrate_ai_workbench_owner_access_v1(c)
    _rbac_migrate_split_permissions_v1(c)
    # 仅当 member 角色尚未关联任何权限时补挂 app:index（旧库空白兜底），不自动给 app:access。
    # 禁止在每次 sync 时无条件 INSERT：否则管理员从 member 上摘掉 app:access / diary:content 后，
    # 会在下一次 _rbac_repair_login_access / bootstrap 时又被塞回去，首页权限开关「永远关不掉」。
    c.execute('SELECT COUNT(*) FROM role_permissions WHERE role_id = ?', (member_id,))
    _mc = c.fetchone()
    if _mc and int(_mc[0]) == 0:
        c.execute('SELECT id FROM permissions WHERE code=?', ('app:index',))
        row_ix = c.fetchone()
        if row_ix:
            c.execute(
                'INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?,?)',
                (member_id, row_ix[0]),
            )
            logging.info(
                '[rbac_sync] member_role had zero permissions; auto_granted app:index only '
                '(member_id=%s permission_id=%s)',
                member_id,
                row_ix[0],
            )
    return True


def _rbac_assign_superuser_admin(c):
    c.execute(
        'SELECT COALESCE(id, rowid) FROM users WHERE lower(trim(username)) = lower(trim(?))',
        ((RBAC_SUPERUSER_USERNAME or '').strip(),),
    )
    tu = c.fetchone()
    c.execute('SELECT id FROM roles WHERE slug=?', ('admin',))
    ra = c.fetchone()
    if tu and ra:
        c.execute(
            'INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?,?)',
            (tu[0], ra[0]),
        )


def _merge_rbac_endpoint_permission_map():
    """Flask view 函数名 → 所需权限。集中与 before_request 一致。"""
    m = {}
    adm = ('rbac:admin',)
    appv = ('app:view',)
    appo = ('app:operate',)
    crv = ('crawler:view',)
    cro = ('crawler:operate',)
    calv = ('calendar:view',)
    calo = ('calendar:operate',)
    plv = ('plans:view',)
    plo = ('plans:operate',)
    repv = ('reports:view',)
    repo = ('reports:operate',)
    airv = ('ai_research:view',)
    airo = ('ai_research:operate',)
    tav = ('trading_agents:view',)
    tao = ('trading_agents:operate',)
    conv = ('concept_stocks:view',)
    cono = ('concept_stocks:operate',)
    senv = ('market_sentiment:view',)
    seno = ('market_sentiment:operate',)
    topv = ('topics:view',)
    topo = ('topics:operate',)
    indv = ('industry_inventory:view',)
    indo = ('industry_inventory:operate',)
    dcv = ('data_center:view',)
    dco = ('data_center:operate',)
    dqv = ('data_query:view',)
    dqo = ('data_query:operate',)
    scrv = ('screening_tasks:view',)
    scro = ('screening_tasks:operate',)
    momv = ('momentum_scores:view',)
    momo = ('momentum_scores:operate',)
    valv = ('valuation:view',)
    valo = ('valuation:operate',)
    gruv = ('gru:view',)
    gruo = ('gru:operate',)
    prtv = ('portfolio:view',)
    prto = ('portfolio:operate',)
    hcv = ('holding_costs:view',)
    hco = ('holding_costs:operate',)
    for name in (
        'migrate_data', 'clean_duplicate_migrations',
        'admin_ai_provider', 'admin_ai_provider_status', 'admin_ai_provider_save', 'admin_ai_provider_test',
        'api_ai_provider_usage',
        'api_crawler_dashboard_yicai_ad_purge',
        'iching_page', 'api_iching_today', 'api_iching_plans', 'api_iching_divine', 'api_iching_history',
    ):
        m[name] = adm
    for name in (
        'admin_rbac_page', 'api_rbac_permissions_list', 'api_rbac_roles_list',
        'api_rbac_users_list', 'api_rbac_audit', 'api_rbac_permission_matrix',
    ):
        m[name] = ('rbac:view',)
    for name in (
        'api_rbac_roles_create', 'api_rbac_roles_delete', 'api_rbac_role_permissions_update',
        'api_rbac_users_create', 'api_rbac_users_update', 'api_rbac_users_delete',
    ):
        m[name] = ('rbac:operate',)
    for name in (
        'daily_workbench_page', 'market_context_page', 'daily_ai_analysis_page', 'daily_export_page',
        'experience_lessons_page', 'api_experience_lessons_latest', 'api_experience_lessons_snapshots',
        'api_experience_lessons_snapshot_detail', 'api_experience_lessons_status',
        'api_experience_lessons_quiz_attempts',
        'api_industry_terms_list', 'api_industry_terms_quiz',
        'export_excel', 'download_report', 'get_market_tone', 'get_index_trend',
    ):
        m[name] = appv
    for name in (
        'api_experience_lessons_run', 'add_essay', 'add_review', 'delete_essay', 'delete_review',
        'api_experience_lessons_quiz_note', 'api_experience_lessons_quiz_attempt_submit',
        'api_experience_lessons_quiz_attempt_reset',
        'api_experience_lessons_agent_rules', 'api_experience_lessons_snapshot_delete',
        'api_industry_terms_lookup', 'api_industry_terms_delete',
        'save_essay', 'save_review_field', 'ai_generate', 'upload_report',
        'set_market_tone', 'save_market_tone', 'set_index_trend', 'save_index_trend',
    ):
        m[name] = appo
    for name in (
        'crawler_dashboard', 'crawler_dashboard_wordcloud', 'api_crawler_dashboard_overview',
        'api_crawler_dashboard_channel_summary', 'api_crawler_dashboard_wordcloud',
        'api_crawler_wordcloud_blacklist_get',
        'api_crawler_dashboard_latest', 'api_crawler_dashboard_export',
        'api_crawler_dashboard_feed_state', 'api_crawler_dashboard_theme_analysis',
        'api_crawler_dashboard_theme_ai_latest', 'api_crawler_dashboard_mainline_continuity',
        'api_crawler_search', 'api_crawler_dashboard_monitor_hits',
        'timeline_page', 'api_timeline_list',
    ):
        m[name] = crv
    for name in (
        'api_crawler_wordcloud_blacklist_post', 'api_crawler_wordcloud_blacklist_delete',
        'api_crawler_dashboard_theme_ai_analysis', 'api_crawler_dashboard_mainline_continuity_ai',
        'api_timeline_add', 'api_timeline_delete',
        'api_crawler_dashboard_cleanup_apply_auto', 'api_crawler_dashboard_cleanup_preview',
        'api_crawler_dashboard_cleanup_purge', 'api_crawler_dashboard_cleanup_rules_delete',
        'api_crawler_dashboard_cleanup_rules_get', 'api_crawler_dashboard_cleanup_rules_post',
        'api_crawler_dashboard_cleanup_rules_update', 'api_crawler_dashboard_item_delete',
    ):
        m[name] = cro
    for name in (
        'calendar', 'get_calendar_events', 'check_reminders', 'get_lunar_date', 'api_calendar_month_context',
        'api_daily_dashboard',
    ):
        m[name] = calv
    for name in (
        'add_calendar_event', 'delete_calendar_event', 'save_calendar_event',
        'api_reviews_upsert', 'api_calendar_quick_add', 'api_delete_calendar_event',
    ):
        m[name] = calo
    for name in (
        'plans', 'api_plan_workbench', 'api_research_links_status', 'graph_view', 'api_graph_data',
        'kelly_calculator_page',
    ):
        m[name] = plv
    for name in (
        'add_plan', 'delete_plan', 'update_plan_status', 'update_plan_progress', 'update_plan_profitable',
        'api_plans_quick', 'api_plans_ai_from_text', 'api_rebuild_research_links',
    ):
        m[name] = plo
    for name in (
        'reports', 'view_report', 'report_workspace', 'report_compare_page',
        'report_reader', 'pdf_reader', 'pdf_report_file', 'pdf_report_download',
        'epub_library_reader', 'api_pdf_reports_list', 'api_reports_link_options',
        'api_reports_compare', 'epub_reader_page',
        'api_epub_reader_distill_task',
    ):
        m[name] = repv
    for name in (
        'add_report', 'delete_report', 'api_deep_report_autosave',
        'api_reports_upload', 'api_reports_save_annotation', 'api_reports_link_entity',
        'api_pdf_report_update_category', 'api_report_business_tab_create',
        'api_pdf_report_update_business_tab', 'api_pdf_report_delete',
        'api_epub_reader_read', 'api_epub_reader_download_epub',
        'api_epub_reader_save_epub_library', 'api_epub_reader_export_pdf',
        'api_epub_reader_distill', 'api_epub_reader_distill_plan',
        'api_epub_reader_distill_start', 'api_deep_thinking_save_report',
    ):
        m[name] = repo
    for name in (
        'ai_research_assistant_page', 'api_ai_research_assistant_modules',
        'api_ai_research_assistant_outputs', 'api_ai_research_assistant_output_detail',
        'api_ai_research_assistant_status',
    ):
        m[name] = airv
    for name in ('api_ai_research_assistant_run',):
        m[name] = airo
    for name in (
        'trading_agents_page', 'trading_agent_detail', 'api_trading_agents_list',
        'api_trading_agent_by_source', 'api_trading_agent_task', 'api_trading_agent_detail',
        'api_trading_agents_collaborative_decision_task',
    ):
        m[name] = tav
    for name in (
        'api_trading_agent_from_epub_start', 'api_trading_agent_delete',
        'api_trading_agent_decision', 'api_trading_agents_research_plan',
        'api_trading_agents_collaborative_decision', 'api_trading_agents_collaboration_report',
    ):
        m[name] = tao
    for name in (
        'concept_stocks', 'get_concept_stocks_list', 'get_concept_stocks',
        'get_industries_hierarchy',
    ):
        m[name] = conv
    for name in (
        'add_concept_stock', 'delete_concept_stock', 'recognize_stocks_from_images',
        'get_industry_stocks',
    ):
        m[name] = cono
    for name in (
        'market_sentiment',
        'api_market_sentiment_cached', 'api_market_sentiment_sparkline', 'api_market_sentiment_metric_history',
        'api_market_sentiment_report', 'api_market_sentiment_score_status',
        'api_market_sentiment_range_score_stream', 'api_market_sentiment_range_export',
    ):
        m[name] = senv
    for name in (
        'api_market_sentiment_ai_report', 'api_market_sentiment_score', 'api_market_sentiment_range_score',
    ):
        m[name] = seno
    for name in (
        'topics', 'edit_topic', 'export_topic_data', 'deep_thinking_page',
        'api_deep_thinking_task_status',
    ):
        m[name] = topv
    for name in (
        'add_topic', 'delete_topic', 'save_topic_info', 'save_card', 'delete_card',
        'save_connection', 'delete_connection', 'import_topic_data',
        'api_deep_thinking_guide', 'api_deep_thinking_guide_start',
        'api_deep_thinking_export_topic', 'api_deep_thinking_investment_topic',
        'api_deep_thinking_investment_topic_start', 'api_thinking_investment_logic',
    ):
        m[name] = topo
    for name in ('industry_inventory', 'get_industries'):
        m[name] = indv
    for name in ('search_stock', 'analyze_stock', 'analyze_industry'):
        m[name] = indo
    for name in (
        'data_center_page', 'api_data_center_status', 'api_data_center_stock',
        'stock_analysis_legacy', 'api_data_center_ai_review_status', 'api_data_center_daily_data_status',
    ):
        m[name] = dcv
    for name in ('api_data_center_ai_review_start', 'api_data_center_daily_data_start'):
        m[name] = dco
    for name in (
        'data_query_config', 'data_query_builder', 'get_table_configs', 'get_table_fields',
        'get_all_stocks', 'search_stock_for_query', 'get_sql_templates',
    ):
        m[name] = dqv
    for name in (
        'delete_table_config', 'save_field_config', 'delete_field_config', 'validate_fields',
        'save_sql_template', 'delete_sql_template', 'execute_template_query',
        'execute_multi_table_query', 'execute_data_query', 'recognize_table_from_text',
        'recognize_table_from_image', 'save_table_config', 'bootstrap_data_query_presets',
    ):
        m[name] = dqo
    for name in (
        'screening_tasks', 'get_task_types', 'screening_task_history',
        'screening_task_result_page', 'get_task_result', 'download_task_result',
    ):
        m[name] = scrv
    for name in ('execute_screening_task', 'cleanup_stale_screening_tasks'):
        m[name] = scro
    for name in (
        'momentum_scores_page', 'api_get_momentum_logs', 'api_get_momentum_scores',
        'api_get_momentum_status', 'api_get_momentum_config', 'api_get_latest_trading_date',
        'api_get_momentum_dates', 'api_get_daily_score_runs', 'api_momentum_scores_fused',
        'api_momentum_character_query', 'api_momentum_character_dates',
    ):
        m[name] = momv
    for name in ('api_run_momentum_scores', 'api_momentum_create_plan', 'api_momentum_character_calc'):
        m[name] = momo
    for name in (
        'stock_holding_costs_page', 'api_stock_holding_costs', 'api_stock_holding_costs_dates',
        'api_stock_holding_costs_summary',
    ):
        m[name] = hcv
    for name in (
        'stock_valuation_page', 'api_stock_valuation_config', 'api_stock_valuation_methods',
        'api_stock_valuation_fetch', 'api_stock_valuation_history',
        'api_stock_valuation_cases', 'api_stock_valuation_case_detail',
    ):
        m[name] = valv
    for name in (
        'api_stock_valuation_config_save', 'api_stock_valuation_calculate', 'api_stock_valuation_guide',
        'api_stock_valuation_case_create', 'api_stock_valuation_case_state',
        'api_stock_valuation_case_assumption', 'api_stock_valuation_case_scenarios',
        'api_stock_valuation_case_ai_coach',
    ):
        m[name] = valo
    for name in (
        'gru_tasks_page', 'api_gru_tasks_config', 'api_gru_tasks_queue_list',
        'api_gru_tasks_queue_detail', 'api_gru_backtest_runs', 'api_gru_backtest_run_detail',
        'api_gru_stock_list_runs', 'api_gru_stock_list_run_detail', 'api_gru_holding_cost_runs',
    ):
        m[name] = gruv
    for name in (
        'api_gru_tasks_execute', 'api_gru_tasks_queue_cancel', 'api_gru_tasks_queue_recover_stale',
    ):
        m[name] = gruo
    for name in (
        'portfolio_analysis', 'get_field_mappings', 'get_portfolio_list',
        'get_portfolio_date_range',
    ):
        m[name] = prtv
    for name in (
        'parse_excel_headers', 'save_field_mapping', 'import_portfolio_data',
        'preprocess_portfolio_data', 'get_market_value_analysis', 'get_stock_changes_analysis',
        'get_industry_changes_analysis', 'get_buy_performance_analysis',
        'get_trading_summary', 'get_stock_metrics',
        'get_industry_stock_details', 'get_portfolio_summary_analysis',
    ):
        m[name] = prto
    m['index'] = _index_entry_permission_codes()
    return m


RBAC_ENDPOINT_PERMISSIONS = _merge_rbac_endpoint_permission_map()
RBAC_LOGIN_ONLY_ENDPOINTS = frozenset({
    'api_rbac_me',
    'morning_brief_page',
    'api_morning_brief_latest',
    'api_morning_brief_generate',
    'api_morning_brief_history',
})
RBAC_PUBLIC_ENDPOINTS = frozenset({'static', 'login', 'register', 'logout', 'healthz', 'readyz', 'metrics', 'api_db_status'})


def _rbac_required_permission_codes(endpoint):
    """返回 endpoint 需要的权限；漏配的新业务路由默认只允许 RBAC 管理员访问。"""
    if not endpoint:
        return ('rbac:admin',)
    if endpoint in RBAC_LOGIN_ONLY_ENDPOINTS:
        return ()
    return RBAC_ENDPOINT_PERMISSIONS.get(endpoint, ('rbac:admin',))


def _rbac_unmapped_endpoints():
    """列出还没有显式权限归属的路由，供权限管理页审计。"""
    ignored = set(RBAC_PUBLIC_ENDPOINTS) | set(RBAC_LOGIN_ONLY_ENDPOINTS)
    rows = []
    for rule in app.url_map.iter_rules():
        endpoint = rule.endpoint
        if endpoint in ignored:
            continue
        if str(rule.rule).startswith(BRIDGE_PATH_PREFIX):
            continue
        if endpoint in RBAC_ENDPOINT_PERMISSIONS:
            continue
        rows.append({
            'endpoint': endpoint,
            'rule': str(rule.rule),
            'methods': sorted(m for m in rule.methods if m not in ('HEAD', 'OPTIONS')),
            'default_required': 'rbac:admin',
        })
    rows.sort(key=lambda x: (x['endpoint'] or '', x['rule'] or ''))
    return rows


def _seed_rbac_data(conn, c):
    """确保内置角色与权限目录；无角色用户挂 member；最小 id 用户与指定超管挂 admin。"""
    _repair_users_null_ids(c)
    _ensure_core_roles(c)
    if not _sync_permission_definitions_and_grants(c):
        return
    c.execute('SELECT id FROM roles WHERE slug=?', ('member',))
    row_m = c.fetchone()
    if not row_m:
        return
    member_id = row_m[0]
    c.execute('SELECT id FROM roles WHERE slug=?', ('admin',))
    row_a = c.fetchone()
    admin_id = row_a[0] if row_a else None
    # 部分旧库 users.id 可能为 NULL，先修复，再用兼容查询读取。
    c.execute('SELECT COALESCE(id, rowid) FROM users')
    user_ids = []
    for r in c.fetchall():
        if not r or r[0] is None:
            continue
        try:
            user_ids.append(int(r[0]))
        except (TypeError, ValueError):
            continue
    for uid in user_ids:
        c.execute('SELECT 1 FROM user_roles WHERE user_id=?', (uid,))
        if c.fetchone() is None:
            c.execute(
                'INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?,?)',
                (uid, member_id),
            )
    if admin_id and user_ids:
        first_uid = min(user_ids)
        c.execute(
            'INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?,?)',
            (first_uid, admin_id),
        )
    _rbac_assign_superuser_admin(c)


def _rbac_get_user_permission_codes(username):
    """返回用户通过角色继承到的权限 code 集合。"""
    if not username:
        return frozenset()
    uname = (username or '').strip()
    cached = _rbac_get_cached_permission_codes(uname)
    if cached is not None:
        return cached
    try:
        conn = get_sqlite_connection()
        c = conn.cursor()
        c.execute(
            'SELECT COALESCE(id, rowid), COALESCE(is_active, 1) FROM users WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1',
            (uname,),
        )
        uid_row = c.fetchone()
        if not uid_row or not uid_row[1]:
            conn.close()
            return frozenset()
        user_pk = _safe_int(uid_row[0])
        if user_pk is None:
            _repair_users_null_ids(c)
            conn.commit()
            c.execute(
                'SELECT COALESCE(id, rowid), COALESCE(is_active, 1) FROM users WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1',
                (uname,),
            )
            uid_row = c.fetchone()
            if not uid_row or not uid_row[1]:
                conn.close()
                return frozenset()
            user_pk = _safe_int(uid_row[0])
        if user_pk is None:
            conn.close()
            logging.error('读取用户权限失败 username=%r: users.id is NULL after repair', username)
            return frozenset()
        c.execute(
            '''SELECT DISTINCT p.code FROM permissions p
               INNER JOIN role_permissions rp ON rp.permission_id = p.id
               INNER JOIN user_roles ur ON ur.role_id = rp.role_id
               WHERE ur.user_id = ?''',
            (user_pk,),
        )
        codes = frozenset(row[0] for row in c.fetchall() if row and row[0])
        conn.close()
        return _rbac_set_cached_permission_codes(uname, codes)
    except Exception as e:
        logging.error('读取用户权限失败 username=%r: %s', username, e, exc_info=True)
        return frozenset()


def _rbac_log_home_permission_snapshot(username, owned_codes, did_repair, show_diary, can_write):
    """首页权限诊断：控制台/文件里 grep `[rbac_home]`。"""
    u = (username or '').strip()
    if not u:
        logging.warning(
            '[rbac_home] index_perm session_username_empty db=%s show_diary_zone=%s can_app_write=%s',
            DATABASE_FILE,
            show_diary,
            can_write,
        )
        return
    role_slugs = []
    user_pk = None
    try:
        conn = get_sqlite_connection()
        c = conn.cursor()
        c.execute(
            'SELECT COALESCE(id, rowid) FROM users WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1',
            (u,),
        )
        row = c.fetchone()
        if not row:
            logging.warning(
                '[rbac_home] index_perm user_row_missing username=%r db=%s owned_sorted=%s did_repair=%s '
                'show_diary_zone=%s can_app_write=%s',
                u,
                DATABASE_FILE,
                sorted(owned_codes),
                did_repair,
                show_diary,
                can_write,
            )
            conn.close()
            return
        user_pk = _safe_int(row[0])
        if user_pk is None:
            _repair_users_null_ids(c)
            conn.commit()
            c.execute(
                'SELECT COALESCE(id, rowid) FROM users WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1',
                (u,),
            )
            row = c.fetchone()
            user_pk = _safe_int(row[0] if row else None)
        if user_pk is None:
            logging.warning('[rbac_home] index_perm user_id_null username=%r db=%s', u, DATABASE_FILE)
            conn.close()
            return
        c.execute(
            '''SELECT r.slug FROM roles r
               INNER JOIN user_roles ur ON ur.role_id = r.id
               WHERE ur.user_id = ?
               ORDER BY r.slug''',
            (user_pk,),
        )
        role_slugs = [x[0] for x in c.fetchall() if x and x[0]]
        conn.close()
    except Exception as e:
        logging.exception('[rbac_home] index_perm role_query_failed username=%r err=%s', u, e)

    logging.info(
        '[rbac_home] index_perm username=%r user_pk=%s db=%s roles=%s perm_count=%s '
        'diary_in_owned=%s app_in_owned=%s show_diary_zone=%s can_app_write=%s did_repair=%s codes=%s',
        u,
        user_pk,
        DATABASE_FILE,
        role_slugs,
        len(owned_codes),
        'diary:content' in owned_codes,
        'app:access' in owned_codes,
        show_diary,
        can_write,
        did_repair,
        sorted(owned_codes),
    )


def _rbac_repair_login_access(username):
    """为已存在用户补全 RBAC 表、角色与 member/超管绑定，解决无 user_roles 或库路径不一致导致的「权限恒为空」。"""
    if not username:
        return
    _auth_log('rbac_repair_begin', username=username, database_file=DATABASE_FILE)
    try:
        _rbac_invalidate_permission_cache(username)
        conn = get_sqlite_connection()
        c = conn.cursor()
        try:
            c.execute('ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1')
        except sqlite3.OperationalError:
            pass
        _init_rbac_tables(c)
        _repair_users_null_ids(c)
        _ensure_core_roles(c)
        _sync_permission_definitions_and_grants(c)
        c.execute(
            'SELECT COALESCE(id, rowid) FROM users WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1',
            ((username or '').strip(),),
        )
        ur = c.fetchone()
        if not ur:
            conn.close()
            _auth_log('rbac_repair_skip_no_user', username=username)
            return
        uid = _safe_int(ur[0])
        if uid is None:
            _repair_users_null_ids(c)
            c.execute(
                'SELECT COALESCE(id, rowid) FROM users WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1',
                ((username or '').strip(),),
            )
            ur = c.fetchone()
            uid = _safe_int(ur[0] if ur else None)
        if uid is None:
            conn.close()
            _auth_log('rbac_repair_skip_null_user_id', username=username)
            return
        c.execute('SELECT id FROM roles WHERE slug=?', ('member',))
        mr = c.fetchone()
        if mr:
            c.execute(
                'INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?,?)',
                (uid, mr[0]),
            )
        _rbac_assign_superuser_admin(c)
        conn.commit()
        conn.close()
        _rbac_invalidate_permission_cache(username)
        snap = _auth_permission_codes_preview(username)
        _auth_log('rbac_repair_ok', username=username, **snap)
    except Exception as e:
        logging.error('_rbac_repair_login_access(%r): %s', username, e, exc_info=True)
        _auth_log('rbac_repair_fail', username=username, error=str(e))


def user_has_permission(username, *codes, require_all=False):
    """若持有 rbac:admin 则视为拥有全部已定义能力；否则按 codes 校验。"""
    if not username:
        return False
    uname = (username or '').strip()
    # 配置的超管：只要库中存在该账号（不区分大小写），一律放行并强制挂上 admin，避免 RBAC 数据异常时把自己锁在登录页外
    if _rbac_is_configured_superuser_login_name(uname):
        uid_row = getattr(g, "_rbac_superuser_uid_row", None) if has_request_context() else None
        if uid_row is None:
            uid_row = query_db(
                'SELECT COALESCE(id, rowid) FROM users WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1',
                (uname,),
                one=True,
            )
            if has_request_context():
                g._rbac_superuser_uid_row = uid_row
        uid = _safe_int(uid_row[0] if uid_row else None)
        if uid is None:
            uid = _rbac_user_id_by_username(uname)
        if uid is not None:
            _rbac_ensure_superuser_admin_for_user_id(uid)
            return True
    owned = _rbac_get_user_permission_codes(uname)
    if not owned:
        skip = has_request_context() and getattr(g, '_rbac_repair_tried', False)
        if not skip:
            if has_request_context():
                g._rbac_repair_tried = True
            _rbac_repair_login_access(username)
            owned = _rbac_get_user_permission_codes(username)
    if 'rbac:admin' in owned:
        return True
    if not codes:
        return _rbac_permission_code_grants(owned, 'app:view') or _rbac_permission_code_grants(owned, 'app:operate')
    if require_all:
        return all(_rbac_permission_code_grants(owned, c) for c in codes)
    return any(_rbac_permission_code_grants(owned, c) for c in codes)


def permission_required(*codes, require_all=False):
    """要求已登录且具备权限（与全局 before_request 策略一致：API/页面均直接返回 403）。"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'username' not in session:
                return _auth_login_required_response()
            uname = session.get('username')
            if not user_has_permission(uname, *codes, require_all=require_all):
                _auth_log(
                    'decorator_permission_denied',
                    username=uname,
                    endpoint=getattr(request, 'endpoint', None),
                    path=getattr(request, 'path', ''),
                    required=list(codes),
                    preview=_auth_permission_codes_preview(uname),
                )
                return _auth_forbidden_response(codes, '没有权限执行此操作')
            return f(*args, **kwargs)
        return wrapped
    return decorator


_rbac_bootstrap_done = False


def _rbac_bootstrap_once():
    """进程内首次请求时同步 RBAC（与 init_db 中 RBAC 段一致），避免未跑 init_db 或旧库缺列时权限恒为空、登录后立刻被踢回登录页。"""
    global _rbac_bootstrap_done
    if _rbac_bootstrap_done:
        return
    _auth_log('rbac_bootstrap_begin', **_app_db_diag())
    try:
        conn = get_sqlite_connection()
        c = conn.cursor()
        try:
            c.execute('ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1')
        except sqlite3.OperationalError:
            pass
        _init_rbac_tables(c)
        _seed_rbac_data(conn, c)
        _backup_sqlite_before_schema_migration(c, "tenant")
        _ensure_tenant_columns_and_indexes(c)
        _ensure_sqlite_performance_indexes(c)
        conn.commit()
        conn.close()
        _rbac_bootstrap_done = True
        _auth_log('rbac_bootstrap_ok', **_app_db_diag())
    except Exception as e:
        logging.exception('RBAC 引导失败（请检查主应用数据库配置 %s）: %s', _app_db_diag(), e)
        _auth_log('rbac_bootstrap_fail', error=str(e), **_app_db_diag())


def _rbac_assign_role_slugs(user_id, conn, c, role_slugs):
    """用角色 slug 列表覆盖该用户的角色（事务外需 commit）。"""
    c.execute('DELETE FROM user_roles WHERE user_id=?', (user_id,))
    for slug in role_slugs or []:
        c.execute('SELECT id FROM roles WHERE slug=?', (slug,))
        r = c.fetchone()
        if r:
            c.execute(
                'INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?,?)',
                (user_id, r[0]),
            )
    _rbac_invalidate_permission_cache()


def _rbac_user_id_by_username(username):
    """返回与 /api/rbac/users 列表中 id 相同的用户主键（COALESCE(id,rowid)）。"""
    uname = (username or '').strip()
    row = query_db(
        'SELECT COALESCE(id, rowid) FROM users WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1',
        (uname,),
        one=True,
    )
    uid = _safe_int(row[0] if row else None)
    if uid is not None:
        return uid
    try:
        conn = get_sqlite_connection()
        c = conn.cursor()
        _repair_users_null_ids(c)
        conn.commit()
        c.execute(
            'SELECT COALESCE(id, rowid) FROM users WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1',
            (uname,),
        )
        row = c.fetchone()
        conn.close()
        return _safe_int(row[0] if row else None)
    except Exception:
        logging.exception('repair user id failed username=%r', username)
        return None


TENANT_OWNED_TABLES = (
    "market_timeline",
    "essays",
    "reviews",
    "investment_calendar",
    "investment_plans",
    "market_tone",
    "index_trend",
    "deep_reports",
    "pdf_reports",
    "pdf_report_business_tabs",
    "topics",
    "topic_cards",
    "card_connections",
    "research_links",
    "concept_stocks",
    "concept_stock_items",
    "data_table_configs",
    "data_field_configs",
    "sql_query_templates",
    "screening_task_executions",
    "screening_task_result_sheets",
    "screening_task_result_rows",
    "portfolio_field_mappings",
    "portfolio_data",
    "daily_morning_briefs",
    "job_runs",
    "daily_reviews",
)


def current_user_id():
    """Current logged-in user's stable users.id / rowid value."""
    if has_request_context() and hasattr(g, "_current_user_id"):
        return g._current_user_id
    username = session.get("username") if has_request_context() else None
    uid = _rbac_user_id_by_username(username) if username else None
    if has_request_context():
        g._current_user_id = uid
    return uid


def current_user_id_required():
    uid = current_user_id()
    if uid is None:
        raise PermissionError("当前用户不存在或未登录")
    return int(uid)


def effective_owner_user_id():
    """Request user when available; otherwise the default owner used for legacy/background writes."""
    if has_request_context():
        return current_user_id_required()
    conn = get_sqlite_connection()
    try:
        return int(_default_owner_user_id_from_cursor(conn.cursor()))
    finally:
        conn.close()


def _sqlite_table_exists(c, table):
    c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table,))
    return c.fetchone() is not None


def _sqlite_table_columns(c, table):
    if not _sqlite_table_exists(c, table):
        return []
    return [row[1] for row in c.execute(f"PRAGMA table_info({table})").fetchall()]


def _sqlite_unique_index_columns(c, table):
    out = []
    if not _sqlite_table_exists(c, table):
        return out
    for row in c.execute(f"PRAGMA index_list({table})").fetchall():
        try:
            is_unique = bool(row[2])
            index_name = row[1]
        except (IndexError, TypeError):
            continue
        if not is_unique or not index_name:
            continue
        cols = [r[2] for r in c.execute(f"PRAGMA index_info({index_name})").fetchall()]
        out.append(cols)
    return out


def _users_table_has_id_column(c):
    try:
        return "id" in _sqlite_table_columns(c, "users")
    except Exception:
        return True


def _next_available_user_id(c):
    values = []
    for sql in (
        "SELECT MAX(id) FROM users",
        "SELECT MAX(user_id) FROM user_roles",
        "SELECT MAX(owner_user_id) FROM essays",
        "SELECT MAX(owner_user_id) FROM reviews",
        "SELECT MAX(owner_user_id) FROM investment_plans",
        "SELECT MAX(owner_user_id) FROM investment_calendar",
        "SELECT MAX(owner_user_id) FROM deep_reports",
        "SELECT MAX(owner_user_id) FROM pdf_reports",
        "SELECT MAX(owner_user_id) FROM topics",
        "SELECT MAX(owner_user_id) FROM portfolio_data",
    ):
        try:
            c.execute(sql)
            values.append(_safe_int((c.fetchone() or [None])[0], 0) or 0)
        except Exception:
            continue
    return max(values or [0]) + 1


def _candidate_user_ids_from_owned_data(c, username):
    uname = (username or "").strip()
    if not uname:
        return []
    like = f"%{uname}%"
    candidates = []
    checks = (
        ("essays", "content"),
        ("reviews", "major_events"),
        ("deep_reports", "title"),
        ("investment_plans", "created_by"),
        ("screening_task_executions", "created_by"),
    )
    for table, col in checks:
        if not _sqlite_table_exists(c, table):
            continue
        cols = set(_sqlite_table_columns(c, table))
        if "owner_user_id" not in cols or col not in cols:
            continue
        try:
            c.execute(
                f"""SELECT owner_user_id, COUNT(*) FROM {table}
                    WHERE owner_user_id IS NOT NULL AND COALESCE({col}, '') LIKE ?
                    GROUP BY owner_user_id
                    ORDER BY COUNT(*) DESC""",
                (like,),
            )
            candidates.extend((_safe_int(row[0]), int(row[1] or 0)) for row in c.fetchall())
        except Exception:
            continue
    seen = set()
    out = []
    for uid, score in sorted(candidates, key=lambda x: (-x[1], x[0] or 0)):
        if uid is None or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


def _repair_users_null_ids(c):
    """MySQL has no SQLite rowid. Fill legacy users.id=NULL rows with stable ids."""
    if not _sqlite_table_exists(c, "users") or not _users_table_has_id_column(c):
        return 0
    c.execute("SELECT id, username FROM users WHERE id IS NULL ORDER BY username")
    rows = c.fetchall()
    repaired = 0
    used = set()
    try:
        c.execute("SELECT id FROM users WHERE id IS NOT NULL")
        used.update(_safe_int(row[0]) for row in c.fetchall())
    except Exception:
        pass
    used.discard(None)

    for _old_id, username in rows:
        target_id = None
        for candidate in _candidate_user_ids_from_owned_data(c, username):
            if candidate not in used:
                target_id = candidate
                break
        if target_id is None:
            target_id = _next_available_user_id(c)
            while target_id in used:
                target_id += 1
        c.execute(
            "UPDATE users SET id=? WHERE id IS NULL AND lower(trim(username)) = lower(trim(?))",
            (target_id, (username or "").strip()),
        )
        if c.rowcount:
            used.add(target_id)
            repaired += int(c.rowcount or 0)
    if repaired:
        logging.info("RBAC user id repair filled %s legacy users.id values", repaired)
    return repaired


def _sqlite_needs_tenant_schema_migration(c):
    for table in TENANT_OWNED_TABLES:
        if _sqlite_table_exists(c, table) and "owner_user_id" not in _sqlite_table_columns(c, table):
            return True
    if _sqlite_table_exists(c, "concept_stocks"):
        concept_uniques = _sqlite_unique_index_columns(c, "concept_stocks")
        if ["concept_name"] in concept_uniques or ["owner_user_id", "concept_name"] not in concept_uniques:
            return True
    for table, unique_cols in (
        ("reviews", ["owner_user_id", "date"]),
        ("market_tone", ["owner_user_id", "date"]),
        ("index_trend", ["owner_user_id", "date"]),
        ("research_links", ["owner_user_id", "source_type", "source_id", "target_type", "target_id", "relation_type"]),
        ("portfolio_field_mappings", ["owner_user_id", "mapping_name"]),
        ("portfolio_data", ["owner_user_id", "portfolio_name", "date", "stock_code"]),
    ):
        if _sqlite_table_exists(c, table) and unique_cols not in _sqlite_unique_index_columns(c, table):
            return True
    return False


def _backup_sqlite_before_schema_migration(c, reason):
    if not _env_bool("APP_SQLITE_MIGRATION_BACKUP", True):
        return
    global _sqlite_migration_backup_done
    if _sqlite_migration_backup_done or not os.path.exists(DATABASE_FILE):
        return
    if not _sqlite_needs_tenant_schema_migration(c):
        _sqlite_migration_backup_done = True
        return
    try:
        backup_dir = os.path.join(_APP_ROOT, "back", "db_backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"database_before_{reason}_{stamp}.db")
        shutil.copy2(DATABASE_FILE, backup_file)
        _sqlite_migration_backup_done = True
        logging.info("SQLite schema migration backup created: %s", backup_file)
    except Exception as e:
        logging.warning("SQLite schema migration backup failed: %s", e, exc_info=True)


def _default_owner_user_id_from_cursor(c):
    c.execute(
        "SELECT COALESCE(id, rowid) FROM users "
        "WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1",
        ((RBAC_SUPERUSER_USERNAME or "").strip(),),
    )
    row = c.fetchone()
    uid = _safe_int(row[0] if row else None)
    if uid is not None:
        return uid
    _repair_users_null_ids(c)
    c.execute(
        "SELECT COALESCE(id, rowid) FROM users "
        "WHERE lower(trim(username)) = lower(trim(?)) LIMIT 1",
        ((RBAC_SUPERUSER_USERNAME or "").strip(),),
    )
    row = c.fetchone()
    uid = _safe_int(row[0] if row else None)
    if uid is not None:
        return uid
    c.execute("SELECT COALESCE(id, rowid) FROM users ORDER BY COALESCE(id, rowid) LIMIT 1")
    row = c.fetchone()
    uid = _safe_int(row[0] if row else None)
    if uid is not None:
        return uid
    return 1


def _ensure_owner_column(c, table, default_owner_id):
    if not _sqlite_table_exists(c, table):
        return
    cols = _sqlite_table_columns(c, table)
    if "owner_user_id" not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN owner_user_id INTEGER")
    c.execute(
        f"UPDATE {table} SET owner_user_id=? WHERE owner_user_id IS NULL",
        (default_owner_id,),
    )


def _rebuild_owned_unique_table(c, table, schema_sql, copy_columns, unique_cols):
    if not _sqlite_table_exists(c, table):
        return
    uniques = _sqlite_unique_index_columns(c, table)
    if list(unique_cols) in uniques and ["date"] not in uniques:
        return

    default_owner_id = _default_owner_user_id_from_cursor(c)
    old_cols = set(_sqlite_table_columns(c, table))
    tmp = f"__{table}_tenant_migrate"
    c.execute(f"DROP TABLE IF EXISTS {tmp}")
    c.execute(schema_sql.format(table=tmp))

    insert_cols = []
    select_exprs = []
    params = []
    for col in copy_columns:
        insert_cols.append(col)
        if col == "owner_user_id":
            if col in old_cols:
                select_exprs.append("COALESCE(owner_user_id, ?)")
            else:
                select_exprs.append("?")
            params.append(default_owner_id)
        elif col in old_cols:
            select_exprs.append(col)
        else:
            select_exprs.append("NULL")
    c.execute(
        f"INSERT OR IGNORE INTO {tmp} ({', '.join(insert_cols)}) "
        f"SELECT {', '.join(select_exprs)} FROM {table}",
        tuple(params),
    )
    c.execute(f"DROP TABLE {table}")
    c.execute(f"ALTER TABLE {tmp} RENAME TO {table}")


def _rebuild_concept_stocks_tenant_unique(c):
    if not _sqlite_table_exists(c, "concept_stocks"):
        return
    uniques = _sqlite_unique_index_columns(c, "concept_stocks")
    if ["owner_user_id", "concept_name"] in uniques and ["concept_name"] not in uniques:
        return

    default_owner_id = _default_owner_user_id_from_cursor(c)
    old_cols = set(_sqlite_table_columns(c, "concept_stocks"))
    tmp = "__concept_stocks_tenant_migrate"
    child_backup = "__concept_stock_items_backup"
    child_exists = _sqlite_table_exists(c, "concept_stock_items")
    child_cols = _sqlite_table_columns(c, "concept_stock_items") if child_exists else []
    if child_exists and child_cols:
        c.execute(f"DROP TABLE IF EXISTS {child_backup}")
        c.execute(f"CREATE TEMP TABLE {child_backup} AS SELECT * FROM concept_stock_items")

    c.execute(f"DROP TABLE IF EXISTS {tmp}")
    c.execute(
        f"""CREATE TABLE {tmp}
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             concept_name TEXT NOT NULL,
             description TEXT,
             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
             updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
             owner_user_id INTEGER NOT NULL,
             UNIQUE(owner_user_id, concept_name))"""
    )
    copy_columns = ("id", "concept_name", "description", "created_at", "updated_at", "owner_user_id")
    insert_cols = []
    select_exprs = []
    params = []
    for col in copy_columns:
        insert_cols.append(col)
        if col == "owner_user_id":
            if col in old_cols:
                select_exprs.append("COALESCE(owner_user_id, ?)")
            else:
                select_exprs.append("?")
            params.append(default_owner_id)
        elif col in old_cols:
            select_exprs.append(col)
        else:
            select_exprs.append("NULL")
    c.execute(
        f"INSERT OR IGNORE INTO {tmp} ({', '.join(insert_cols)}) "
        f"SELECT {', '.join(select_exprs)} FROM concept_stocks",
        tuple(params),
    )
    c.execute("DROP TABLE concept_stocks")
    c.execute(f"ALTER TABLE {tmp} RENAME TO concept_stocks")

    if child_exists and child_cols:
        cols_sql = ", ".join(child_cols)
        c.execute(f"INSERT OR IGNORE INTO concept_stock_items ({cols_sql}) SELECT {cols_sql} FROM {child_backup}")
        c.execute(f"DROP TABLE IF EXISTS {child_backup}")


def _ensure_tenant_columns_and_indexes(c):
    """Tag user-owned app data and index the common tenant-scoped access paths."""
    default_owner_id = _default_owner_user_id_from_cursor(c)

    _rebuild_owned_unique_table(
        c,
        "reviews",
        """CREATE TABLE {table}
           (id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            market_emotion TEXT,
            sectors TEXT,
            themes TEXT,
            market_cap_performance TEXT,
            investment_style TEXT,
            major_events TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL,
            UNIQUE(owner_user_id, date))""",
        (
            "id",
            "date",
            "market_emotion",
            "sectors",
            "themes",
            "market_cap_performance",
            "investment_style",
            "major_events",
            "created_at",
            "updated_at",
            "owner_user_id",
        ),
        ("owner_user_id", "date"),
    )
    _rebuild_owned_unique_table(
        c,
        "market_tone",
        """CREATE TABLE {table}
           (id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            volume_status TEXT,
            emotion_status TEXT,
            divergence_status TEXT,
            investment_strategies TEXT,
            investment_styles TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL,
            UNIQUE(owner_user_id, date))""",
        (
            "id",
            "date",
            "volume_status",
            "emotion_status",
            "divergence_status",
            "investment_strategies",
            "investment_styles",
            "created_at",
            "updated_at",
            "owner_user_id",
        ),
        ("owner_user_id", "date"),
    )
    _rebuild_owned_unique_table(
        c,
        "index_trend",
        """CREATE TABLE {table}
           (id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            shanghai_trend TEXT,
            shenzhen_trend TEXT,
            chinext_trend TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL,
            UNIQUE(owner_user_id, date))""",
        (
            "id",
            "date",
            "shanghai_trend",
            "shenzhen_trend",
            "chinext_trend",
            "created_at",
            "updated_at",
            "owner_user_id",
        ),
        ("owner_user_id", "date"),
    )
    _rebuild_owned_unique_table(
        c,
        "research_links",
        """CREATE TABLE {table}
           (id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT DEFAULT 'related',
            confidence REAL DEFAULT 1.0,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL,
            UNIQUE(owner_user_id, source_type, source_id, target_type, target_id, relation_type))""",
        (
            "id",
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            "confidence",
            "note",
            "created_at",
            "updated_at",
            "owner_user_id",
        ),
        ("owner_user_id", "source_type", "source_id", "target_type", "target_id", "relation_type"),
    )
    _rebuild_owned_unique_table(
        c,
        "portfolio_field_mappings",
        """CREATE TABLE {table}
           (id INTEGER PRIMARY KEY AUTOINCREMENT,
            mapping_name TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            mapping_config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL,
            UNIQUE(owner_user_id, mapping_name))""",
        (
            "id",
            "mapping_name",
            "is_default",
            "mapping_config",
            "created_at",
            "updated_at",
            "owner_user_id",
        ),
        ("owner_user_id", "mapping_name"),
    )
    _rebuild_owned_unique_table(
        c,
        "portfolio_data",
        """CREATE TABLE {table}
           (id INTEGER PRIMARY KEY AUTOINCREMENT,
            portfolio_name TEXT NOT NULL,
            date TEXT NOT NULL,
            stock_code TEXT NOT NULL,
            stock_name TEXT,
            stock_market TEXT,
            position_quantity REAL,
            position_value REAL,
            buy_quantity REAL DEFAULT 0,
            sell_quantity REAL DEFAULT 0,
            avg_price REAL,
            first_industry_name TEXT,
            second_industry_name TEXT,
            third_industry_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL,
            UNIQUE(owner_user_id, portfolio_name, date, stock_code))""",
        (
            "id",
            "portfolio_name",
            "date",
            "stock_code",
            "stock_name",
            "stock_market",
            "position_quantity",
            "position_value",
            "buy_quantity",
            "sell_quantity",
            "avg_price",
            "first_industry_name",
            "second_industry_name",
            "third_industry_name",
            "created_at",
            "owner_user_id",
        ),
        ("owner_user_id", "portfolio_name", "date", "stock_code"),
    )
    _rebuild_concept_stocks_tenant_unique(c)

    for table in TENANT_OWNED_TABLES:
        _ensure_owner_column(c, table, default_owner_id)

    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_market_timeline_owner_date ON market_timeline(owner_user_id, date DESC, time DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_essays_owner_date_created ON essays(owner_user_id, date DESC, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_reviews_owner_date_desc ON reviews(owner_user_id, date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_investment_plans_owner_status ON investment_plans(owner_user_id, status, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_investment_plans_owner_target ON investment_plans(owner_user_id, target_date)",
        "CREATE INDEX IF NOT EXISTS idx_investment_calendar_owner_start ON investment_calendar(owner_user_id, start_date)",
        "CREATE INDEX IF NOT EXISTS idx_investment_calendar_owner_related_plan ON investment_calendar(owner_user_id, related_plan_id)",
        "CREATE INDEX IF NOT EXISTS idx_market_tone_owner_date ON market_tone(owner_user_id, date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_index_trend_owner_date ON index_trend(owner_user_id, date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_deep_reports_owner_date ON deep_reports(owner_user_id, date DESC, updated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pdf_reports_owner_upload ON pdf_reports(owner_user_id, upload_time DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_pdf_reports_owner_business_tab_upload ON pdf_reports(owner_user_id, business_tab_id, upload_time DESC, id DESC)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_pdf_report_business_tabs_owner_category_name ON pdf_report_business_tabs(owner_user_id, category, name)",
        "CREATE INDEX IF NOT EXISTS idx_pdf_report_business_tabs_owner_category ON pdf_report_business_tabs(owner_user_id, category, sort_order, name)",
        "CREATE INDEX IF NOT EXISTS idx_topics_owner_created ON topics(owner_user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_topic_cards_owner_topic ON topic_cards(owner_user_id, topic_id)",
        "CREATE INDEX IF NOT EXISTS idx_card_connections_owner_topic ON card_connections(owner_user_id, topic_id)",
        "CREATE INDEX IF NOT EXISTS idx_research_links_owner_source ON research_links(owner_user_id, source_type, source_id)",
        "CREATE INDEX IF NOT EXISTS idx_research_links_owner_target ON research_links(owner_user_id, target_type, target_id)",
        "CREATE INDEX IF NOT EXISTS idx_concept_stocks_owner_name ON concept_stocks(owner_user_id, concept_name)",
        "CREATE INDEX IF NOT EXISTS idx_concept_stock_items_owner_concept ON concept_stock_items(owner_user_id, concept_id)",
        "CREATE INDEX IF NOT EXISTS idx_data_table_configs_owner_name ON data_table_configs(owner_user_id, table_name)",
        "CREATE INDEX IF NOT EXISTS idx_data_field_configs_owner_table ON data_field_configs(owner_user_id, table_config_id)",
        "CREATE INDEX IF NOT EXISTS idx_sql_query_templates_owner_name ON sql_query_templates(owner_user_id, template_name)",
        "CREATE INDEX IF NOT EXISTS idx_screening_executions_owner_created ON screening_task_executions(owner_user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_screening_result_sheets_exec ON screening_task_result_sheets(execution_id, sheet_index)",
        "CREATE INDEX IF NOT EXISTS idx_screening_result_rows_exec_sheet ON screening_task_result_rows(execution_id, sheet_name, row_index)",
        "CREATE INDEX IF NOT EXISTS idx_screening_result_rows_owner_exec ON screening_task_result_rows(owner_user_id, execution_id)",
        "CREATE INDEX IF NOT EXISTS idx_portfolio_mappings_owner_default ON portfolio_field_mappings(owner_user_id, is_default, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_portfolio_data_owner_name_date ON portfolio_data(owner_user_id, portfolio_name, date)",
        "CREATE INDEX IF NOT EXISTS idx_portfolio_data_owner_stock_name_date ON portfolio_data(owner_user_id, stock_name, date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_dmb_owner_date ON daily_morning_briefs(owner_user_id, report_date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_dmb_public_date ON daily_morning_briefs(report_date DESC, source_name, status)",
        "CREATE INDEX IF NOT EXISTS idx_dmb_generated_at ON daily_morning_briefs(generated_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_job_runs_owner_job_date ON job_runs(owner_user_id, job_name, target_date)",
    ):
        try:
            c.execute(stmt)
        except sqlite3.OperationalError as e:
            logging.debug("tenant index skipped %s: %s", stmt, e)


# 初始化数据库
def init_db():
    try:
        conn = get_sqlite_connection()
        c = conn.cursor()
        ensure_juyuan_bridge_tables_with_cursor(c)
        
        # 用户表
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     username TEXT NOT NULL UNIQUE,
                     password TEXT NOT NULL)''')

        # 爬虫标题词云 · 用户自定义黑名单（点击词云加入，仅当前登录用户）
        c.execute('''CREATE TABLE IF NOT EXISTS crawler_wordcloud_blacklist (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     username TEXT NOT NULL,
                     word TEXT NOT NULL,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     UNIQUE(username, word))''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_cwb_username ON crawler_wordcloud_blacklist(username)')

        # 盘中异动 / 历史复盘时间轴（SQLite，与爬虫看板联动）
        c.execute('''CREATE TABLE IF NOT EXISTS market_timeline (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     date TEXT NOT NULL,
                     time TEXT NOT NULL,
                     title TEXT NOT NULL,
                     url TEXT,
                     remark TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_market_timeline_date ON market_timeline(date)')

        try:
            c.execute('ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1')
        except sqlite3.OperationalError:
            pass

        _init_rbac_tables(c)
        
        # 随笔表 - 一天可以有多个随笔卡片
        c.execute('''CREATE TABLE IF NOT EXISTS essays
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     date TEXT NOT NULL,
                     content TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # 复盘表 - 固定模式的复盘，一天一条
        c.execute('''CREATE TABLE IF NOT EXISTS reviews
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     date TEXT NOT NULL UNIQUE,
                     market_emotion TEXT,
                     sectors TEXT,
                     themes TEXT,
                     market_cap_performance TEXT,
                     investment_style TEXT,
                     major_events TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # 投资日历表 - 支持单日、多日、周期事件
        c.execute('''CREATE TABLE IF NOT EXISTS investment_calendar
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     title TEXT NOT NULL,
                     content TEXT,
                     start_date TEXT NOT NULL,
                     end_date TEXT,
                     reminder_type TEXT DEFAULT 'notification',
                     reminder_time INTEGER DEFAULT 0,
                     reminder_sent INTEGER DEFAULT 0,
                     color TEXT DEFAULT '#6366f1',
                     event_type TEXT DEFAULT 'single',
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # 投资日历：投研分类、关联股票、关联交易计划
        for _mig in (
            "ALTER TABLE investment_calendar ADD COLUMN event_category TEXT DEFAULT 'other'",
            "ALTER TABLE investment_calendar ADD COLUMN related_stock TEXT",
            "ALTER TABLE investment_calendar ADD COLUMN related_plan_id INTEGER",
        ):
            try:
                c.execute(_mig)
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    logging.debug("投资日历表迁移: %s", e)
        
        # 投资计划表 - 参考Notion/Linear的设计
        c.execute('''CREATE TABLE IF NOT EXISTS investment_plans
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     title TEXT NOT NULL,
                     description TEXT,
                     status TEXT DEFAULT 'todo',
                     priority TEXT DEFAULT 'medium',
                     category TEXT,
                     tags TEXT,
                     target_date TEXT,
                     progress INTEGER DEFAULT 0,
                     color TEXT DEFAULT '#f59e0b',
                     is_profitable INTEGER,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # 检查并添加 is_profitable 字段（如果不存在）
        try:
            c.execute("ALTER TABLE investment_plans ADD COLUMN is_profitable INTEGER")
            conn.commit()
            # 数据库迁移操作，只在首次执行时记录
            logging.info("数据库迁移: 已添加 is_profitable 字段")
        except sqlite3.OperationalError:
            # 字段已存在，忽略错误
            pass
        # 投研计划：资讯追踪关键词（逗号分隔，软关联爬虫）
        try:
            c.execute("ALTER TABLE investment_plans ADD COLUMN keywords TEXT")
            conn.commit()
            logging.info("数据库迁移: 已添加 investment_plans.keywords 字段")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE investment_plans ADD COLUMN instruments TEXT")
            conn.commit()
            logging.info("数据库迁移: 已添加 investment_plans.instruments 字段")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE investment_plans ADD COLUMN tracking_items TEXT")
            conn.commit()
            logging.info("数据库迁移: 已添加 investment_plans.tracking_items 字段")
        except sqlite3.OperationalError:
            pass
        
        # 市场基调表 - 每日市场基调设置
        c.execute('''CREATE TABLE IF NOT EXISTS market_tone
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     date TEXT NOT NULL UNIQUE,
                     volume_status TEXT,
                     emotion_status TEXT,
                     divergence_status TEXT,
                     investment_strategies TEXT,
                     investment_styles TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # 指数走势表 - 每日三大指数走势
        c.execute('''CREATE TABLE IF NOT EXISTS index_trend
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     date TEXT NOT NULL UNIQUE,
                     shanghai_trend TEXT,
                     shenzhen_trend TEXT,
                     chinext_trend TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

        # 每日市场情绪结果表（保存最近计算结果，页面可直接展示）
        c.execute('''CREATE TABLE IF NOT EXISTS market_sentiment_results
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     trading_day TEXT NOT NULL UNIQUE,
                     result_json TEXT NOT NULL,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        try:
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_msr_trading_day ON market_sentiment_results(trading_day)')
        except Exception:
            try:
                c.execute('CREATE INDEX IF NOT EXISTS idx_msr_trading_day_lookup ON market_sentiment_results(trading_day)')
            except Exception:
                pass

        # 算法版本追踪：只记录版本，不清空历史缓存。
        # 情绪缓存是投研历史数据，算法升级后的重算应由显式批处理完成。
        c.execute('''CREATE TABLE IF NOT EXISTS sentiment_meta
                     (key TEXT PRIMARY KEY, value TEXT)''')
        from market_sentiment import SENTIMENT_VERSION as _SV
        row = c.execute("SELECT value FROM sentiment_meta WHERE key='version'").fetchone()
        if row is None or row[0] != _SV:
            c.execute("INSERT OR REPLACE INTO sentiment_meta (key, value) VALUES ('version', ?)", (_SV,))
            app_logger.info(f"情绪算法版本更新为 {_SV}，已保留历史缓存")
        
        # 深度报告和总结表
        c.execute('''CREATE TABLE IF NOT EXISTS deep_reports
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     title TEXT NOT NULL,
                     content TEXT,
                     summary TEXT,
                     category TEXT,
                     tags TEXT,
                     related_plan_id INTEGER,
                     date TEXT,
                     sheet_types TEXT,
                     stock_codes TEXT,
                     concept_ids TEXT,
                     industry_names TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        for _idx in (
            "CREATE INDEX IF NOT EXISTS idx_deep_reports_date ON deep_reports(date)",
            "CREATE INDEX IF NOT EXISTS idx_deep_reports_plan ON deep_reports(related_plan_id)",
        ):
            try:
                c.execute(_idx)
            except sqlite3.OperationalError:
                pass
        
        # 检查并添加新字段（向后兼容）
        try:
            c.execute("ALTER TABLE deep_reports ADD COLUMN sheet_types TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        
        try:
            c.execute("ALTER TABLE deep_reports ADD COLUMN stock_codes TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        
        try:
            c.execute("ALTER TABLE deep_reports ADD COLUMN concept_ids TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        
        try:
            c.execute("ALTER TABLE deep_reports ADD COLUMN industry_names TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        c.execute('''CREATE TABLE IF NOT EXISTS pdf_reports
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     title TEXT NOT NULL,
                     original_filename TEXT NOT NULL,
                     original_filepath TEXT,
                     pdf_filename TEXT NOT NULL,
                      pdf_filepath TEXT NOT NULL,
                      source_format TEXT,
                      category TEXT DEFAULT 'report_other',
                      annotation_json TEXT DEFAULT '{}',
                     summary_text TEXT,
                     linked_entity_type TEXT,
                     linked_entity_id INTEGER,
                     upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_pdf_reports_upload_time ON pdf_reports(upload_time)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_pdf_reports_linked_entity ON pdf_reports(linked_entity_type, linked_entity_id)')
        try:
            c.execute("ALTER TABLE pdf_reports ADD COLUMN category TEXT DEFAULT 'report_other'")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE pdf_reports ADD COLUMN business_tab_id INTEGER")
        except sqlite3.OperationalError:
            pass
        c.execute("UPDATE pdf_reports SET category='report' WHERE category IS NULL OR category=''")
        c.execute('CREATE INDEX IF NOT EXISTS idx_pdf_reports_category ON pdf_reports(category)')
        c.execute('''CREATE TABLE IF NOT EXISTS pdf_report_business_tabs
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     owner_user_id INTEGER NOT NULL,
                     category TEXT NOT NULL DEFAULT 'report_other',
                     name TEXT NOT NULL,
                     description TEXT,
                     sort_order INTEGER DEFAULT 0,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     UNIQUE(owner_user_id, category, name))''')
        
        # 脑图表
        c.execute('''CREATE TABLE IF NOT EXISTS topics
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     title TEXT NOT NULL,
                     description TEXT,
                     settings_json TEXT DEFAULT '{}',
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        try:
            c.execute("ALTER TABLE topics ADD COLUMN settings_json TEXT DEFAULT '{}'")
        except sqlite3.OperationalError:
            pass
        
        # 脑图卡片表
        c.execute('''CREATE TABLE IF NOT EXISTS topic_cards
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     topic_id INTEGER NOT NULL,
                     title TEXT NOT NULL,
                     content TEXT,
                     card_type TEXT DEFAULT 'company',
                     x INTEGER DEFAULT 100,
                     y INTEGER DEFAULT 100,
                     width INTEGER DEFAULT 220,
                     height INTEGER DEFAULT 160,
                     color TEXT DEFAULT '#6366f1',
                     metadata_json TEXT DEFAULT '{}',
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE)''')
        
        # 检查并添加card_type字段
        try:
            c.execute("ALTER TABLE topic_cards ADD COLUMN card_type TEXT DEFAULT 'company'")
            conn.commit()
            logging.info("数据库迁移: 已添加 card_type 字段")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE topic_cards ADD COLUMN metadata_json TEXT DEFAULT '{}'")
            conn.commit()
            logging.info("数据库迁移: 已添加 topic_cards.metadata_json 字段")
        except sqlite3.OperationalError:
            pass
        
        # 卡片关系表（连线）- 行业关系
        c.execute('''CREATE TABLE IF NOT EXISTS card_connections
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     topic_id INTEGER NOT NULL,
                     from_card_id INTEGER NOT NULL,
                     to_card_id INTEGER NOT NULL,
                     relation_type TEXT DEFAULT 'downstream',
                     connection_type TEXT DEFAULT 'bezier',
                     color TEXT DEFAULT '#999999',
                     label TEXT,
                     note TEXT,
                     metadata_json TEXT DEFAULT '{}',
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP,
                     FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE,
                     FOREIGN KEY (from_card_id) REFERENCES topic_cards(id) ON DELETE CASCADE,
                     FOREIGN KEY (to_card_id) REFERENCES topic_cards(id) ON DELETE CASCADE)''')
        
        # 检查并添加relation_type字段
        try:
            c.execute("ALTER TABLE card_connections ADD COLUMN relation_type TEXT DEFAULT 'downstream'")
            conn.commit()
            logging.info("数据库迁移: 已添加 relation_type 字段")
        except sqlite3.OperationalError:
            pass
        for stmt, log_message in (
            ("ALTER TABLE card_connections ADD COLUMN label TEXT", "数据库迁移: 已添加 card_connections.label 字段"),
            ("ALTER TABLE card_connections ADD COLUMN note TEXT", "数据库迁移: 已添加 card_connections.note 字段"),
            ("ALTER TABLE card_connections ADD COLUMN metadata_json TEXT DEFAULT '{}'", "数据库迁移: 已添加 card_connections.metadata_json 字段"),
            ("ALTER TABLE card_connections ADD COLUMN updated_at TIMESTAMP", "数据库迁移: 已添加 card_connections.updated_at 字段"),
        ):
            try:
                c.execute(stmt)
                conn.commit()
                logging.info(log_message)
            except sqlite3.OperationalError:
                pass

        # 统一投研联动表：不改动既有业务表，用增量关系承接计划/报告/事件/标的之间的连接。
        c.execute('''CREATE TABLE IF NOT EXISTS research_links
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     source_type TEXT NOT NULL,
                     source_id INTEGER NOT NULL,
                     target_type TEXT NOT NULL,
                     target_id TEXT NOT NULL,
                     relation_type TEXT DEFAULT 'related',
                     confidence REAL DEFAULT 1.0,
                     note TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     UNIQUE(source_type, source_id, target_type, target_id, relation_type))''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_research_links_source ON research_links(source_type, source_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_research_links_target ON research_links(target_type, target_id)')
        
        # 数据表配置表
        c.execute('''CREATE TABLE IF NOT EXISTS data_table_configs
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     table_name TEXT NOT NULL UNIQUE,
                     table_display_name TEXT NOT NULL,
                     description TEXT,
                     primary_key_field TEXT,
                     date_field TEXT,
                     code_field TEXT,
                     name_field TEXT,
                     join_type TEXT DEFAULT 'CompanyCode',
                     join_field TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # 检查并添加join_type和join_field字段（向后兼容）
        try:
            c.execute("ALTER TABLE data_table_configs ADD COLUMN join_type TEXT DEFAULT 'CompanyCode'")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        
        try:
            c.execute("ALTER TABLE data_table_configs ADD COLUMN join_field TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass
        
        # 概念股表
        c.execute('''CREATE TABLE IF NOT EXISTS concept_stocks
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     concept_name TEXT NOT NULL,
                     description TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     owner_user_id INTEGER,
                     UNIQUE(owner_user_id, concept_name))''')
        
        # 概念股股票关联表
        c.execute('''CREATE TABLE IF NOT EXISTS concept_stock_items
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     concept_id INTEGER NOT NULL,
                     stock_code TEXT NOT NULL,
                     stock_name TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     owner_user_id INTEGER,
                     FOREIGN KEY (concept_id) REFERENCES concept_stocks(id) ON DELETE CASCADE,
                     UNIQUE(concept_id, stock_code))''')
        
        # 字段配置表
        c.execute('''CREATE TABLE IF NOT EXISTS data_field_configs
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     table_config_id INTEGER NOT NULL,
                     field_name TEXT NOT NULL,
                     field_display_name TEXT NOT NULL,
                     field_type TEXT DEFAULT 'TEXT',
                     description TEXT,
                     is_sortable INTEGER DEFAULT 1,
                     is_filterable INTEGER DEFAULT 1,
                     order_index INTEGER DEFAULT 0,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     FOREIGN KEY (table_config_id) REFERENCES data_table_configs(id) ON DELETE CASCADE,
                     UNIQUE(table_config_id, field_name))''')
        
        # SQL查询模板表
        c.execute('''CREATE TABLE IF NOT EXISTS sql_query_templates
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     template_name TEXT NOT NULL,
                     sql_template TEXT NOT NULL,
                     description TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # 筛选任务执行历史表
        c.execute('''CREATE TABLE IF NOT EXISTS screening_task_executions
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     task_type TEXT NOT NULL,
                     task_name TEXT NOT NULL,
                     status TEXT NOT NULL DEFAULT 'pending',
                     output_file_path TEXT,
                     execution_params TEXT,
                     start_time TIMESTAMP,
                     end_time TIMESTAMP,
                     duration_seconds INTEGER,
                     error_message TEXT,
                     result_summary TEXT,
                     owner_user_id INTEGER,
                     created_by TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

        c.execute('''CREATE TABLE IF NOT EXISTS screening_task_result_sheets
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     execution_id INTEGER NOT NULL,
                     owner_user_id INTEGER,
                     task_type TEXT,
                     sheet_name TEXT NOT NULL,
                     sheet_index INTEGER NOT NULL DEFAULT 0,
                     row_count INTEGER NOT NULL DEFAULT 0,
                     columns_json TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     UNIQUE(execution_id, sheet_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS screening_task_result_rows
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     execution_id INTEGER NOT NULL,
                     sheet_name TEXT NOT NULL,
                     row_index INTEGER NOT NULL,
                     row_json TEXT NOT NULL,
                     owner_user_id INTEGER,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     UNIQUE(execution_id, sheet_name, row_index))''')
        
        # 动量评分结果表
        # 模拟仓字段映射配置表
        c.execute('''CREATE TABLE IF NOT EXISTS portfolio_field_mappings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     mapping_name TEXT NOT NULL UNIQUE,
                     is_default INTEGER DEFAULT 0,
                     mapping_config TEXT NOT NULL,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # 模拟仓数据表
        c.execute('''CREATE TABLE IF NOT EXISTS portfolio_data
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     portfolio_name TEXT NOT NULL,
                     date TEXT NOT NULL,
                     stock_code TEXT NOT NULL,
                     stock_name TEXT,
                     stock_market TEXT,
                     position_quantity REAL,
                     position_value REAL,
                     buy_quantity REAL DEFAULT 0,
                     sell_quantity REAL DEFAULT 0,
                     avg_price REAL,
                     first_industry_name TEXT,
                     second_industry_name TEXT,
                     third_industry_name TEXT,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     UNIQUE(portfolio_name, date, stock_code))''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS momentum_scores
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      date TEXT NOT NULL,
                      code TEXT NOT NULL,
                      momentum_score REAL NOT NULL,
                      factors_json TEXT,
                      status TEXT,
                      status_start_date TEXT,
                      amplitude REAL,
                      lowest_price REAL,
                      highest_price REAL,
                      amount_std REAL,
                      duration_days INTEGER,
                      trend_return REAL,
                      has_volume_surge INTEGER,
                      five_day_acceleration INTEGER,
                      underlying_data_json TEXT,
                      -- 动量指标字段（核心指标）
                      return_1d REAL, return_5d REAL, return_10d REAL, return_20d REAL,
                      return_60d REAL, return_120d REAL, return_250d REAL,
                      amplitude_5d REAL, amplitude_20d REAL, amplitude_60d REAL,
                      daily_volatility REAL, annualized_volatility REAL,
                      max_gain_20d REAL, max_gain_60d REAL,
                      max_drawdown_20d REAL, max_drawdown_60d REAL,
                      recent_high REAL, recent_low REAL, price_vs_high REAL,
                      ma5_slope REAL, ma10_slope REAL, ma20_slope REAL,
                      price_vs_ma5 REAL, price_vs_ma20 REAL, ma5_vs_ma20 REAL,
                      trend_strength REAL,
                      volume_ratio_5d REAL, volume_ratio_20d REAL,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      UNIQUE(date, code))''')

        c.execute('''CREATE TABLE IF NOT EXISTS stock_holding_costs
                     (source TEXT NOT NULL DEFAULT 'juyuan_close',
                      symbol TEXT NOT NULL,
                      stock_name TEXT,
                      start_date TEXT NOT NULL,
                      end_date TEXT NOT NULL,
                      latest_trade_date TEXT,
                      n_days INTEGER NOT NULL DEFAULT 0,
                      latest_close REAL,
                      avg_holding_cost REAL,
                      period_vwap_cost REAL,
                      price_vs_avg_cost REAL,
                      total_volume REAL,
                      remaining_volume_proxy REAL,
                      remaining_value_proxy REAL,
                      turnover_sum REAL,
                      turnover_compound REAL,
                      calc_version TEXT NOT NULL DEFAULT 'juyuan_close_v1',
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (source, symbol, start_date, end_date))''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_stock_holding_costs_end_symbol ON stock_holding_costs(end_date, symbol)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_stock_holding_costs_start_end ON stock_holding_costs(start_date, end_date)')

        c.execute('''CREATE TABLE IF NOT EXISTS stock_character_profiles
                     (trade_date TEXT NOT NULL,
                      stock_code TEXT NOT NULL,
                      stock_name TEXT,
                      sample_start_date TEXT,
                      sample_end_date TEXT,
                      lookback_days INTEGER,
                      sample_count INTEGER,
                      momentum_score REAL,
                      next_day_return REAL,
                      close_price REAL,
                      avg_holding_cost REAL,
                      period_vwap_cost REAL,
                      price_vs_avg_cost REAL,
                      continuous_volume_index REAL,
                      character_score REAL,
                      character_label TEXT,
                      confidence_level TEXT,
                      risk_level TEXT,
                      character_summary TEXT,
                      action_hint TEXT,
                      momentum_return_corr REAL,
                      momentum_bucket TEXT,
                      bucket_sample_count INTEGER,
                      bucket_next_day_avg_return REAL,
                      bucket_next_day_win_rate REAL,
                      bucket_next_day_median_return REAL,
                      bucket_next_day_p75_return REAL,
                      bucket_next_day_p25_return REAL,
                      momentum_volume_corr REAL,
                      volume_index_corr_next_return REAL,
                      volume_index_win_rate REAL,
                      high_momentum_volume_win_rate REAL,
                      high_momentum_volume_avg_return REAL,
                      high_momentum_volume_sample_count INTEGER,
                      cost_bias_return_corr_1d REAL,
                      cost_bias_return_corr_3d REAL,
                      cost_bias_return_corr_5d REAL,
                      cost_bucket TEXT,
                      cost_bucket_sample_count INTEGER,
                      cost_bucket_avg_return_1d REAL,
                      cost_bucket_avg_return_3d REAL,
                      cost_bucket_avg_return_5d REAL,
                      cost_bucket_win_rate_1d REAL,
                      cost_bucket_win_rate_3d REAL,
                      cost_bucket_win_rate_5d REAL,
                      calc_version TEXT NOT NULL DEFAULT 'stock_character_v1',
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (trade_date, stock_code))''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_stock_character_profiles_stock_date ON stock_character_profiles(stock_code, trade_date)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_stock_character_profiles_date_score ON stock_character_profiles(trade_date, momentum_score DESC)')
        for field_name, field_type in [
            ('sample_count', 'INTEGER'),
            ('character_score', 'REAL'),
            ('character_label', 'TEXT'),
            ('confidence_level', 'TEXT'),
            ('risk_level', 'TEXT'),
            ('character_summary', 'TEXT'),
            ('action_hint', 'TEXT'),
        ]:
            try:
                c.execute(f"ALTER TABLE stock_character_profiles ADD COLUMN {field_name} {field_type}")
            except sqlite3.OperationalError:
                pass
        
        # 为现有表添加状态字段（如果不存在）
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN status TEXT")
        except sqlite3.OperationalError:
            pass  # 字段已存在
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN status_start_date TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN amplitude REAL")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN lowest_price REAL")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN highest_price REAL")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN amount_std REAL")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN duration_days INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN trend_return REAL")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN has_volume_surge INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN five_day_acceleration INTEGER")
        except sqlite3.OperationalError:
            pass
        try:
            c.execute("ALTER TABLE momentum_scores ADD COLUMN underlying_data_json TEXT")
        except sqlite3.OperationalError:
            pass
        
        # 为现有表添加动量指标字段（如果不存在）
        momentum_metrics_fields = [
            ('return_1d', 'REAL'), ('return_5d', 'REAL'), ('return_10d', 'REAL'), ('return_20d', 'REAL'),
            ('return_60d', 'REAL'), ('return_120d', 'REAL'), ('return_250d', 'REAL'),
            ('amplitude_5d', 'REAL'), ('amplitude_20d', 'REAL'), ('amplitude_60d', 'REAL'),
            ('daily_volatility', 'REAL'), ('annualized_volatility', 'REAL'),
            ('max_gain_20d', 'REAL'), ('max_gain_60d', 'REAL'),
            ('max_drawdown_20d', 'REAL'), ('max_drawdown_60d', 'REAL'),
            ('recent_high', 'REAL'), ('recent_low', 'REAL'), ('price_vs_high', 'REAL'),
            ('ma5_slope', 'REAL'), ('ma10_slope', 'REAL'), ('ma20_slope', 'REAL'),
            ('price_vs_ma5', 'REAL'), ('price_vs_ma20', 'REAL'), ('ma5_vs_ma20', 'REAL'),
            ('trend_strength', 'REAL'),
            ('volume_ratio_5d', 'REAL'), ('volume_ratio_20d', 'REAL')
        ]
        for field_name, field_type in momentum_metrics_fields:
            try:
                c.execute(f"ALTER TABLE momentum_scores ADD COLUMN {field_name} {field_type}")
            except sqlite3.OperationalError:
                pass  # 字段已存在
        
        # 初始化安全表
        init_security_tables(conn, c)
        
        # 检查是否存在旧表，如果存在则迁移数据
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='daily_reviews'")
        if c.fetchone():
            migrate_old_data(conn, c)

        c.execute(
            """CREATE TABLE IF NOT EXISTS app_scheduler_meta (
                     key TEXT PRIMARY KEY,
                     value TEXT NOT NULL)"""
        )

        c.execute(
            """CREATE TABLE IF NOT EXISTS job_runs (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     job_name TEXT NOT NULL,
                     target_date TEXT,
                     status TEXT NOT NULL,
                     source TEXT,
                     params_json TEXT,
                     result_json TEXT,
                     error_message TEXT,
                     row_count INTEGER,
                     started_at TEXT NOT NULL,
                     finished_at TEXT,
                     duration_seconds REAL,
                     created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_job_runs_job_date ON job_runs(job_name, target_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_job_runs_status ON job_runs(status)")

        c.execute(
            """CREATE TABLE IF NOT EXISTS crawler_theme_ai_reports (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     report_key TEXT NOT NULL UNIQUE,
                     run_date TEXT NOT NULL,
                     start_time TEXT NOT NULL,
                     end_time TEXT NOT NULL,
                     hours REAL,
                     source TEXT DEFAULT '',
                     keyword TEXT DEFAULT '',
                     has_link TEXT DEFAULT '',
                     budget TEXT DEFAULT 'standard',
                     status TEXT NOT NULL DEFAULT 'success',
                     total_rows INTEGER DEFAULT 0,
                     previous_rows INTEGER DEFAULT 0,
                     prompt_chars INTEGER DEFAULT 0,
                     text_pipeline_version TEXT,
                     payload_json TEXT NOT NULL,
                     error_message TEXT,
                     generated_by TEXT,
                     generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_ctar_run_date ON crawler_theme_ai_reports(run_date DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ctar_generated_at ON crawler_theme_ai_reports(generated_at DESC)")

        c.execute(
            """CREATE TABLE IF NOT EXISTS daily_morning_briefs (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     owner_user_id INTEGER,
                     report_date TEXT NOT NULL,
                     source_name TEXT NOT NULL DEFAULT '多源财经早餐',
                     source_title TEXT,
                     source_summary TEXT,
                     source_url TEXT,
                     source_publish_time TEXT,
                     selected_reason TEXT,
                     source_payload_json TEXT,
                     article_text TEXT,
                     article_fetch_status TEXT,
                     crawler_context_json TEXT,
                     ai_payload_json TEXT,
                     model TEXT,
                     status TEXT NOT NULL DEFAULT 'success',
                     error_message TEXT,
                     generated_by TEXT,
                     pipeline_version TEXT,
                     generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                     UNIQUE(owner_user_id, report_date, source_name))"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_dmb_owner_date ON daily_morning_briefs(owner_user_id, report_date DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_dmb_public_date ON daily_morning_briefs(report_date DESC, source_name, status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_dmb_generated_at ON daily_morning_briefs(generated_at DESC)")

        _seed_rbac_data(conn, c)
        _backup_sqlite_before_schema_migration(c, "tenant")
        _ensure_tenant_columns_and_indexes(c)
        _ensure_sqlite_performance_indexes(c)
        
        conn.commit()
        conn.close()
        logging.info("数据库初始化成功")
    except Exception as e:
        logging.error(f"数据库初始化失败: {e}", exc_info=True)

# 封装数据库查询函数
def query_db(query, args=(), one=False):
    conn = get_sqlite_connection()
    try:
        c = conn.cursor()
        c.execute(query, args)
        rv = c.fetchall()
        return (rv[0] if rv else None) if one else rv
    finally:
        conn.close()


def query_db_rows(query, args=(), one=False):
    """Query SQLite rows with column-name access."""
    conn = get_sqlite_connection(sqlite3.Row)
    try:
        c = conn.cursor()
        c.execute(query, args)
        rv = c.fetchall()
        return (rv[0] if rv else None) if one else rv
    finally:
        conn.close()


@app.route('/healthz')
def healthz():
    return jsonify({
        'success': True,
        'status': 'ok',
        'service': 'ReviewsDaily',
        'csrf_enabled': CSRF_ENABLED,
        'request_id': getattr(g, 'request_id', None),
    })


@app.route('/metrics')
def metrics():
    if not METRICS_ENABLED:
        return jsonify({
            'success': False,
            'error': 'metrics disabled',
            'request_id': getattr(g, 'request_id', None),
        }), 404
    return jsonify(_metrics_snapshot())


@app.route('/readyz')
def readyz():
    checks = {}
    status_code = 200
    try:
        conn = get_sqlite_connection()
        conn.execute("SELECT 1")
        conn.close()
        checks['app_db'] = 'ok'
    except Exception as e:
        checks['app_db'] = f'error: {e}'
        status_code = 503

    if APP_HEALTH_CHECK_CRAWLER_DB:
        try:
            conn = get_crawler_mysql_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            conn.close()
            checks['crawler_mysql'] = 'ok'
        except Exception as e:
            checks['crawler_mysql'] = f'error: {e}'
            status_code = 503

    return jsonify({
        'success': status_code == 200,
        'status': 'ready' if status_code == 200 else 'not_ready',
        'checks': checks,
        'csrf_enabled': CSRF_ENABLED,
        'csp_enabled': CSP_ENABLED,
        'metrics_enabled': METRICS_ENABLED,
        'audit_log_enabled': AUDIT_LOG_ENABLED,
        'request_id': getattr(g, 'request_id', None),
    }), status_code


@app.route('/api/db-status')
def api_db_status():
    global _db_status_cache
    now = time.time()
    if APP_DB_STATUS_CACHE_TTL > 0:
        with _db_status_cache_lock:
            if _db_status_cache and now - _db_status_cache[0] < APP_DB_STATUS_CACHE_TTL:
                return jsonify(_db_status_cache[1])

    """返回当前数据库后端及连接状态，供前端弹框检测使用。无需登录。"""
    backend = APP_DB_BACKEND
    app_db_ok = False
    app_db_error = None
    try:
        conn = get_sqlite_connection()
        conn.execute("SELECT 1")
        conn.close()
        app_db_ok = True
    except Exception as e:
        app_db_error = str(e)

    crawler_db_ok = None
    crawler_db_error = None
    if APP_HEALTH_CHECK_CRAWLER_DB:
        try:
            conn = get_crawler_mysql_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            conn.close()
            crawler_db_ok = True
        except Exception as e:
            crawler_db_error = str(e)
            crawler_db_ok = False

    payload = {
        'backend': backend,
        'app_db_ok': app_db_ok,
        'app_db_error': app_db_error,
        'crawler_db_ok': crawler_db_ok,
        'crawler_db_error': crawler_db_error,
        'cached_for_seconds': APP_DB_STATUS_CACHE_TTL,
    }
    if APP_DB_STATUS_CACHE_TTL > 0:
        with _db_status_cache_lock:
            _db_status_cache = (time.time(), payload)
    return jsonify(payload)


@app.errorhandler(413)
def request_entity_too_large(_error):
    return jsonify({
        'success': False,
        'error': '上传内容过大',
        'max_bytes': app.config.get('MAX_CONTENT_LENGTH'),
        'request_id': getattr(g, 'request_id', None),
    }), 413
