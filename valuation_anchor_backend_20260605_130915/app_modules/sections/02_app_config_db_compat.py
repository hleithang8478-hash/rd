# -*- coding: utf-8 -*-
# AUTO-SPLIT from legacy app.py lines 1586-2603.
# Section: Flask app creation, project paths, DB backend compatibility, base hooks.
# Loaded by root app.py; keep project-root paths based on root app.py.

app = Flask(__name__)
if ProxyFix is not None and _env_bool("APP_TRUST_PROXY", False):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
# 数据库与密钥相对 app.py 目录，避免从不同工作目录启动时读写「另一个」database.db（典型症状：登录成功立刻回登录页）
_APP_ROOT = os.path.dirname(os.path.abspath(__file__))
_DATABASE_FILE_ENV = os.environ.get('APP_DATABASE_FILE')
if _DATABASE_FILE_ENV:
    DATABASE_FILE = (
        _DATABASE_FILE_ENV
        if os.path.isabs(_DATABASE_FILE_ENV)
        else os.path.join(_APP_ROOT, _DATABASE_FILE_ENV)
    )
else:
    DATABASE_FILE = os.path.join(_APP_ROOT, 'database.db')
os.environ['APP_DATABASE_FILE'] = DATABASE_FILE
REPORT_UPLOAD_DIR = os.path.join(_APP_ROOT, "static", "uploads", "reports")
REPORT_UPLOAD_STATIC_PREFIX = "uploads/reports"
REPORT_ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "epub"}
REPORT_CATEGORY_GROUPS = {
    "report": {
        "label": "报告",
        "children": {
            "report_internal": "内部报告",
            "report_research": "研报",
            "report_other": "其它报告",
        },
    },
    "system": {
        "label": "制度",
        "children": {
            "system_company": "公司制度",
            "system_exchange": "交易所制度",
            "system_regulator": "监管制度",
        },
    },
    "rule": {
        "label": "规则",
        "children": {
            "rule_company": "公司规则",
            "rule_exchange": "交易所规则",
        },
    },
    "book": {
        "label": "书籍",
        "children": {
            "book_epub": "EPUB 电子书",
            "book_other": "其它书籍",
        },
    },
}
REPORT_CATEGORIES = {
    key: label
    for group in REPORT_CATEGORY_GROUPS.values()
    for key, label in group["children"].items()
}
REPORT_CATEGORY_LEGACY_MAP = {
    "report": "report_other",
    "system": "system_company",
    "rule": "rule_company",
    "law": "system_regulator",
}
# 生成安全的密钥（如果不存在则生成新的）
SECRET_KEY_FILE = os.path.join(_APP_ROOT, 'secret_key.txt')
if os.path.exists(SECRET_KEY_FILE):
    with open(SECRET_KEY_FILE, 'r') as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, 'w') as f:
        f.write(app.secret_key)
    # 正常操作不记录
    # logging.debug("已生成新的安全密钥")

SESSION_TIMEOUT = 30 * 60  # 30分钟超时（更安全）
MAX_LOGIN_ATTEMPTS = 5  # 最大登录尝试次数
LOGIN_LOCKOUT_TIME = 15 * 60  # 锁定15分钟
APP_ALLOW_REGISTRATION = _env_bool("APP_ALLOW_REGISTRATION", False)
APP_HEALTH_CHECK_CRAWLER_DB = _env_bool("APP_HEALTH_CHECK_CRAWLER_DB", False)

app.config.update(
    MAX_CONTENT_LENGTH=_env_int("APP_MAX_CONTENT_LENGTH", 64 * 1024 * 1024, min_value=1024 * 1024),
    PERMANENT_SESSION_LIFETIME=timedelta(seconds=SESSION_TIMEOUT),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.environ.get("APP_SESSION_COOKIE_SAMESITE", "Lax"),
    SESSION_COOKIE_SECURE=_env_bool("APP_SESSION_COOKIE_SECURE", False),
)

# 登录/RBAC 流水日志：默认开启；关闭可设环境变量 AUTH_FLOW_LOG=0
AUTH_FLOW_LOG = os.environ.get('AUTH_FLOW_LOG', '1').lower() not in ('0', 'false', 'no')


SQLITE_TIMEOUT_SECONDS = float(os.environ.get("APP_SQLITE_TIMEOUT", "15"))
SQLITE_BUSY_TIMEOUT_MS = int(SQLITE_TIMEOUT_SECONDS * 1000)
SQLITE_PRAGMAS = (
    ("PRAGMA journal_mode=WAL", False),
    ("PRAGMA synchronous=NORMAL", True),
    ("PRAGMA temp_store=MEMORY", True),
    ("PRAGMA foreign_keys=ON", True),
)
APP_DB_BACKEND = os.environ.get("APP_DB_BACKEND", "sqlite").strip().lower()
if APP_DB_BACKEND not in ("mysql", "mysql8"):
    logging.warning(
        "[DB] APP_DB_BACKEND=%r — 当前使用 SQLite，生产环境请设置 APP_DB_BACKEND=mysql 并配置 APP_MYSQL_* 环境变量。",
        APP_DB_BACKEND,
    )
APP_MYSQL_CONFIG = {
    "host": os.environ.get("APP_MYSQL_HOST") or os.environ.get("DB_HOST", "127.0.0.1"),
    "port": _env_int("APP_MYSQL_PORT", int(os.environ.get("DB_PORT", "3306") or 3306), 1, 65535),
    "user": os.environ.get("APP_MYSQL_USER") or os.environ.get("DB_USER", "root"),
    "password": os.environ.get("APP_MYSQL_PASSWORD") or os.environ.get("DB_PASSWORD", ""),
    "database": os.environ.get("APP_MYSQL_DATABASE") or os.environ.get("APP_MYSQL_DB") or "reviewsdaily_app",
    "charset": os.environ.get("APP_MYSQL_CHARSET") or os.environ.get("DB_CHARSET", "utf8mb4"),
}
APP_MYSQL_POOL_SIZE = _env_int("APP_MYSQL_POOL_SIZE", _env_int("APP_THREADS", 8, 1, 64), 0, 128)
APP_MYSQL_CONNECT_TIMEOUT = _env_int("APP_MYSQL_CONNECT_TIMEOUT", 5, 1, 60)
APP_MYSQL_READ_TIMEOUT = _env_int("APP_MYSQL_READ_TIMEOUT", 20, 1, 300)
APP_MYSQL_WRITE_TIMEOUT = _env_int("APP_MYSQL_WRITE_TIMEOUT", 20, 1, 300)
APP_DB_SLOW_QUERY_MS = _env_int("APP_DB_SLOW_QUERY_MS", 800, 0, 600000)


def _app_db_diag():
    """Non-sensitive app DB diagnostics for logs and health responses."""
    return {
        'app_db_backend': APP_DB_BACKEND,
        'sqlite_database_file': DATABASE_FILE,
        'app_mysql_host': APP_MYSQL_CONFIG.get('host'),
        'app_mysql_port': APP_MYSQL_CONFIG.get('port'),
        'app_mysql_database': APP_MYSQL_CONFIG.get('database'),
        'app_mysql_user': APP_MYSQL_CONFIG.get('user'),
        'app_mysql_pool_size': APP_MYSQL_POOL_SIZE if APP_DB_BACKEND in ("mysql", "mysql8") else None,
    }


RBAC_PERMISSION_CACHE_TTL = float(os.environ.get("APP_RBAC_CACHE_TTL", "30"))
RBAC_SUPERUSER_CACHE_TTL = float(os.environ.get("APP_RBAC_SUPERUSER_CACHE_TTL", "300"))
APP_DB_STATUS_CACHE_TTL = float(os.environ.get("APP_DB_STATUS_CACHE_TTL", "30"))
ACCESS_LOG_ENABLED = os.environ.get("APP_ACCESS_LOG", "0").lower() in ("1", "true", "yes")
ACCESS_LOG_FLUSH_SIZE = int(os.environ.get("APP_ACCESS_LOG_FLUSH_SIZE", "50"))
ACCESS_LOG_FLUSH_SECONDS = float(os.environ.get("APP_ACCESS_LOG_FLUSH_SECONDS", "5"))
CSRF_ENABLED = _env_bool("APP_CSRF_ENABLED", True)
CSRF_TOKEN_SESSION_KEY = "_csrf_token"
CSRF_HEADER_NAMES = ("X-CSRF-Token", "X-XSRF-TOKEN")
MINIMAL_THEME_ASSET_VERSION = "tabs1"
WORKSPACE_SHELL_ASSET_VERSION = "workspace23"
THOR_GATEWAY_ASSET_VERSION = "thor3"
THOR_FRAME_BRIDGE_ASSET_VERSION = "thorframe1"
CSRF_PROTECTED_GET_ENDPOINTS = frozenset({
    "delete_essay",
    "delete_review",
    "migrate_data",
    "clean_duplicate_migrations",
})
CSP_ENABLED = _env_bool("APP_CSP_ENABLED", True)
METRICS_ENABLED = _env_bool("APP_METRICS_ENABLED", True)
AUDIT_LOG_ENABLED = _env_bool("APP_AUDIT_LOG", True)
MUTATION_RATE_LIMIT_PER_MINUTE = _env_int("APP_MUTATION_RATE_LIMIT_PER_MINUTE", 180, min_value=0)

_sqlite_wal_checked = False
_sqlite_wal_lock = threading.Lock()
_app_mysql_pool = []
_app_mysql_pool_lock = threading.Lock()
_app_mysql_pool_stats = {
    "created": 0,
    "reused": 0,
    "returned": 0,
    "closed": 0,
    "stale": 0,
    "slow_queries": 0,
}
_rbac_permission_cache = {}
_rbac_permission_cache_lock = threading.Lock()
_rbac_superuser_admin_cache = {}
_db_status_cache = None
_db_status_cache_lock = threading.Lock()
_access_log_buffer = []
_access_log_lock = threading.Lock()
_access_log_last_flush = time.time()
_sqlite_migration_backup_done = False
_metrics_lock = threading.Lock()
_metrics = {
    "started_at": time.time(),
    "requests_total": 0,
    "errors_total": 0,
    "inflight": 0,
    "latency_total_seconds": 0.0,
    "latency_count": 0,
    "max_latency_seconds": 0.0,
    "by_status": Counter(),
    "by_method": Counter(),
}
_mutation_rate_lock = threading.Lock()
_mutation_rate_buckets = {}

RICH_TEXT_ALLOWED_TAGS = {
    "a", "abbr", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3", "h4",
    "h5", "h6", "hr", "img", "li", "ol", "p", "pre", "s", "span", "strong",
    "sub", "sup", "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
}
RICH_TEXT_ALLOWED_ATTRS = {
    "*": {"class", "title"},
    "a": {"href", "target", "rel", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
RICH_TEXT_ALLOWED_SCHEMES = ("http://", "https://", "mailto:", "tel:", "/")
RICH_TEXT_ALLOWED_CLASSES = re.compile(r"^(?:ql-|text-|align-|ql-align-|ql-indent-|ql-size-|ql-font-)[A-Za-z0-9_-]+$")


class _SafeRichTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.skip_depth = 0

    def _allowed_attr(self, tag, name, value):
        name = (name or "").lower()
        if name.startswith("on") or name in {"style", "srcdoc"}:
            return None
        allowed = RICH_TEXT_ALLOWED_ATTRS.get("*", set()) | RICH_TEXT_ALLOWED_ATTRS.get(tag, set())
        if name not in allowed:
            return None
        value = "" if value is None else str(value).replace("\x00", "")
        if name in {"href", "src"}:
            compact = value.strip()
            lowered = compact.lower()
            if lowered.startswith("data:") or lowered.startswith("javascript:") or lowered.startswith("vbscript:"):
                return None
            if not lowered.startswith(RICH_TEXT_ALLOWED_SCHEMES):
                return None
            value = compact
        if name == "target" and value not in {"_blank", "_self"}:
            return None
        if name == "class":
            classes = [c for c in re.split(r"\s+", value.strip()) if c and RICH_TEXT_ALLOWED_CLASSES.match(c)]
            if not classes:
                return None
            value = " ".join(classes[:12])
        return name, value

    def _append_start(self, tag, attrs, closed=False):
        safe_attrs = []
        for name, value in attrs or []:
            attr = self._allowed_attr(tag, name, value)
            if attr:
                safe_attrs.append(f'{attr[0]}="{html.escape(attr[1], quote=True)}"')
        if tag == "a":
            names = {a.split("=", 1)[0] for a in safe_attrs}
            targets = [a for a in safe_attrs if a.startswith("target=")]
            if targets and 'rel' not in names:
                safe_attrs.append('rel="noopener noreferrer"')
        attr_text = (" " + " ".join(safe_attrs)) if safe_attrs else ""
        self.parts.append(f"<{tag}{attr_text}{' /' if closed else ''}>")

    def handle_starttag(self, tag, attrs):
        tag = (tag or "").lower()
        if tag in {"script", "style", "iframe", "object", "embed", "link", "meta", "base", "form"}:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in RICH_TEXT_ALLOWED_TAGS:
            self._append_start(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        tag = (tag or "").lower()
        if not self.skip_depth and tag in RICH_TEXT_ALLOWED_TAGS:
            self._append_start(tag, attrs, closed=True)

    def handle_endtag(self, tag):
        tag = (tag or "").lower()
        if tag in {"script", "style", "iframe", "object", "embed", "link", "meta", "base", "form"}:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if not self.skip_depth and tag in RICH_TEXT_ALLOWED_TAGS:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(html.escape(data or "", quote=False))

    def handle_entityref(self, name):
        if not self.skip_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip_depth:
            self.parts.append(f"&#{name};")


def sanitize_rich_text(value):
    value = "" if value is None else str(value)
    if not value:
        return ""
    parser = _SafeRichTextParser()
    try:
        parser.feed(value)
        parser.close()
        return "".join(parser.parts)
    except Exception:
        logging.warning("rich text sanitize failed; escaped raw content", exc_info=True)
        return html.escape(value)


class _HybridRow:
    def __init__(self, columns, values):
        self._columns = list(columns or [])
        self._values = tuple(values or ())
        self._map = {name: self._values[i] for i, name in enumerate(self._columns)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._columns

    def get(self, key, default=None):
        return self._map.get(key, default)


def _mysql_normalize_value(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return value


def _mysql_normalize_row(row):
    if row is None:
        return None
    return tuple(_mysql_normalize_value(v) for v in row)


def _mysql_normalize_rows(rows):
    return [_mysql_normalize_row(row) for row in rows]


def _mysql_quote_ident(name):
    return "`" + str(name).replace("`", "``") + "`"


MYSQL_VARCHAR_LENGTHS = {
    "username": 191,
    "password": 255,
    "date": 32,
    "start_date": 32,
    "end_date": 32,
    "target_date": 32,
    "time": 32,
    "trading_day": 32,
    "run_date": 32,
    "report_date": 32,
    "word": 191,
    "term": 191,
    "normalized_term": 191,
    "code": 64,
    "slug": 191,
    "name": 191,
    "module": 64,
    "report_key": 191,
    "task_id": 64,
    "status": 64,
    "source": 64,
    "source_type": 64,
    "target_type": 64,
    "target_id": 191,
    "relation_type": 64,
    "connection_type": 64,
    "mapping_name": 191,
    "portfolio_name": 191,
    "stock_code": 64,
    "stock_name": 191,
    "stock_market": 64,
    "field_name": 191,
    "field_type": 64,
    "table_name": 191,
    "template_name": 191,
    "concept_name": 191,
    "category": 64,
    "event_type": 64,
    "event_category": 64,
    "related_stock": 191,
    "title": 191,
    "key": 191,
    "client_label": 128,
    "worker_id": 128,
    "job_name": 128,
    "keyword": 191,
    "has_link": 32,
    "budget": 64,
    "model": 64,
    "source_name": 128,
    "source_publish_time": 32,
    "selected_reason": 64,
    "article_fetch_status": 64,
    "pipeline_version": 64,
    "generated_by": 128,
    "created_by": 128,
    "task_type": 64,
    "task_name": 191,
    "priority": 64,
    "reminder_type": 64,
    "color": 32,
    "card_type": 64,
    "join_type": 64,
    "primary_key_field": 191,
    "date_field": 191,
    "code_field": 191,
    "name_field": 191,
    "linked_entity_type": 64,
    "linked_entity_id": 191,
    "upload_time": 32,
    "created_at": 32,
    "updated_at": 32,
    "started_at": 32,
    "finished_at": 32,
    "picked_at": 32,
    "generated_at": 32,
    "attempt_time": 32,
    "access_time": 32,
    "ip_address": 64,
    "endpoint": 191,
    "method": 16,
}

MYSQL_LONG_TEXT_COLUMNS = {
    "content",
    "label",
    "name",
    "title",
    "table_display_name",
    "field_display_name",
    "description",
    "summary",
    "note",
    "tags",
    "keywords",
    "instruments",
    "tracking_items",
    "metadata_json",
    "settings_json",
    "annotation_json",
    "payload_json",
    "source_payload_json",
    "crawler_context_json",
    "ai_payload_json",
    "source_summary",
    "source_url",
    "article_text",
    "params_json",
    "result_json",
    "factors_json",
    "underlying_data_json",
    "execution_params",
    "result_summary",
    "error_message",
    "sql_text",
    "result_payload",
    "market_emotion",
    "sectors",
    "themes",
    "market_cap_performance",
    "investment_style",
    "major_events",
    "volume_status",
    "emotion_status",
    "divergence_status",
    "investment_strategies",
    "investment_styles",
    "shanghai_trend",
    "shenzhen_trend",
    "chinext_trend",
}


def _mysql_text_type_for_column(col_name, indexed=False):
    key = str(col_name or "").strip("`\"").lower()
    if indexed:
        return f"VARCHAR({MYSQL_VARCHAR_LENGTHS.get(key, 191)})"
    if key in MYSQL_LONG_TEXT_COLUMNS or key.endswith("_json"):
        return "LONGTEXT"
    if key in MYSQL_VARCHAR_LENGTHS:
        return f"VARCHAR({MYSQL_VARCHAR_LENGTHS[key]})"
    return "LONGTEXT"


def _mysql_strip_text_default(rest):
    return re.sub(r"\s+DEFAULT\s+(?:'[^']*'|\"[^\"]*\"|[^\s,]+)", "", rest, flags=re.I)


def _mysql_is_table_constraint_or_index(part):
    item = part.strip()
    if re.match(r"(PRIMARY\s+KEY|FOREIGN\s+KEY|CHECK|CONSTRAINT)\b", item, flags=re.I):
        return True
    if re.match(r"UNIQUE(?:\s+(?:KEY|INDEX))?\b", item, flags=re.I):
        return _mysql_first_parenthesized_content(item) is not None
    return re.match(
        r"(?:FULLTEXT\s+|SPATIAL\s+)?(?:KEY|INDEX)\s+(?:(?:[`\"]?[A-Za-z_][\w]*[`\"]?|USING\s+\w+)\s+)*\(",
        item,
        flags=re.I,
    ) is not None


def _mysql_first_parenthesized_content(text):
    start = text.find("(")
    if start < 0:
        return None
    depth = 0
    in_single = False
    in_double = False
    escape = False
    for pos in range(start, len(text)):
        ch = text[pos]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single or in_double:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:pos]
    return None


def _mysql_indexed_columns_from_table_part(part):
    item = part.strip()
    m = re.match(r"CONSTRAINT\s+[`\"]?[A-Za-z_][\w]*[`\"]?\s+(.+)$", item, flags=re.I | re.S)
    if m:
        item = m.group(1).lstrip()
    if not re.match(
        r"(PRIMARY\s+KEY|UNIQUE(?:\s+(?:KEY|INDEX))?|(?:FULLTEXT\s+|SPATIAL\s+)?(?:KEY|INDEX)\s+(?:(?:[`\"]?[A-Za-z_][\w]*[`\"]?|USING\s+\w+)\s+)*\()",
        item,
        flags=re.I,
    ):
        return set()
    cols = _mysql_first_parenthesized_content(item)
    if not cols:
        return set()
    out = set()
    for col in _split_sql_csv(cols):
        m = re.match(r"^[`\"]?([A-Za-z_][\w]*)[`\"]?(?:\s*\(\s*\d+\s*\))?(?:\s+(?:ASC|DESC))?$", col.strip(), flags=re.I)
        if m:
            out.add(m.group(1))
    return out


def _mysql_translate_column_def(part, indexed_cols=None):
    indexed_cols = indexed_cols or set()
    col_match = re.match(r"([`\"]?)([A-Za-z_][\w]*)([`\"]?)\s+(.+)$", part, flags=re.S)
    if not col_match or _mysql_is_table_constraint_or_index(part):
        return part
    _, col_name, _, rest = col_match.groups()
    rest = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTO_INCREMENT\b", "BIGINT PRIMARY KEY AUTO_INCREMENT", rest, flags=re.I)
    rest = re.sub(r"\bINTEGER\b", "BIGINT", rest, flags=re.I)
    rest = re.sub(r"\bREAL\b", "DOUBLE", rest, flags=re.I)
    rest = re.sub(r"\bBLOB\b", "LONGBLOB", rest, flags=re.I)
    if re.search(r"\b(?:TEXT|CLOB)\b", rest, flags=re.I):
        indexed = (
            col_name in indexed_cols
            or re.search(r"\b(?:PRIMARY\s+KEY|UNIQUE)\b", rest, flags=re.I) is not None
        )
        mysql_type = _mysql_text_type_for_column(col_name, indexed=indexed)
        rest = re.sub(r"\b(?:TEXT|CLOB)\b", mysql_type, rest, count=1, flags=re.I)
        if mysql_type in ("LONGTEXT", "LONGBLOB"):
            rest = _mysql_strip_text_default(rest)
    return f"{_mysql_quote_ident(col_name)} {rest}"


def _mysql_replace_qmark_placeholders(sql):
    out = []
    in_single = False
    in_double = False
    escape = False
    for ch in sql:
        if escape:
            out.append(ch)
            escape = False
            continue
        if ch == "\\":
            out.append(ch)
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
            continue
        if ch == "?" and not in_single and not in_double:
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


def _mysql_is_simple_index_columns(cols):
    for part in _split_sql_csv(cols):
        part = part.strip()
        if not re.match(r"^[`\"\w]+(?:\s+(?:ASC|DESC))?$", part, flags=re.I):
            return False
    return True


def _mysql_translate_index_columns(cols):
    out = []
    for part in _split_sql_csv(cols):
        item = part.strip()
        m = re.match(r"^([`\"]?)([A-Za-z_][\w]*)([`\"]?)(\s+(?:ASC|DESC))?$", item, flags=re.I)
        if not m:
            return None
        _, col_name, _, direction = m.groups()
        out.append(f"{_mysql_quote_ident(col_name)}{direction or ''}")
    return ", ".join(out)


def _mysql_text_index_column_prefixes(table, col_names):
    if APP_DB_BACKEND not in ("mysql", "mysql8"):
        return {}
    try:
        conn = _app_mysql_checkout_raw()
        try:
            with conn.cursor() as cur:
                placeholders = ",".join(["%s"] * len(col_names))
                cur.execute(
                    f"""SELECT column_name, data_type
                          FROM information_schema.columns
                         WHERE table_schema=%s AND table_name=%s
                           AND column_name IN ({placeholders})""",
                    tuple([APP_MYSQL_CONFIG["database"], table] + list(col_names)),
                )
                text_types = {"text", "tinytext", "mediumtext", "longtext", "blob", "tinyblob", "mediumblob", "longblob"}
                return {name: 191 for name, data_type in cur.fetchall() if str(data_type).lower() in text_types}
        finally:
            _app_mysql_return_raw(conn, rollback=True)
    except Exception:
        logging.debug("mysql text index column introspection failed table=%s cols=%s", table, col_names, exc_info=True)
        return {}


def _mysql_translate_index_columns_for_table(table, cols):
    parsed = []
    col_names = []
    for part in _split_sql_csv(cols):
        item = part.strip()
        m = re.match(r"^([`\"]?)([A-Za-z_][\w]*)([`\"]?)(\s+(?:ASC|DESC))?$", item, flags=re.I)
        if not m:
            return None
        _, col_name, _, direction = m.groups()
        parsed.append((col_name, direction or ""))
        col_names.append(col_name)
    prefix_lengths = _mysql_text_index_column_prefixes(table, col_names)
    out = []
    for col_name, direction in parsed:
        prefix = prefix_lengths.get(col_name)
        if prefix:
            out.append(f"{_mysql_quote_ident(col_name)}({prefix}){direction}")
        else:
            out.append(f"{_mysql_quote_ident(col_name)}{direction}")
    return ", ".join(out)


def _split_sql_csv(text):
    parts = []
    buf = []
    depth = 0
    in_single = False
    in_double = False
    escape = False
    for ch in text:
        if escape:
            buf.append(ch)
            escape = False
            continue
        if ch == "\\":
            buf.append(ch)
            escape = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            continue
        if not in_single and not in_double:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                parts.append("".join(buf).strip())
                buf = []
                continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _mysql_translate_create_table(sql):
    m = re.match(r"(\s*CREATE\s+(?:TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\w]+)\s*\((.*)\)(.*)$", sql, flags=re.I | re.S)
    if not m:
        return sql
    prefix, body, suffix = m.groups()
    parts = _split_sql_csv(body)
    indexed_cols = set()
    for part in parts:
        indexed_cols.update(_mysql_indexed_columns_from_table_part(part))
    out_parts = []
    for part in parts:
        out_parts.append(_mysql_translate_column_def(part, indexed_cols))
    translated = f"{prefix} (\n  " + ",\n  ".join(out_parts) + f"\n){suffix}"
    return translated


def _mysql_translate_alter_add_column(sql):
    m = re.match(r"(\s*ALTER\s+TABLE\s+[`\"\w]+\s+ADD\s+COLUMN\s+)(.+)$", sql, flags=re.I | re.S)
    if not m:
        return sql
    prefix, col_def = m.groups()
    return prefix + _mysql_translate_column_def(col_def)


def _mysql_translate_sql(sql):
    if not isinstance(sql, str):
        return sql
    s = sql.strip()
    low = s.lower()
    if low.startswith("pragma busy_timeout") or low in {"pragma foreign_keys=on", "pragma synchronous=normal", "pragma temp_store=memory"}:
        return None
    s = _mysql_replace_qmark_placeholders(sql)
    s = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGINT PRIMARY KEY AUTO_INCREMENT", s, flags=re.I)
    s = re.sub(r"\bAUTOINCREMENT\b", "AUTO_INCREMENT", s, flags=re.I)
    s = _mysql_translate_create_table(s)
    s = _mysql_translate_alter_add_column(s)
    s = re.sub(r"\bINTEGER\b", "BIGINT", s, flags=re.I)
    s = re.sub(r"\bREAL\b", "DOUBLE", s, flags=re.I)
    s = re.sub(r"\bBLOB\b", "LONGBLOB", s, flags=re.I)
    s = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT IGNORE INTO", s, flags=re.I)
    s = re.sub(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", "REPLACE INTO", s, flags=re.I)
    s = re.sub(r"\bCREATE\s+TEMP\s+TABLE\b", "CREATE TEMPORARY TABLE", s, flags=re.I)
    s = re.sub(r"\bALTER\s+TABLE\s+([`\"\w]+)\s+RENAME\s+TO\s+([`\"\w]+)", r"RENAME TABLE \1 TO \2", s, flags=re.I)
    s = re.sub(r"\bCAST\(([^)]+)\s+AS\s+TEXT\)", r"CAST(\1 AS CHAR)", s, flags=re.I)
    s = re.sub(r"COALESCE\(\s*([a-zA-Z_][\w]*)\.id\s*,\s*\1\.rowid\s*\)", r"\1.id", s, flags=re.I)
    s = re.sub(r"COALESCE\(\s*id\s*,\s*rowid\s*\)", "id", s, flags=re.I)
    s = re.sub(r"\browid\b", "id", s, flags=re.I)
    s = re.sub(r"datetime\('now'\s*,\s*'-15 minutes'\)", "DATE_SUB(NOW(), INTERVAL 15 MINUTE)", s, flags=re.I)
    s = re.sub(r"date\('now'\s*,\s*'\+7 days'\)", "DATE_ADD(CURDATE(), INTERVAL 7 DAY)", s, flags=re.I)
    s = re.sub(r"\bdatetime\(\s*([A-Za-z_][\w.]*|\`[^`]+\`)\s*\)", r"\1", s, flags=re.I)
    s = re.sub(r"\bdate\(\s*\?\s*\)", "DATE(%s)", s, flags=re.I)
    s = re.sub(r"\bdate\(\s*%s\s*\)", "DATE(%s)", s, flags=re.I)
    s = re.sub(r"\bdate\(\s*([A-Za-z_][\w.]*|\`[^`]+\`)\s*\)", r"DATE(\1)", s, flags=re.I)
    s = re.sub(
        r"(TRIM\([^)]+\))\s+GLOB\s+'\[0-9\]\[0-9\]\[0-9\]\[0-9\]\[0-9\]\[0-9\]\[0-9\]\[0-9\]'",
        r"\1 REGEXP '^[0-9]{8}$'",
        s,
        flags=re.I,
    )
    s = re.sub(r"\bON\s+CONFLICT\s*\([^)]+\)\s+DO\s+UPDATE\s+SET\b", "ON DUPLICATE KEY UPDATE", s, flags=re.I)
    s = re.sub(r"\bexcluded\.([a-zA-Z_][\w]*)\b", r"VALUES(\1)", s, flags=re.I)
    s = re.sub(r"\b(sentiment_meta|app_scheduler_meta)\s*\(\s*key\s*,", r"\1 (`key`,", s, flags=re.I)
    s = re.sub(r"\bWHERE\s+key\s*=", "WHERE `key`=", s, flags=re.I)
    return s


def _app_mysql_create_raw():
    import pymysql
    conn = pymysql.connect(
        host=APP_MYSQL_CONFIG["host"],
        port=APP_MYSQL_CONFIG["port"],
        user=APP_MYSQL_CONFIG["user"],
        password=APP_MYSQL_CONFIG["password"],
        database=APP_MYSQL_CONFIG["database"],
        charset=APP_MYSQL_CONFIG["charset"],
        autocommit=False,
        connect_timeout=APP_MYSQL_CONNECT_TIMEOUT,
        read_timeout=APP_MYSQL_READ_TIMEOUT,
        write_timeout=APP_MYSQL_WRITE_TIMEOUT,
    )
    _app_mysql_pool_stats["created"] += 1
    return conn


def _app_mysql_close_raw(conn):
    try:
        conn.close()
    except Exception:
        pass
    _app_mysql_pool_stats["closed"] += 1


def _app_mysql_checkout_raw():
    if APP_MYSQL_POOL_SIZE > 0:
        while True:
            with _app_mysql_pool_lock:
                raw = _app_mysql_pool.pop() if _app_mysql_pool else None
            if raw is None:
                break
            try:
                raw.ping(reconnect=True)
                _app_mysql_pool_stats["reused"] += 1
                return raw
            except Exception:
                _app_mysql_pool_stats["stale"] += 1
                _app_mysql_close_raw(raw)
    return _app_mysql_create_raw()


def _app_mysql_return_raw(conn, rollback=True):
    if conn is None:
        return
    reusable = False
    if APP_MYSQL_POOL_SIZE > 0:
        try:
            if rollback:
                conn.rollback()
            conn.ping(reconnect=False)
            reusable = True
        except Exception:
            _app_mysql_pool_stats["stale"] += 1
    if reusable:
        with _app_mysql_pool_lock:
            if len(_app_mysql_pool) < APP_MYSQL_POOL_SIZE:
                _app_mysql_pool.append(conn)
                _app_mysql_pool_stats["returned"] += 1
                return
    _app_mysql_close_raw(conn)


def _app_mysql_pool_snapshot():
    with _app_mysql_pool_lock:
        stats = dict(_app_mysql_pool_stats)
        stats["idle"] = len(_app_mysql_pool)
        stats["max_size"] = APP_MYSQL_POOL_SIZE
        stats["connect_timeout_seconds"] = APP_MYSQL_CONNECT_TIMEOUT
        stats["read_timeout_seconds"] = APP_MYSQL_READ_TIMEOUT
        stats["write_timeout_seconds"] = APP_MYSQL_WRITE_TIMEOUT
        return stats


def _compact_sql_for_log(sql):
    return re.sub(r"\s+", " ", str(sql or "")).strip()[:600]


def _log_app_mysql_slow_query(sql, elapsed_seconds):
    if APP_DB_SLOW_QUERY_MS <= 0:
        return
    elapsed_ms = elapsed_seconds * 1000.0
    if elapsed_ms < APP_DB_SLOW_QUERY_MS:
        return
    _app_mysql_pool_stats["slow_queries"] += 1
    logging.warning(
        "[db] slow app mysql query cost=%.1fms sql=%s",
        elapsed_ms,
        _compact_sql_for_log(sql),
    )


class _MySQLCompatCursor:
    def __init__(self, conn, cursor):
        self._conn = conn
        self._cursor = cursor
        self._rows = None
        self._description = None
        self.lastrowid = None
        self.rowcount = -1

    @property
    def description(self):
        return self._description if self._rows is not None else self._cursor.description

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        try:
            self._cursor.close()
        except Exception:
            pass

    def _set_rows(self, columns, rows):
        self._description = [(c, None, None, None, None, None, None) for c in columns]
        self._rows = _mysql_normalize_rows(rows)
        self.rowcount = len(self._rows)
        self.lastrowid = None

    def _execute_pragma(self, sql):
        table_match = re.match(r"PRAGMA\s+table_info\(([^)]+)\)", sql, flags=re.I)
        if table_match:
            table = table_match.group(1).strip("`'\" ")
            with self._conn._raw.cursor() as cur:
                cur.execute(
                    """SELECT column_name, column_type, is_nullable, column_default, column_key,
                              extra, ordinal_position
                         FROM information_schema.columns
                        WHERE table_schema=%s AND table_name=%s
                        ORDER BY ordinal_position""",
                    (APP_MYSQL_CONFIG["database"], table),
                )
                rows = []
                for name, col_type, nullable, default, key, extra, pos in cur.fetchall():
                    pk = 1 if key == "PRI" else 0
                    notnull = 0 if nullable == "YES" else 1
                    rows.append((int(pos) - 1, name, col_type, notnull, default, pk))
            self._set_rows(["cid", "name", "type", "notnull", "dflt_value", "pk"], rows)
            return True
        index_list_match = re.match(r"PRAGMA\s+index_list\(([^)]+)\)", sql, flags=re.I)
        if index_list_match:
            table = index_list_match.group(1).strip("`'\" ")
            with self._conn._raw.cursor() as cur:
                cur.execute(
                    """SELECT index_name, non_unique
                         FROM information_schema.statistics
                        WHERE table_schema=%s AND table_name=%s AND index_name <> 'PRIMARY'
                        GROUP BY index_name, non_unique
                        ORDER BY index_name""",
                    (APP_MYSQL_CONFIG["database"], table),
                )
                fetched = cur.fetchall()
                for name, _non_unique in fetched:
                    self._conn._pragma_index_table[name] = table
                rows = [(i, name, 0 if non_unique else 1, "c", 0) for i, (name, non_unique) in enumerate(fetched)]
            self._set_rows(["seq", "name", "unique", "origin", "partial"], rows)
            return True
        index_info_match = re.match(r"PRAGMA\s+index_info\(([^)]+)\)", sql, flags=re.I)
        if index_info_match:
            index = index_info_match.group(1).strip("`'\" ")
            table = self._conn._pragma_index_table.get(index)
            with self._conn._raw.cursor() as cur:
                if table:
                    cur.execute(
                        """SELECT seq_in_index, column_name
                             FROM information_schema.statistics
                            WHERE table_schema=%s AND table_name=%s AND index_name=%s
                            ORDER BY seq_in_index""",
                        (APP_MYSQL_CONFIG["database"], table, index),
                    )
                else:
                    cur.execute(
                        """SELECT seq_in_index, column_name
                             FROM information_schema.statistics
                            WHERE table_schema=%s AND index_name=%s
                            ORDER BY table_name, seq_in_index""",
                        (APP_MYSQL_CONFIG["database"], index),
                    )
                rows = [(int(seq) - 1, int(seq) - 1, col) for seq, col in cur.fetchall()]
            self._set_rows(["seqno", "cid", "name"], rows)
            return True
        return False

    def _execute_sqlite_master(self, args):
        table = args[0] if args else None
        if table is None:
            m = re.search(r"\bname\s*=\s*['\"]([^'\"]+)['\"]", getattr(self, "_last_sql", ""), flags=re.I)
            table = m.group(1) if m else None
        with self._conn._raw.cursor() as cur:
            if table is None:
                cur.execute(
                    """SELECT table_name FROM information_schema.tables
                        WHERE table_schema=%s AND table_type='BASE TABLE'""",
                    (APP_MYSQL_CONFIG["database"],),
                )
            else:
                cur.execute(
                    """SELECT table_name FROM information_schema.tables
                        WHERE table_schema=%s AND table_name=%s LIMIT 1""",
                    (APP_MYSQL_CONFIG["database"], table),
                )
            rows = cur.fetchall()
        self._set_rows(["name" if table is None else "1"], rows)

    def _index_exists(self, table, index_name):
        with self._conn._raw.cursor() as cur:
            cur.execute(
                """SELECT 1 FROM information_schema.statistics
                    WHERE table_schema=%s AND table_name=%s AND index_name=%s LIMIT 1""",
                (APP_MYSQL_CONFIG["database"], table, index_name),
            )
            return cur.fetchone() is not None

    def _execute_create_index_if_needed(self, sql):
        m = re.match(
            r"\s*CREATE\s+(UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+([`\"\w]+)\s+ON\s+([`\"\w]+)\s*\((.+)\)\s*$",
            sql,
            flags=re.I | re.S,
        )
        if not m:
            return False
        unique, index_name, table, cols = m.groups()
        index_name = index_name.strip("`\"")
        table = table.strip("`\"")
        if self._index_exists(table, index_name):
            self._set_rows([], [])
            self.rowcount = 0
            return True
        if not _mysql_is_simple_index_columns(cols):
            self._set_rows([], [])
            self.rowcount = 0
            return True
        cols_sql = _mysql_translate_index_columns_for_table(table, cols)
        if not cols_sql:
            self._set_rows([], [])
            self.rowcount = 0
            return True
        translated = f"CREATE {'UNIQUE ' if unique else ''}INDEX {_mysql_quote_ident(index_name)} ON {_mysql_quote_ident(table)} ({cols_sql})"
        try:
            self._raw_execute(_mysql_translate_sql(translated))
        except Exception as e:
            msg = str(e).lower()
            if "duplicate key name" in msg or "already exists" in msg:
                self._set_rows([], [])
                self.rowcount = 0
                return True
            raise
        self.rowcount = self._cursor.rowcount
        self.lastrowid = self._cursor.lastrowid
        return True

    def _execute_create_index_plain(self, sql):
        m = re.match(
            r"\s*CREATE\s+(UNIQUE\s+)?INDEX\s+([`\"\w]+)\s+ON\s+([`\"\w]+)\s*\((.+)\)\s*$",
            sql,
            flags=re.I | re.S,
        )
        if not m:
            return False
        unique, index_name, table, cols = m.groups()
        index_name = index_name.strip("`\"")
        table = table.strip("`\"")
        if not _mysql_is_simple_index_columns(cols):
            self._set_rows([], [])
            self.rowcount = 0
            return True
        cols_sql = _mysql_translate_index_columns_for_table(table, cols)
        if not cols_sql:
            self._set_rows([], [])
            self.rowcount = 0
            return True
        translated = f"CREATE {'UNIQUE ' if unique else ''}INDEX {_mysql_quote_ident(index_name)} ON {_mysql_quote_ident(table)} ({cols_sql})"
        self._raw_execute(_mysql_translate_sql(translated))
        self.rowcount = self._cursor.rowcount
        self.lastrowid = self._cursor.lastrowid
        return True

    def _raw_execute(self, sql, args=None):
        started = time.time()
        try:
            if args is None:
                return self._cursor.execute(sql)
            return self._cursor.execute(sql, args)
        finally:
            _log_app_mysql_slow_query(sql, time.time() - started)

    def execute(self, sql, args=()):
        self._rows = None
        self._description = None
        args = tuple(args or ())
        stripped = sql.strip() if isinstance(sql, str) else ""
        self._last_sql = stripped
        if stripped.lower().startswith("pragma ") and self._execute_pragma(stripped):
            return self
        if "sqlite_master" in stripped.lower():
            if stripped.lower().lstrip().startswith("select"):
                self._execute_sqlite_master(args)
                return self
        if self._execute_create_index_if_needed(stripped):
            return self
        if self._execute_create_index_plain(stripped):
            return self
        translated = _mysql_translate_sql(sql)
        if translated is None:
            self._set_rows([], [])
            self.rowcount = 0
            return self
        try:
            self._raw_execute(translated, args)
            self.rowcount = self._cursor.rowcount
            self.lastrowid = self._cursor.lastrowid
            return self
        except Exception as e:
            msg = str(e).lower()
            if any(x in msg for x in ("duplicate column", "duplicate key name", "already exists", "check that column/key exists")):
                raise sqlite3.OperationalError(str(e))
            if "duplicate entry" in msg:
                raise sqlite3.IntegrityError(str(e))
            raise

    def executemany(self, sql, seq_of_args):
        translated = _mysql_translate_sql(sql)
        started = time.time()
        try:
            self._cursor.executemany(translated, seq_of_args)
        finally:
            _log_app_mysql_slow_query(translated, time.time() - started)
        self.rowcount = self._cursor.rowcount
        self.lastrowid = self._cursor.lastrowid
        return self

    def _wrap(self, rows):
        rows = _mysql_normalize_rows(rows)
        if self._conn.row_factory is None:
            return rows
        desc = self.description or []
        cols = [d[0] for d in desc]
        return [_HybridRow(cols, row) for row in rows]

    def fetchall(self):
        if self._rows is not None:
            rows = self._rows
            self._rows = []
            return self._wrap(rows)
        return self._wrap(self._cursor.fetchall())

    def fetchone(self):
        if self._rows is not None:
            if not self._rows:
                return None
            row = self._rows.pop(0)
            return self._wrap([row])[0]
        row = self._cursor.fetchone()
        if row is None:
            return None
        return self._wrap([row])[0]

    def __iter__(self):
        return iter(self.fetchall())


class _MySQLCompatConnection:
    def __init__(self, row_factory=None):
        self.row_factory = row_factory
        self._pragma_index_table = {}
        self._closed = False
        self._raw = _app_mysql_checkout_raw()

    def cursor(self):
        if self._closed:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
        return _MySQLCompatCursor(self, self._raw.cursor())

    def execute(self, sql, args=()):
        cur = self.cursor()
        cur.execute(sql, args)
        return cur

    def executemany(self, sql, seq_of_args):
        cur = self.cursor()
        cur.executemany(sql, seq_of_args)
        return cur

    def commit(self):
        if self._closed:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
        self._raw.commit()

    def rollback(self):
        if self._closed:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
        self._raw.rollback()

    def close(self):
        if self._closed:
            return
        raw = self._raw
        self._raw = None
        self._closed = True
        _app_mysql_return_raw(raw, rollback=True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            try:
                self.rollback()
            except Exception:
                pass
        self.close()
        return False


def get_sqlite_connection(row_factory=None):
    """Create an app SQLite connection with production-friendly pragmas."""
    if APP_DB_BACKEND in ("mysql", "mysql8"):
        return _MySQLCompatConnection(row_factory=row_factory)
    global _sqlite_wal_checked
    conn = sqlite3.connect(DATABASE_FILE, timeout=SQLITE_TIMEOUT_SECONDS)
    if row_factory is not None:
        conn.row_factory = row_factory
    conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
    if not _sqlite_wal_checked:
        with _sqlite_wal_lock:
            if not _sqlite_wal_checked:
                for stmt, _ in SQLITE_PRAGMAS:
                    try:
                        conn.execute(stmt)
                    except sqlite3.DatabaseError as e:
                        logging.debug("SQLite pragma skipped %s: %s", stmt, e)
                _sqlite_wal_checked = True
    else:
        for stmt, every_time in SQLITE_PRAGMAS:
            if every_time:
                try:
                    conn.execute(stmt)
                except sqlite3.DatabaseError:
                    pass
    return conn


configure_juyuan_bridge_database(get_sqlite_connection, backend=APP_DB_BACKEND)
register_juyuan_bridge_routes(app, DATABASE_FILE)


def _rbac_cache_key(username):
    return (username or "").strip().casefold()


def _rbac_get_cached_permission_codes(username):
    key = _rbac_cache_key(username)
    if not key:
        return None
    now = time.time()
    with _rbac_permission_cache_lock:
        cached = _rbac_permission_cache.get(key)
        if cached and now - cached[0] < RBAC_PERMISSION_CACHE_TTL:
            return cached[1]
    return None


def _rbac_set_cached_permission_codes(username, codes):
    key = _rbac_cache_key(username)
    if not key:
        return codes
    frozen = frozenset(codes or ())
    with _rbac_permission_cache_lock:
        _rbac_permission_cache[key] = (time.time(), frozen)
    return frozen


def _rbac_invalidate_permission_cache(username=None):
    with _rbac_permission_cache_lock:
        if username:
            _rbac_permission_cache.pop(_rbac_cache_key(username), None)
        else:
            _rbac_permission_cache.clear()


def _access_log_flush(force=False):
    if not ACCESS_LOG_ENABLED:
        return
    global _access_log_last_flush
    with _access_log_lock:
        if not _access_log_buffer:
            return
        age = time.time() - _access_log_last_flush
        if not force and len(_access_log_buffer) < ACCESS_LOG_FLUSH_SIZE and age < ACCESS_LOG_FLUSH_SECONDS:
            return
        rows = list(_access_log_buffer)
        _access_log_buffer.clear()
        _access_log_last_flush = time.time()
    try:
        conn = get_sqlite_connection()
        c = conn.cursor()
        c.executemany(
            "INSERT INTO access_logs (username, ip_address, endpoint, method) VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()
    except Exception:
        logging.debug("access log flush failed", exc_info=True)


def get_csrf_token():
    """Return the current session CSRF token, creating one on demand."""
    token = session.get(CSRF_TOKEN_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_TOKEN_SESSION_KEY] = token
    return token


def _csrf_request_token():
    token = request.headers.get("X-CSRF-Token") or request.headers.get("X-XSRF-TOKEN")
    if token:
        return token
    if request.is_json:
        data = request.get_json(silent=True) or {}
        token = data.get("_csrf_token") or data.get("csrf_token")
        if token:
            return token
    return request.form.get("_csrf_token") or request.form.get("csrf_token") or request.args.get("_csrf_token")


def _request_wants_json_response():
    if request.path.startswith("/api/") or request.is_json:
        return True
    best = request.accept_mimetypes.best
    return bool(
        best == "application/json"
        and request.accept_mimetypes[best] >= request.accept_mimetypes["text/html"]
    )


def _status_template_response(template_name, status_code, fallback_title, fallback_message, **context):
    try:
        return render_template(template_name, **context), status_code
    except TemplateNotFound:
        body = (
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            "<title>{title}</title></head><body>"
            "<h1>{title}</h1><p>{message}</p></body></html>"
        ).format(
            title=html.escape(str(fallback_title), quote=True),
            message=html.escape(str(fallback_message), quote=True),
        )
        return body, status_code


def _auth_login_required_response(message="请先登录后再继续操作。", reason="login_required"):
    if _request_wants_json_response():
        return jsonify({
            "success": False,
            "error": message,
            "reason": reason,
            "request_id": getattr(g, "request_id", None),
        }), 401
    return redirect(url_for("login"))


def _auth_forbidden_response(required=None, message="当前账号没有权限访问该页面。"):
    required_list = [str(code) for code in (required or ()) if code]
    payload = {
        "success": False,
        "error": message,
        "required_permissions": required_list,
        "request_id": getattr(g, "request_id", None),
    }
    if _request_wants_json_response():
        return jsonify(payload), 403
    return _status_template_response(
        "permission_denied.html",
        403,
        "没有权限",
        message,
        message=message,
        required_permissions=required_list,
        username=session.get("username") or "",
        path=request.path,
        endpoint=request.endpoint or "",
        request_id=getattr(g, "request_id", None),
    )


def _csrf_failure_response(reason):
    message = "页面安全码已过期，请刷新页面后重试。"
    payload = {
        "success": False,
        "error": message,
        "reason": reason,
        "request_id": getattr(g, "request_id", None),
    }
    if _request_wants_json_response():
        return jsonify(payload), 403
    if not session.get("username") and request.endpoint not in ("login", "register"):
        return redirect(url_for("login"))
    if request.endpoint == "login":
        diag = _login_page_diag(step="csrf_failed", csrf_reason=reason) if "_login_page_diag" in globals() else {}
        return render_template("login.html", error=message, auth_diag=diag), 403
    return _status_template_response(
        "security_error.html",
        403,
        "页面安全码已过期",
        message,
        message=message,
        reason=reason,
        path=request.path,
        request_id=getattr(g, "request_id", None),
    )


def _is_csrf_required():
    if not CSRF_ENABLED:
        return False
    if request.endpoint in ("static", "healthz", "readyz", "metrics"):
        return False
    if request.path.startswith(BRIDGE_PATH_PREFIX):
        return False
    if request.endpoint not in ("login", "register") and not session.get("username"):
        return False
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        return True
    return request.method == "GET" and request.endpoint in CSRF_PROTECTED_GET_ENDPOINTS


def _record_metric(response=None):
    try:
        duration = max(0.0, time.time() - float(getattr(g, "request_started_at", time.time())))
        status_code = int(getattr(response, "status_code", 500) or 500)
        with _metrics_lock:
            _metrics["requests_total"] += 1
            _metrics["inflight"] = max(0, _metrics["inflight"] - 1)
            _metrics["latency_total_seconds"] += duration
            _metrics["latency_count"] += 1
            _metrics["max_latency_seconds"] = max(_metrics["max_latency_seconds"], duration)
            _metrics["by_status"][str(status_code)] += 1
            _metrics["by_method"][request.method] += 1
            if status_code >= 500:
                _metrics["errors_total"] += 1
    except Exception:
        logging.debug("metrics update failed", exc_info=True)
    return response


def _metrics_snapshot():
    with _metrics_lock:
        count = int(_metrics.get("latency_count") or 0)
        avg = (_metrics["latency_total_seconds"] / count) if count else 0.0
        payload = {
            "success": True,
            "service": "知行合一",
            "uptime_seconds": round(time.time() - float(_metrics["started_at"]), 3),
            "requests_total": int(_metrics["requests_total"]),
            "errors_total": int(_metrics["errors_total"]),
            "inflight": int(_metrics["inflight"]),
            "avg_latency_seconds": round(avg, 6),
            "max_latency_seconds": round(float(_metrics["max_latency_seconds"]), 6),
            "by_status": dict(_metrics["by_status"]),
            "by_method": dict(_metrics["by_method"]),
        }
    if APP_DB_BACKEND in ("mysql", "mysql8"):
        payload["app_mysql_pool"] = _app_mysql_pool_snapshot()
    crawler_pool_snapshot = globals().get("_crawler_mysql_pool_snapshot")
    if callable(crawler_pool_snapshot):
        payload["crawler_mysql_pool"] = crawler_pool_snapshot()
    return payload


def _record_audit_event(action, resource_type="", resource_id="", details=None, success=True):
    if not AUDIT_LOG_ENABLED:
        return
    try:
        if not has_request_context():
            return
        username = session.get("username") or "anonymous"
        ip_address = request.remote_addr
        endpoint = request.endpoint or ""
        method = request.method or ""
        path = request.path or ""
        request_id = getattr(g, "request_id", None)
        details_json = json.dumps(details or {}, ensure_ascii=False, default=str)[:4000]
        conn = get_sqlite_connection()
        c = conn.cursor()
        c.execute(
            """INSERT INTO audit_events
               (request_id, username, ip_address, endpoint, method, path, action,
                resource_type, resource_id, success, details_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                request_id,
                username,
                ip_address,
                endpoint,
                method,
                path,
                action,
                resource_type,
                str(resource_id or "")[:200],
                1 if success else 0,
                details_json,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        logging.debug("audit event write failed", exc_info=True)


def _rate_limit_mutation_request():
    if MUTATION_RATE_LIMIT_PER_MINUTE <= 0:
        return None
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    user_key = session.get("username") or request.remote_addr or "anonymous"
    bucket_key = (user_key, int(time.time() // 60))
    with _mutation_rate_lock:
        current_minute = bucket_key[1]
        stale = [key for key in _mutation_rate_buckets if key[1] < current_minute - 1]
        for key in stale:
            _mutation_rate_buckets.pop(key, None)
        count = _mutation_rate_buckets.get(bucket_key, 0) + 1
        _mutation_rate_buckets[bucket_key] = count
    if count > MUTATION_RATE_LIMIT_PER_MINUTE:
        return jsonify({
            "success": False,
            "error": "请求过于频繁，请稍后再试",
            "request_id": getattr(g, "request_id", None),
        }), 429
    return None


def _ensure_sqlite_performance_indexes(c):
    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_users_username_norm ON users(lower(trim(username)))",
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_success_time ON login_attempts(ip_address, success, attempt_time)",
        "CREATE INDEX IF NOT EXISTS idx_access_logs_time ON access_logs(access_time)",
        "CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_essays_date_created ON essays(date DESC, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_reviews_date_desc ON reviews(date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_investment_plans_status ON investment_plans(status)",
        "CREATE INDEX IF NOT EXISTS idx_investment_calendar_start_date ON investment_calendar(start_date)",
        "CREATE INDEX IF NOT EXISTS idx_investment_calendar_related_plan ON investment_calendar(related_plan_id)",
        "CREATE INDEX IF NOT EXISTS idx_topic_cards_topic ON topic_cards(topic_id)",
        "CREATE INDEX IF NOT EXISTS idx_card_connections_topic ON card_connections(topic_id)",
        "CREATE INDEX IF NOT EXISTS idx_screening_task_executions_created ON screening_task_executions(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_portfolio_data_name_date ON portfolio_data(portfolio_name, date)",
        "CREATE INDEX IF NOT EXISTS idx_portfolio_data_stock_name_date ON portfolio_data(stock_name, date DESC)",
        "CREATE INDEX IF NOT EXISTS idx_momentum_scores_date_score ON momentum_scores(date, momentum_score DESC)",
        "CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_id)",
        "CREATE INDEX IF NOT EXISTS idx_role_permissions_permission ON role_permissions(permission_id)",
    ):
        try:
            c.execute(stmt)
        except sqlite3.OperationalError as e:
            logging.debug("SQLite index skipped %s: %s", stmt, e)


def _auth_log(event, **fields):
    """统一前缀 [auth]，便于 grep / 接入日志系统。"""
    if not AUTH_FLOW_LOG:
        return
    try:
        tail = ' '.join('%s=%r' % (k, v) for k, v in sorted(fields.items()))
    except Exception:
        tail = ''
    logging.info('[auth] %s | %s', event, tail)


def _auth_permission_codes_preview(username, limit=40):
    try:
        codes = sorted(_rbac_get_user_permission_codes(username))
        return {'count': len(codes), 'codes': codes[:limit]}
    except Exception as e:
        return {'error': str(e)}


def _login_page_diag(**extra):
    """登录页下发给浏览器控制台与 JSON-LD 的诊断字段（勿在生产对公网暴露敏感信息时可关 AUTH_FLOW_LOG）。"""
    d = {
        'step': 'login_page',
        'time': datetime.now().isoformat(timespec='seconds'),
        'path': getattr(request, 'path', '') or '',
        'endpoint': getattr(request, 'endpoint', None),
        'method': getattr(request, 'method', '') or '',
        'remote_addr': getattr(request, 'remote_addr', None),
        'session_username': session.get('username'),
        **_app_db_diag(),
    }
    if extra:
        d.update(extra)
    return d


@app.context_processor
def inject_rbac_template_helpers():
    """模板中 has_perm('code')：只认角色-权限表里实际挂上的 code。

    刻意不用 user_has_permission：后者对配置超管用户名、以及部分兜底逻辑会「恒为真」，
    导致首页日记区、灰显按钮等 UI 权限开关看起来「怎么改都不生效」。
    """
    def has_perm(code):
        u = session.get('username')
        if not u or not code:
            return False
        try:
            owned = _rbac_get_user_permission_codes(u)
            if not owned and has_request_context() and not getattr(g, '_rbac_has_perm_repair', False):
                g._rbac_has_perm_repair = True
                _rbac_repair_login_access(u)
                owned = _rbac_get_user_permission_codes(u)
            grants = globals().get('_rbac_permission_code_grants')
            if callable(grants):
                return grants(owned, code, include_descendants=True)
            return code in owned
        except Exception:
            return False

    def ai_provider_label():
        try:
            cfg_fn = globals().get("get_ai_provider_config")
            if callable(cfg_fn):
                cfg = cfg_fn(mask_secret=True)
                return cfg.get("label") or cfg.get("provider") or "AI"
        except Exception:
            pass
        return "AI"

    return dict(has_perm=has_perm, csrf_token=get_csrf_token, ai_provider_label=ai_provider_label)


@app.before_request
def production_request_guard():
    if not getattr(g, "request_id", None):
        g.request_id = (request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]).strip()[:64]
    g.request_started_at = time.time()
    with _metrics_lock:
        _metrics["inflight"] += 1
    limited = _rate_limit_mutation_request()
    if limited is not None:
        return limited
    if not _is_csrf_required():
        return None
    expected = session.get(CSRF_TOKEN_SESSION_KEY)
    provided = _csrf_request_token()
    if not expected:
        return _csrf_failure_response("session_token_missing")
    if not provided or not secrets.compare_digest(str(expected), str(provided)):
        logging.warning(
            "CSRF validation failed endpoint=%s path=%s method=%s remote=%s",
            request.endpoint,
            request.path,
            request.method,
            request.remote_addr,
        )
        _record_audit_event(
            "csrf_denied",
            resource_type=request.endpoint or "",
            success=False,
            details={"path": request.path, "method": request.method},
        )
        return _csrf_failure_response("token_mismatch")


@app.after_request
def inject_platform_security_assets(response):
    try:
        if response.status_code != 200 or response.direct_passthrough or response.is_streamed:
            return response
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type:
            return response
        html_text = response.get_data(as_text=True)
        if "</head>" not in html_text.lower() and "</body>" not in html_text.lower():
            return response
        changed = False
        lower_html = html_text.lower()
        if CSRF_ENABLED and 'name="csrf-token"' not in lower_html and "</head>" in lower_html:
            head_pos = lower_html.rfind("</head>")
            token_meta = '<meta name="csrf-token" content="%s">' % html.escape(get_csrf_token(), quote=True)
            html_text = html_text[:head_pos] + token_meta + html_text[head_pos:]
            lower_html = html_text.lower()
            changed = True
        if CSRF_ENABLED and "platform_security.js" not in lower_html and "</head>" in lower_html:
            head_pos = lower_html.rfind("</head>")
            script = '<script src="%s"></script>' % url_for("static", filename="platform_security.js", v="prod1")
            html_text = html_text[:head_pos] + script + html_text[head_pos:]
            lower_html = html_text.lower()
            changed = True
        elif CSRF_ENABLED and "platform_security.js" not in lower_html and "</body>" in lower_html:
            body_pos = lower_html.rfind("</body>")
            script = '<script src="%s"></script>' % url_for("static", filename="platform_security.js", v="prod1")
            html_text = html_text[:body_pos] + script + html_text[body_pos:]
            lower_html = html_text.lower()
            changed = True
        if "form_drafts.js" not in lower_html and "</body>" in lower_html:
            body_pos = html_text.lower().rfind("</body>")
            script = '<script src="%s"></script>' % url_for("static", filename="form_drafts.js", v=WORKSPACE_SHELL_ASSET_VERSION)
            html_text = html_text[:body_pos] + script + html_text[body_pos:]
            lower_html = html_text.lower()
            changed = True
        if "app_minimal_theme.css" not in lower_html and "</head>" in lower_html:
            head_pos = lower_html.rfind("</head>")
            css_link = '<link rel="stylesheet" href="%s">' % url_for("static", filename="app_minimal_theme.css", v=MINIMAL_THEME_ASSET_VERSION)
            html_text = html_text[:head_pos] + css_link + html_text[head_pos:]
            changed = True
        if changed:
            response.set_data(html_text)
            response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception as e:
        logging.warning("inject platform security assets failed: %s", e, exc_info=True)
    return response


@app.after_request
def inject_global_workspace_panels(response):
    """Inject global workspace navigation/tabs and optional command panel into logged-in HTML pages."""
    try:
        if not session.get("username"):
            return response
        if request.endpoint in ("static", "login", "register", "logout"):
            return response
        if response.status_code != 200 or response.direct_passthrough or response.is_streamed:
            return response
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type:
            return response
        html = response.get_data(as_text=True)
        pos = html.lower().rfind("</body>")
        if pos < 0:
            return response
        frame_mode = request.args.get("__rd_frame") == "1"
        changed = False

        def _mark_workspace_body(match):
            attrs = match.group(1) or ""
            body_class = "rd-workspace-frame" if frame_mode else "rd-workspace-active"
            if re.search(r'\bclass\s*=\s*"[^"]*"', attrs, re.I):
                attrs = re.sub(
                    r'\bclass\s*=\s*"([^"]*)"',
                    lambda class_match: 'class="%s"' % (
                        (class_match.group(1).strip() + " " + body_class).strip()
                    ),
                    attrs,
                    count=1,
                    flags=re.I,
                )
            elif re.search(r"\bclass\s*=\s*'[^']*'", attrs, re.I):
                attrs = re.sub(
                    r"\bclass\s*=\s*'([^']*)'",
                    lambda class_match: "class='%s'" % (
                        (class_match.group(1).strip() + " " + body_class).strip()
                    ),
                    attrs,
                    count=1,
                    flags=re.I,
                )
            else:
                attrs += ' class="%s"' % body_class
            return "<body%s>" % attrs

        updated_html = re.sub(r"<body(?![^>]*\brd-workspace-(?:active|frame)\b)([^>]*)>", _mark_workspace_body, html, count=1, flags=re.I)
        if updated_html != html:
            html = updated_html
            changed = True
        injection = ""
        if not frame_mode and 'id="rd-workspace-shell"' not in html:
            try:
                injection += render_template("components/workspace_shell.html").lstrip("\ufeff")
            except TemplateNotFound:
                pass
        if 'app_shell.css' in html:
            updated_html = re.sub(
                r'(href=["\'][^"\']*app_shell\.css)(?:\?[^"\']*)?(["\'])',
                r'\1?v=%s\2' % WORKSPACE_SHELL_ASSET_VERSION,
                html,
                count=0,
                flags=re.I,
            )
            if updated_html != html:
                html = updated_html
                changed = True
        else:
            head_pos = html.lower().find("</head>")
            if head_pos >= 0:
                css_link = '<link rel="stylesheet" href="%s">' % url_for('static', filename='app_shell.css', v=WORKSPACE_SHELL_ASSET_VERSION)
                html = html[:head_pos] + css_link + html[head_pos:]
                changed = True
        if "app_minimal_theme.css" not in html.lower():
            head_pos = html.lower().find("</head>")
            if head_pos >= 0:
                css_link = '<link rel="stylesheet" href="%s">' % url_for('static', filename='app_minimal_theme.css', v=MINIMAL_THEME_ASSET_VERSION)
                html = html[:head_pos] + css_link + html[head_pos:]
                changed = True
        if frame_mode:
            if 'thor_gateway.js' in html:
                updated_html = re.sub(
                    r'<script\b[^>]*src=["\'][^"\']*thor_gateway\.js(?:\?[^"\']*)?["\'][^>]*>\s*</script>',
                    '',
                    html,
                    count=0,
                    flags=re.I,
                )
                if updated_html != html:
                    html = updated_html
                    changed = True
        elif 'thor_gateway.js' in html:
            updated_html = re.sub(
                r'(src=["\'][^"\']*thor_gateway\.js)(?:\?[^"\']*)?(["\'])',
                r'\1?v=%s\2' % THOR_GATEWAY_ASSET_VERSION,
                html,
                count=0,
                flags=re.I,
            )
            if updated_html != html:
                html = updated_html
                changed = True
        else:
            injection += '<script src="%s"></script>' % url_for('static', filename='thor_gateway.js', v=THOR_GATEWAY_ASSET_VERSION)
        if frame_mode:
            if 'app_shell.js' in html:
                updated_html = re.sub(
                    r'<script\b[^>]*src=["\'][^"\']*app_shell\.js(?:\?[^"\']*)?["\'][^>]*>\s*</script>',
                    '',
                    html,
                    count=0,
                    flags=re.I,
                )
                if updated_html != html:
                    html = updated_html
                    changed = True
        elif 'app_shell.js' in html:
            updated_html = re.sub(
                r'(src=["\'][^"\']*app_shell\.js)(?:\?[^"\']*)?(["\'])',
                r'\1?v=%s\2' % WORKSPACE_SHELL_ASSET_VERSION,
                html,
                count=0,
                flags=re.I,
            )
            if updated_html != html:
                html = updated_html
                changed = True
        else:
            injection += '<script src="%s"></script>' % url_for('static', filename='app_shell.js', v=WORKSPACE_SHELL_ASSET_VERSION)
        if frame_mode:
            if 'thor_frame_bridge.js' in html:
                updated_html = re.sub(
                    r'(src=["\'][^"\']*thor_frame_bridge\.js)(?:\?[^"\']*)?(["\'])',
                    r'\1?v=%s\2' % THOR_FRAME_BRIDGE_ASSET_VERSION,
                    html,
                    count=0,
                    flags=re.I,
                )
                if updated_html != html:
                    html = updated_html
                    changed = True
            else:
                injection += '<script src="%s"></script>' % url_for('static', filename='thor_frame_bridge.js', v=THOR_FRAME_BRIDGE_ASSET_VERSION)
        if not injection and not changed:
            return response
        pos = html.lower().rfind("</body>")
        if pos < 0:
            return response
        html = html[:pos] + injection + html[pos:]
        response.set_data(html)
        response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception as e:
        logging.warning("inject global workspace panels failed: %s", e, exc_info=True)
    return response


@app.after_request
def inject_thor_command_panel(response):
    """Backward-compatible no-op; Thor is now provided by static/thor_gateway.js."""
    return response


@app.after_request
def apply_production_response_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if CSP_ENABLED and "Content-Security-Policy" not in response.headers:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://cdn.plot.ly https://cdn.quilljs.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdn.quilljs.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
            "worker-src 'self' blob: https://cdnjs.cloudflare.com; "
            "frame-src 'self' blob:; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'self'; "
            "form-action 'self'"
        )
    request_id = getattr(g, "request_id", None)
    if request_id:
        response.headers.setdefault("X-Request-ID", request_id)
    if _env_bool("APP_HSTS", False) and request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return _record_metric(response)
