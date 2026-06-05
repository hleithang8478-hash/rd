# -*- coding: utf-8 -*-
from app_modules.services.stock_master_cache import get_all_stock_master, search_stock_master
# AUTO-SPLIT from legacy app.py lines 13099-14819.
# Section: data query builder, SQL templates, query execution, table recognition.
# Loaded by root app.py; keep project-root paths based on root app.py.

# ==================== 数据查询构建器功能 ====================
# 数据表配置页面
@app.route('/data_query_config')
@login_required
def data_query_config():
    return render_template('data_query_config.html')

# 数据查询页面
@app.route('/data_query')
@app.route('/data_query_builder')
@login_required
def data_query_builder():
    return render_template('data_query.html')

# 获取所有数据表配置
@app.route('/api/data_query/tables')
@login_required
def get_table_configs():
    try:
        owner_id = current_user_id_required()
        # 使用明确的列名查询，避免字段顺序问题
        tables = query_db("""
            SELECT id, table_name, table_display_name, description, primary_key_field, 
                   date_field, code_field, name_field, join_type, join_field, created_at, updated_at
            FROM data_table_configs 
            WHERE owner_user_id=?
            ORDER BY created_at DESC
        """, (owner_id,))
        result = []
        for table in tables:
            # 使用明确的索引，确保字段对应正确
            # 表结构：id(0), table_name(1), table_display_name(2), description(3), 
            #         primary_key_field(4), date_field(5), code_field(6), name_field(7), 
            #         join_type(8), join_field(9), created_at(10), updated_at(11)
            join_type = table[8] if len(table) > 8 and table[8] else 'CompanyCode'
            join_field = table[9] if len(table) > 9 and table[9] else ''
            
            # 确保join_type和join_field是字符串
            if join_type:
                join_type = str(join_type).strip()
            else:
                join_type = 'CompanyCode'
            
            if join_field:
                join_field = str(join_field).strip()
            else:
                join_field = ''
            
            result.append({
                'id': table[0],
                'table_name': table[1],
                'table_display_name': table[2],
                'description': table[3] if len(table) > 3 else '',
                'primary_key_field': table[4] if len(table) > 4 else '',
                'date_field': table[5] if len(table) > 5 else '',
                'code_field': table[6] if len(table) > 6 else '',
                'name_field': table[7] if len(table) > 7 else '',
                'join_type': join_type,
                'join_field': join_field
            })
        return jsonify({'success': True, 'tables': result})
    except Exception as e:
        logging.error(f"获取数据表配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 保存数据表配置
@app.route('/api/data_query/tables', methods=['POST'])
@login_required
def save_table_config():
    try:
        owner_id = current_user_id_required()
        data = request.get_json() or {}
        table_id = data.get('id')
        table_name = data.get('table_name', '').strip()
        table_display_name = data.get('table_display_name', '').strip()
        description = data.get('description', '')
        primary_key_field = data.get('primary_key_field', '')
        date_field = data.get('date_field', '')
        code_field = data.get('code_field', '')
        name_field = data.get('name_field', '')
        
        if not table_name or not table_display_name:
            return jsonify({'success': False, 'error': '表名和显示名称不能为空'})
        
        join_type = data.get('join_type', 'CompanyCode')  # InnerCode 或 CompanyCode
        join_field = data.get('join_field', '').strip()  # 关联字段名
        
        # 验证关联字段配置
        if not join_field:
            return jsonify({'success': False, 'error': '关联字段名不能为空，这是与SecuMain关联的关键字段'})
        
        try:
            table_name = _safe_sql_table_name(table_name, "表名")
            primary_key_field = _safe_optional_sql_identifier(primary_key_field, "主键字段")
            date_field = _safe_optional_sql_identifier(date_field, "日期字段")
            code_field = _safe_optional_sql_identifier(code_field, "代码字段")
            name_field = _safe_optional_sql_identifier(name_field, "名称字段")
            join_field = _safe_sql_identifier(join_field, "关联字段名")
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)})
        
        # 验证join_type和join_field的匹配性（给出提示但不强制）
        if join_type == 'InnerCode' and 'company' in join_field.lower() and 'inner' not in join_field.lower():
            logging.warning(f"表 {table_name} 的关联方式设置为InnerCode，但关联字段名 '{join_field}' 看起来像是CompanyCode字段，请确认配置是否正确")
        elif join_type == 'CompanyCode' and 'inner' in join_field.lower() and 'company' not in join_field.lower():
            logging.warning(f"表 {table_name} 的关联方式设置为CompanyCode，但关联字段名 '{join_field}' 看起来像是InnerCode字段，请确认配置是否正确")
        
        if table_id:
            # 更新
            update_db("""UPDATE data_table_configs SET 
                        table_name = ?, table_display_name = ?, description = ?,
                        primary_key_field = ?, date_field = ?, code_field = ?, name_field = ?,
                        join_type = ?, join_field = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE owner_user_id=? AND id = ?""",
                     (table_name, table_display_name, description, primary_key_field,
                      date_field, code_field, name_field, join_type, join_field, owner_id, table_id))
            return jsonify({'success': True, 'id': table_id})
        else:
            # 新增
            insert_db("""INSERT INTO data_table_configs 
                        (table_name, table_display_name, description, primary_key_field,
                         date_field, code_field, name_field, join_type, join_field, owner_user_id) 
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (table_name, table_display_name, description, primary_key_field,
                      date_field, code_field, name_field, join_type, join_field, owner_id))
            new_table = query_db(
                "SELECT id FROM data_table_configs WHERE owner_user_id=? AND table_name = ? ORDER BY created_at DESC LIMIT 1",
                (owner_id, table_name),
                one=True,
            )
            return jsonify({'success': True, 'id': new_table[0] if new_table else None})
    except Exception as e:
        logging.error(f"保存数据表配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 删除数据表配置
@app.route('/api/data_query/tables/<int:table_id>', methods=['DELETE'])
@login_required
def delete_table_config(table_id):
    try:
        owner_id = current_user_id_required()
        delete_db("DELETE FROM data_field_configs WHERE owner_user_id=? AND table_config_id = ?", (owner_id, table_id))
        delete_db("DELETE FROM data_table_configs WHERE owner_user_id=? AND id = ?", (owner_id, table_id))
        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"删除数据表配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 获取数据表的字段配置
@app.route('/api/data_query/tables/<int:table_id>/fields')
@login_required
def get_table_fields(table_id):
    try:
        owner_id = current_user_id_required()
        fields = query_db("""SELECT * FROM data_field_configs 
                            WHERE owner_user_id=? AND table_config_id = ? 
                            ORDER BY order_index, id""", (owner_id, table_id))
        result = []
        for field in fields:
            result.append({
                'id': field[0],
                'table_config_id': field[1],
                'field_name': field[2],
                'field_display_name': field[3],
                'field_type': field[4],
                'description': field[5],
                'is_sortable': bool(field[6]),
                'is_filterable': bool(field[7]),
                'order_index': field[8]
            })
        return jsonify({'success': True, 'fields': result})
    except Exception as e:
        logging.error(f"获取字段配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 保存字段配置
@app.route('/api/data_query/fields', methods=['POST'])
@login_required
def save_field_config():
    try:
        owner_id = current_user_id_required()
        data = request.get_json()
        field_id = data.get('id')
        table_config_id = data.get('table_config_id')
        field_name = data.get('field_name', '').strip()
        field_display_name = data.get('field_display_name', '').strip()
        field_type = data.get('field_type', 'TEXT')
        description = data.get('description', '')
        is_sortable = 1 if data.get('is_sortable', True) else 0
        is_filterable = 1 if data.get('is_filterable', True) else 0
        order_index = data.get('order_index', 0)
        
        if not table_config_id or not field_name or not field_display_name:
            return jsonify({'success': False, 'error': '表配置ID、字段名和显示名称不能为空'})
        table_exists = query_db(
            "SELECT 1 FROM data_table_configs WHERE owner_user_id=? AND id=?",
            (owner_id, table_config_id),
            one=True,
        )
        if not table_exists:
            return jsonify({'success': False, 'error': '表配置不存在'})
        try:
            field_name = _safe_sql_identifier(field_name, "字段名")
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)})
        
        if field_id:
            # 更新
            update_db("""UPDATE data_field_configs SET 
                        field_name = ?, field_display_name = ?, field_type = ?, description = ?,
                        is_sortable = ?, is_filterable = ?, order_index = ?
                        WHERE owner_user_id=? AND id = ?""",
                     (field_name, field_display_name, field_type, description,
                      is_sortable, is_filterable, order_index, owner_id, field_id))
            return jsonify({'success': True, 'id': field_id})
        else:
            # 新增
            insert_db("""INSERT INTO data_field_configs 
                        (table_config_id, field_name, field_display_name, field_type, description,
                         is_sortable, is_filterable, order_index, owner_user_id) 
                        VALUES (?,?,?,?,?,?,?,?,?)""",
                     (table_config_id, field_name, field_display_name, field_type, description,
                      is_sortable, is_filterable, order_index, owner_id))
            new_field = query_db("""SELECT id FROM data_field_configs 
                                   WHERE owner_user_id=? AND table_config_id = ? AND field_name = ? 
                                   ORDER BY created_at DESC LIMIT 1""",
                                (owner_id, table_config_id, field_name), one=True)
            return jsonify({'success': True, 'id': new_field[0] if new_field else None})
    except Exception as e:
        logging.error(f"保存字段配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 验证字段是否存在
@app.route('/api/data_query/validate_fields', methods=['POST'])
@login_required
def validate_fields():
    """验证字段是否在数据库表中存在"""
    try:
        data = request.get_json()
        table_name = data.get('table_name', '').strip()
        field_names = data.get('field_names', [])  # 字段名列表
        
        if not table_name:
            return jsonify({'success': False, 'error': '表名不能为空'})
        
        if not field_names:
            return jsonify({'success': True, 'valid_fields': [], 'invalid_fields': []})
        try:
            table_name = _safe_sql_table_name(table_name, "表名")
            field_names = [_safe_sql_identifier(field_name, "字段名") for field_name in field_names]
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)})
        
        try:
            from data_fetcher import JuyuanDataFetcher
            fetcher = JuyuanDataFetcher(lazy_init_pool=True)
            
            # 查询表的结构（列名）
            # SQL Server 查询列名的方法
            table_leaf = table_name.split(".")[-1]
            sql = """
            SELECT COLUMN_NAME 
            FROM INFORMATION_SCHEMA.COLUMNS 
            WHERE TABLE_NAME = ?
            """
            
            try:
                df = fetcher.query(sql, (table_leaf,))
                if df.empty:
                    return jsonify({
                        'success': False,
                        'error': f'表 "{table_name}" 不存在或无法访问'
                    })
                
                # 获取所有有效的列名
                valid_columns = set(df['COLUMN_NAME'].str.strip().str.upper().tolist())
                
                # 验证每个字段名
                valid_fields = []
                invalid_fields = []
                
                for field_name in field_names:
                    field_upper = field_name.strip().upper()
                    if field_upper in valid_columns:
                        valid_fields.append(field_name)
                    else:
                        invalid_fields.append(field_name)
                
                return jsonify({
                    'success': True,
                    'valid_fields': valid_fields,
                    'invalid_fields': invalid_fields,
                    'all_columns': list(valid_columns)  # 返回所有有效列名，供参考
                })
            except Exception as e:
                logging.error(f"查询表结构失败: {e}", exc_info=True)
                # 如果查询失败，尝试另一种方法：SELECT TOP 1 来验证表是否存在
                try:
                    test_sql = f"SELECT TOP 1 * FROM {_quote_sql_table_name(table_name)}"
                    fetcher.query(test_sql)
                    # 如果执行成功但无法获取列信息，返回部分成功
                    return jsonify({
                        'success': True,
                        'valid_fields': [],
                        'invalid_fields': field_names,
                        'warning': '无法获取表结构信息，请手动验证字段名',
                        'all_columns': []
                    })
                except Exception as query_err:
                    return jsonify({
                        'success': False,
                        'error': f'表 "{table_name}" 不存在或无法访问: {str(query_err)}'
                    })
        except ImportError:
            return jsonify({
                'success': False,
                'error': '数据库连接模块未找到'
            })
            
    except Exception as e:
        logging.error(f"验证字段失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 删除字段配置
@app.route('/api/data_query/fields/<int:field_id>', methods=['DELETE'])
@login_required
def delete_field_config(field_id):
    try:
        owner_id = current_user_id_required()
        delete_db("DELETE FROM data_field_configs WHERE owner_user_id=? AND id = ?", (owner_id, field_id))
        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"删除字段配置失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/data_query/bootstrap_presets', methods=['POST'])
@login_required
def bootstrap_data_query_presets():
    try:
        owner_id = current_user_id_required()
        table_created = 0
        table_updated = 0
        field_count = 0
        template_created = 0
        template_updated = 0

        for preset in DATA_QUERY_PRESET_TABLES:
            result = _upsert_preset_table(owner_id, preset)
            if result["created"]:
                table_created += 1
            else:
                table_updated += 1
            field_count += result["field_count"]

        for preset in DATA_QUERY_PRESET_TEMPLATES:
            result = _upsert_preset_template(owner_id, preset)
            if result["created"]:
                template_created += 1
            else:
                template_updated += 1

        return jsonify({
            'success': True,
            'table_created': table_created,
            'table_updated': table_updated,
            'field_count': field_count,
            'template_created': template_created,
            'template_updated': template_updated,
            'message': (
                f"已初始化 {table_created} 张表、更新 {table_updated} 张表，"
                f"维护 {field_count} 个字段，新增 {template_created} 个模板、更新 {template_updated} 个模板。"
            )
        })
    except Exception as e:
        logging.error(f"初始化数据查询预设失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 获取所有股票列表（用于缓存，每天更新一次）
@app.route('/api/data_query/all_stocks', methods=['GET'])
@login_required
def get_all_stocks():
    """获取所有符合条件的股票列表（用于客户端缓存）"""
    try:
        refresh = str(request.args.get('refresh') or '').strip().lower() in ('1', 'true', 'yes')
        result = get_all_stock_master(get_sqlite_connection, refresh=refresh, refresh_if_stale=True)
        stocks_list = result.get('stocks') or []
        logging.info(
            "return all stock list count=%s source=%s refreshed_at=%s",
            len(stocks_list),
            result.get('source') or 'cache',
            (result.get('cache') or {}).get('full_refreshed_at') or '',
        )
        return jsonify({
            'success': True,
            'stocks': stocks_list,
            'count': len(stocks_list),
            'source': result.get('source') or 'cache',
            'cache': result.get('cache') or {},
            'refresh_error': result.get('refresh_error') or ''
        })
        try:
            limit = int(data.get('limit') or 50)
        except (TypeError, ValueError):
            limit = 50
        fallback_juyuan = str(data.get('cache_only') or '').strip().lower() not in ('1', 'true', 'yes')
        result = search_stock_master(
            get_sqlite_connection,
            query,
            limit=limit,
            fallback_juyuan=fallback_juyuan,
            warm_if_empty=True,
        )
        return jsonify({
            'success': True,
            'stocks': result.get('stocks') or [],
            'source': result.get('source') or 'cache',
            'cache_hit': bool(result.get('cache_hit')),
            'cache': result.get('cache') or {},
            'warning': result.get('error') or ''
        })

        from industry_inventory_module import get_module
        from juyuan_config import STOCK_FILTER
        from data_fetcher import JuyuanDataFetcher
        
        fetcher = JuyuanDataFetcher(lazy_init_pool=True)
        
        # 获取所有符合条件的股票（应用与筛选任务相同的筛选条件）
        sql = f"""
        SELECT DISTINCT 
            s.SecuCode,
            s.SecuAbbr,
            s.CompanyCode,
            i.ThirdIndustryName,
            i.SecondIndustryName,
            i.FirstIndustryName
        FROM SecuMain s
        LEFT JOIN LC_ExgIndustry i ON s.CompanyCode = i.CompanyCode
            AND i.Standard = '38'
            AND i.IfPerformed = 1
        WHERE s.SecuCategory = 1
        AND ({STOCK_FILTER})
        AND s.SecuCode NOT LIKE 'X%'
        ORDER BY s.SecuCode
        """
        
        df = fetcher.query(sql)
        
        stocks_list = []
        for _, row in df.iterrows():
            stocks_list.append({
                'code': str(row.get('SecuCode', '')).zfill(6),
                'name': row.get('SecuAbbr', ''),
                'company_code': int(row.get('CompanyCode', 0)),
                'third_industry': row.get('ThirdIndustryName', ''),
                'second_industry': row.get('SecondIndustryName', ''),
                'first_industry': row.get('FirstIndustryName', '')
            })
        
        logging.info(f"返回所有股票列表，共 {len(stocks_list)} 只")
        
        return jsonify({
            'success': True,
            'stocks': stocks_list,
            'count': len(stocks_list)
        })
    except Exception as e:
        logging.error(f"获取所有股票列表失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 搜索股票（用于查询构建器）
@app.route('/api/data_query/search_stock', methods=['POST'])
@login_required
def search_stock_for_query():
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        
        if not query:
            return jsonify({'success': False, 'error': '请输入搜索关键词'})
        
        from industry_inventory_module import get_module
        module = get_module()
        stocks = module.get_stock_list_by_code_or_name(query)
        
        return jsonify({
            'success': True,
            'stocks': stocks
        })
    except Exception as e:
        logging.error(f"搜索股票失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})


SQL_IDENTIFIER_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
DATA_QUERY_MAX_ROWS = _env_int("DATA_QUERY_MAX_ROWS", 10000, min_value=100, max_value=50000)
DATA_QUERY_MAX_STOCK_CODES = _env_int("DATA_QUERY_MAX_STOCK_CODES", 500, min_value=1, max_value=5000)
DATA_QUERY_MAX_TABLES = _env_int("DATA_QUERY_MAX_TABLES", 8, min_value=1, max_value=50)
DATA_QUERY_MAX_FIELDS = _env_int("DATA_QUERY_MAX_FIELDS", 80, min_value=1, max_value=300)
DATA_QUERY_TEMPLATE_MAX_LENGTH = _env_int("DATA_QUERY_TEMPLATE_MAX_LENGTH", 20000, min_value=1000, max_value=100000)
STOCK_CODE_RE = re.compile(r'^(\d{6})(?:\.(?:SH|SZ|SS|BJ))?$', re.I)

DATA_QUERY_PRESET_TABLES = [
    {
        "table_name": "SecuMain",
        "table_display_name": "证券主表",
        "description": "股票代码、简称、上市日期和公司代码，是其他表的主轴。",
        "primary_key_field": "InnerCode",
        "date_field": "ListedDate",
        "code_field": "SecuCode",
        "name_field": "SecuAbbr",
        "join_type": "InnerCode",
        "join_field": "InnerCode",
        "fields": [
            ("SecuCode", "股票代码", "TEXT", "A股六位代码", 1),
            ("SecuAbbr", "股票简称", "TEXT", "证券简称", 2),
            ("ListedDate", "上市日期", "DATE", "上市日期", 3),
            ("SecuMarket", "交易市场", "TEXT", "市场标识", 4),
            ("ListedSector", "上市板块", "TEXT", "板块信息", 5),
            ("CompanyCode", "公司代码", "INTEGER", "公司维度关联字段", 6),
            ("InnerCode", "内部代码", "INTEGER", "证券维度关联字段", 7),
        ],
    },
    {
        "table_name": "QT_StockPerformance",
        "table_display_name": "日行情与成交",
        "description": "日线价格、成交量、换手率和流通市值，适合做走势复盘。",
        "primary_key_field": "ID",
        "date_field": "TradingDay",
        "code_field": "InnerCode",
        "name_field": "",
        "join_type": "InnerCode",
        "join_field": "InnerCode",
        "fields": [
            ("TradingDay", "交易日", "DATE", "行情日期", 1),
            ("OpenPrice", "开盘价", "NUMBER", "开盘价", 2),
            ("HighPrice", "最高价", "NUMBER", "最高价", 3),
            ("LowPrice", "最低价", "NUMBER", "最低价", 4),
            ("ClosePrice", "收盘价", "NUMBER", "收盘价", 5),
            ("TurnoverVolume", "成交量", "NUMBER", "成交量", 6),
            ("TurnoverRate", "换手率", "NUMBER", "换手率", 7),
            ("NegotiableMV", "流通市值", "NUMBER", "流通市值", 8),
        ],
    },
    {
        "table_name": "DZ_DIndicesForValuation",
        "table_display_name": "估值指标",
        "description": "PB、PE 等估值指标，用来快速判断估值位置。",
        "primary_key_field": "ID",
        "date_field": "TradingDay",
        "code_field": "InnerCode",
        "name_field": "",
        "join_type": "InnerCode",
        "join_field": "InnerCode",
        "fields": [
            ("TradingDay", "交易日", "DATE", "估值日期", 1),
            ("PB", "PB", "NUMBER", "市净率", 2),
            ("PETTMCut", "PE_TTM", "NUMBER", "滚动市盈率", 3),
            ("PCFOperatingTTM", "经营现金流市值比", "NUMBER", "现金流估值", 4),
        ],
    },
    {
        "table_name": "LC_MainIndexNew",
        "table_display_name": "财务核心指标",
        "description": "ROE、每股分红等财务指标，适合做质量筛选。",
        "primary_key_field": "ID",
        "date_field": "EndDate",
        "code_field": "CompanyCode",
        "name_field": "",
        "join_type": "CompanyCode",
        "join_field": "CompanyCode",
        "fields": [
            ("EndDate", "报告期", "DATE", "财报报告期", 1),
            ("ROETTM", "ROE_TTM", "NUMBER", "滚动净资产收益率", 2),
            ("DividendPS", "每股分红", "NUMBER", "每股分红", 3),
            ("DividendPaidRatio", "分红支付率", "NUMBER", "分红支付率", 4),
        ],
    },
]

DATA_QUERY_PRESET_TEMPLATES = [
    {
        "template_name": "最近行情快照",
        "description": "输入股票代码和日期区间，直接查看价格、换手率和流通市值。支持 {STOCK_CODES}/{START_DATE}/{END_DATE}。",
        "sql_template": """
SELECT
    s.SecuCode AS 股票代码,
    s.SecuAbbr AS 股票名称,
    q.TradingDay AS 交易日,
    q.OpenPrice AS 开盘价,
    q.HighPrice AS 最高价,
    q.LowPrice AS 最低价,
    q.ClosePrice AS 收盘价,
    q.TurnoverRate AS 换手率,
    q.NegotiableMV AS 流通市值
FROM QT_StockPerformance q
INNER JOIN SecuMain s ON q.InnerCode = s.InnerCode AND s.SecuCategory = 1
WHERE s.SecuCode IN ({STOCK_CODES})
  AND q.TradingDay >= '{START_DATE}'
  AND q.TradingDay <= '{END_DATE}'
ORDER BY s.SecuCode, q.TradingDay DESC
""".strip(),
    },
    {
        "template_name": "最新估值与ROE",
        "description": "把最新估值和最新财务质量指标拼到一张表，适合快速看便宜不便宜、好不好。",
        "sql_template": """
WITH latest_val AS (
    SELECT InnerCode, MAX(TradingDay) AS TradingDay
    FROM DZ_DIndicesForValuation
    WHERE TradingDay <= '{END_DATE}'
    GROUP BY InnerCode
),
latest_fin AS (
    SELECT CompanyCode, MAX(EndDate) AS EndDate
    FROM LC_MainIndexNew
    WHERE EndDate <= '{END_DATE}'
    GROUP BY CompanyCode
)
SELECT
    s.SecuCode AS 股票代码,
    s.SecuAbbr AS 股票名称,
    v.TradingDay AS 估值日期,
    v.PB AS PB,
    v.PETTMCut AS PE_TTM,
    f.EndDate AS 财报期,
    f.ROETTM AS ROE_TTM,
    f.DividendPS AS 每股分红,
    f.DividendPaidRatio AS 分红支付率
FROM SecuMain s
LEFT JOIN latest_val lv ON s.InnerCode = lv.InnerCode
LEFT JOIN DZ_DIndicesForValuation v ON v.InnerCode = lv.InnerCode AND v.TradingDay = lv.TradingDay
LEFT JOIN latest_fin lf ON s.CompanyCode = lf.CompanyCode
LEFT JOIN LC_MainIndexNew f ON f.CompanyCode = lf.CompanyCode AND f.EndDate = lf.EndDate
WHERE s.SecuCode IN ({STOCK_CODES})
  AND s.SecuCategory = 1
ORDER BY s.SecuCode
""".strip(),
    },
    {
        "template_name": "区间涨跌幅排行",
        "description": "按输入区间计算首末收盘价和区间涨跌幅，适合比较一组股票谁更强。",
        "sql_template": """
WITH base AS (
    SELECT
        s.SecuCode,
        s.SecuAbbr,
        q.TradingDay,
        q.ClosePrice,
        ROW_NUMBER() OVER (PARTITION BY s.SecuCode ORDER BY q.TradingDay ASC) AS rn_asc,
        ROW_NUMBER() OVER (PARTITION BY s.SecuCode ORDER BY q.TradingDay DESC) AS rn_desc
    FROM QT_StockPerformance q
    INNER JOIN SecuMain s ON q.InnerCode = s.InnerCode AND s.SecuCategory = 1
    WHERE s.SecuCode IN ({STOCK_CODES})
      AND q.TradingDay >= '{START_DATE}'
      AND q.TradingDay <= '{END_DATE}'
),
pivoted AS (
    SELECT
        SecuCode,
        MAX(SecuAbbr) AS SecuAbbr,
        MAX(CASE WHEN rn_asc = 1 THEN ClosePrice END) AS 起始收盘,
        MAX(CASE WHEN rn_desc = 1 THEN ClosePrice END) AS 结束收盘,
        MAX(CASE WHEN rn_desc = 1 THEN TradingDay END) AS 最新交易日
    FROM base
    GROUP BY SecuCode
)
SELECT
    SecuCode AS 股票代码,
    SecuAbbr AS 股票名称,
    最新交易日,
    起始收盘,
    结束收盘,
    CASE WHEN 起始收盘 IS NULL OR 起始收盘 = 0 THEN NULL ELSE (结束收盘 - 起始收盘) / 起始收盘 END AS 区间涨跌幅
FROM pivoted
ORDER BY 区间涨跌幅 DESC
""".strip(),
    },
]


def _safe_sql_identifier(value, label="字段名"):
    value = (value or "").strip()
    if not value or not SQL_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f'{label}格式无效: "{value}"')
    return value


def _quote_sql_identifier(value, label="字段名"):
    return f"[{_safe_sql_identifier(value, label)}]"


def _safe_sql_table_name(value, label="表名"):
    value = (value or "").strip()
    parts = value.split(".")
    if not parts or any(not SQL_IDENTIFIER_RE.fullmatch(part) for part in parts):
        raise ValueError(f'{label}格式无效: "{value}"')
    if len(parts) > 2:
        raise ValueError(f'{label}最多支持 schema.table 两段格式')
    return ".".join(parts)


def _quote_sql_table_name(value, label="表名"):
    return ".".join(_quote_sql_identifier(part, label) for part in _safe_sql_table_name(value, label).split("."))


def _safe_optional_sql_identifier(value, label="字段名"):
    value = (value or "").strip()
    if not value:
        return ""
    return _safe_sql_identifier(value, label)


def _quote_sql_alias(value):
    value = re.sub(r"[\[\]\x00-\x1f]", "_", str(value or "")).strip()
    if not value:
        value = "column"
    return f"[{value[:128]}]"


def _normalize_int_list(values, label="ID列表", max_items=DATA_QUERY_MAX_FIELDS):
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{label}必须是列表")
    result = []
    seen = set()
    for raw in values:
        try:
            item = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{label}包含无效ID")
        if item <= 0:
            raise ValueError(f"{label}包含无效ID")
        if item not in seen:
            seen.add(item)
            result.append(item)
        if len(result) > max_items:
            raise ValueError(f"{label}最多支持{max_items}项")
    return result


def _normalize_stock_codes(values, max_items=DATA_QUERY_MAX_STOCK_CODES):
    if not values:
        return []
    if not isinstance(values, (list, tuple)):
        raise ValueError("股票代码必须是列表")
    result = []
    seen = set()
    for raw in values:
        text = str(raw or "").strip().upper()
        if not text:
            continue
        match = STOCK_CODE_RE.fullmatch(text)
        if not match:
            raise ValueError(f'股票代码格式无效: "{text}"')
        code = match.group(1)
        if code not in seen:
            seen.add(code)
            result.append(code)
        if len(result) > max_items:
            raise ValueError(f"股票代码最多支持{max_items}只")
    return result


def _normalize_date_range(value):
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("日期范围格式无效")
    result = {}
    for key in ("start", "end"):
        raw = (value.get(key) or "").strip()
        if not raw:
            continue
        try:
            datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"日期格式无效: {raw}")
        result[key] = raw
    if result.get("start") and result.get("end") and result["start"] > result["end"]:
        raise ValueError("开始日期不能晚于结束日期")
    return result


def _template_literal(value: str) -> str:
    return str(value).replace("'", "''")


def _apply_template_parameters(sql_template: str, stock_codes, date_range):
    placeholders = set(re.findall(r"\{([A-Z_]+)\}", sql_template or ""))
    today_text = datetime.now().strftime("%Y-%m-%d")
    start_date = date_range.get("start") or "1900-01-01"
    end_date = date_range.get("end") or today_text

    if "STOCK_CODES" in placeholders and not stock_codes:
        raise ValueError("该模板需要股票代码，请在模板参数里输入至少一只股票")

    stock_literal = ", ".join(f"'{_template_literal(code)}'" for code in stock_codes) if stock_codes else "''"
    replacements = {
        "STOCK_CODES": stock_literal,
        "START_DATE": _template_literal(start_date),
        "END_DATE": _template_literal(end_date),
        "TOP": str(DATA_QUERY_MAX_ROWS),
    }

    final_sql = sql_template
    for key, value in replacements.items():
        final_sql = final_sql.replace("{" + key + "}", value)

    leftovers = sorted(set(re.findall(r"\{([A-Z_]+)\}", final_sql)))
    if leftovers:
        raise ValueError(f"模板包含暂不支持的占位符: {', '.join(leftovers)}")
    return final_sql


def _find_owned_table(owner_id, table_name):
    return query_db(
        "SELECT id FROM data_table_configs WHERE owner_user_id=? AND table_name=? ORDER BY id DESC LIMIT 1",
        (owner_id, table_name),
        one=True,
    )


def _upsert_preset_table(owner_id, preset):
    existing = _find_owned_table(owner_id, preset["table_name"])
    if existing:
        table_id = existing[0]
        update_db(
            """UPDATE data_table_configs SET
               table_display_name=?, description=?, primary_key_field=?, date_field=?,
               code_field=?, name_field=?, join_type=?, join_field=?, updated_at=CURRENT_TIMESTAMP
               WHERE owner_user_id=? AND id=?""",
            (
                preset["table_display_name"],
                preset["description"],
                preset["primary_key_field"],
                preset["date_field"],
                preset["code_field"],
                preset["name_field"],
                preset["join_type"],
                preset["join_field"],
                owner_id,
                table_id,
            ),
        )
        created = False
    else:
        insert_db(
            """INSERT INTO data_table_configs
               (table_name, table_display_name, description, primary_key_field, date_field,
                code_field, name_field, join_type, join_field, owner_user_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                preset["table_name"],
                preset["table_display_name"],
                preset["description"],
                preset["primary_key_field"],
                preset["date_field"],
                preset["code_field"],
                preset["name_field"],
                preset["join_type"],
                preset["join_field"],
                owner_id,
            ),
        )
        row = _find_owned_table(owner_id, preset["table_name"])
        table_id = row[0] if row else None
        created = True

    if not table_id:
        raise RuntimeError(f"初始化数据表失败: {preset['table_name']}")

    field_count = 0
    for field_name, display_name, field_type, description, order_index in preset.get("fields", []):
        existing_field = query_db(
            """SELECT id FROM data_field_configs
               WHERE owner_user_id=? AND table_config_id=? AND field_name=?
               ORDER BY id DESC LIMIT 1""",
            (owner_id, table_id, field_name),
            one=True,
        )
        if existing_field:
            update_db(
                """UPDATE data_field_configs SET
                   field_display_name=?, field_type=?, description=?, is_sortable=1, is_filterable=1,
                   order_index=?
                   WHERE owner_user_id=? AND id=?""",
                (display_name, field_type, description, order_index, owner_id, existing_field[0]),
            )
        else:
            insert_db(
                """INSERT INTO data_field_configs
                   (table_config_id, field_name, field_display_name, field_type, description,
                    is_sortable, is_filterable, order_index, owner_user_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (table_id, field_name, display_name, field_type, description, 1, 1, order_index, owner_id),
            )
        field_count += 1

    return {"created": created, "table_id": table_id, "field_count": field_count}


def _upsert_preset_template(owner_id, preset):
    existing = query_db(
        "SELECT id FROM sql_query_templates WHERE owner_user_id=? AND template_name=? ORDER BY id DESC LIMIT 1",
        (owner_id, preset["template_name"]),
        one=True,
    )
    if existing:
        update_db(
            """UPDATE sql_query_templates SET sql_template=?, description=?, updated_at=CURRENT_TIMESTAMP
               WHERE owner_user_id=? AND id=?""",
            (preset["sql_template"], preset["description"], owner_id, existing[0]),
        )
        return {"created": False, "template_id": existing[0]}

    insert_db(
        """INSERT INTO sql_query_templates (template_name, sql_template, description, owner_user_id)
           VALUES (?,?,?,?)""",
        (preset["template_name"], preset["sql_template"], preset["description"], owner_id),
    )
    row = query_db(
        "SELECT id FROM sql_query_templates WHERE owner_user_id=? AND template_name=? ORDER BY id DESC LIMIT 1",
        (owner_id, preset["template_name"]),
        one=True,
    )
    return {"created": True, "template_id": row[0] if row else None}


def _normalize_join_type(value):
    text = str(value or "CompanyCode").strip().lower()
    if text == "innercode":
        return "InnerCode"
    if text == "companycode":
        return "CompanyCode"
    raise ValueError("关联方式只支持 CompanyCode 或 InnerCode")


def _join_target_field(join_type):
    return "InnerCode" if str(join_type or "").strip().lower() == "innercode" else "CompanyCode"


def _validate_readonly_select_sql(sql):
    sql_clean = (sql or "").strip()
    if not sql_clean:
        raise ValueError("SQL不能为空")
    if len(sql_clean) > DATA_QUERY_TEMPLATE_MAX_LENGTH:
        raise ValueError(f"SQL模板不能超过{DATA_QUERY_TEMPLATE_MAX_LENGTH}字符")
    lowered = re.sub(r"/\*.*?\*/", " ", sql_clean, flags=re.S).lower()
    lowered = re.sub(r"--.*?$", " ", lowered, flags=re.M).strip()
    lowered_comment_elided = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.S).lower()
    lowered_comment_elided = re.sub(r"--.*?$", "", lowered_comment_elided, flags=re.M).strip()
    lowered_normalized = re.sub(r"\s+", " ", lowered)
    lowered_elided_normalized = re.sub(r"\s+", " ", lowered_comment_elided)
    if ";" in lowered_normalized:
        raise ValueError("SQL模板只允许单条SELECT查询，不能包含分号")
    if not re.match(r"^(select|with)\b", lowered_normalized):
        raise ValueError("SQL模板只允许SELECT/CTE只读查询")
    forbidden = (
        " insert ", " update ", " delete ", " merge ", " drop ", " alter ", " create ",
        " truncate ", " exec ", " execute ", " xp_", " sp_", " grant ", " revoke ",
        " into ", " openrowset ", " opendatasource ", " bulk ", " waitfor ",
        " backup ", " restore ", " shutdown ",
    )
    haystacks = (f" {lowered_normalized} ", f" {lowered_elided_normalized} ")
    if any(token in haystack for haystack in haystacks for token in forbidden):
        raise ValueError("SQL模板包含非只读或高风险关键字")
    return sql_clean


def _find_top_level_keyword(sql, keyword, start=0):
    keyword_l = keyword.lower()
    depth = 0
    quote = None
    bracket = False
    i = start
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""

        if quote:
            if ch == quote:
                if nxt == quote:
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if bracket:
            if ch == "]":
                bracket = False
            i += 1
            continue

        if ch == "-" and nxt == "-":
            nl = sql.find("\n", i + 2)
            i = len(sql) if nl == -1 else nl + 1
            continue
        if ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            i = len(sql) if end == -1 else end + 2
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "[":
            bracket = True
            i += 1
            continue
        if ch == "(":
            depth += 1
            i += 1
            continue
        if ch == ")":
            depth = max(0, depth - 1)
            i += 1
            continue

        if depth == 0 and sql[i:i + len(keyword)].lower() == keyword_l:
            before = sql[i - 1] if i > 0 else " "
            after_idx = i + len(keyword)
            after = sql[after_idx] if after_idx < len(sql) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return i
        i += 1
    return -1


def _select_has_top(sql, select_pos=0):
    suffix = sql[select_pos:]
    return bool(re.match(
        r"^select\s+(?:all\s+|distinct\s+)?top\s*(?:\(\s*\d+\s*\)|\d+)(?=\s|$)",
        suffix,
        flags=re.I,
    ))


def _insert_top_in_select(sql, select_pos, limit):
    match = re.match(r"^select\s+(?:all\s+|distinct\s+)?", sql[select_pos:], flags=re.I)
    if not match:
        return sql
    insert_at = select_pos + match.end()
    return f"{sql[:insert_at]}TOP {int(limit)} {sql[insert_at:]}"


def _limit_select_sql(sql, limit):
    sql_clean = sql.strip()
    if re.match(r"^select\b", sql_clean, flags=re.I):
        if _select_has_top(sql_clean, 0):
            return sql_clean
        return _insert_top_in_select(sql_clean, 0, limit)
    if re.match(r"^with\b", sql_clean, flags=re.I):
        select_pos = _find_top_level_keyword(sql_clean, "select", start=4)
        if select_pos >= 0 and not _select_has_top(sql_clean, select_pos):
            return _insert_top_in_select(sql_clean, select_pos, limit)
    return sql_clean


# ==================== SQL模板管理功能 ====================
# 获取所有SQL模板
@app.route('/api/data_query/templates')
@login_required
def get_sql_templates():
    try:
        owner_id = current_user_id_required()
        templates = query_db("""
            SELECT id, template_name, sql_template, description, created_at, updated_at
            FROM sql_query_templates 
            WHERE owner_user_id=?
            ORDER BY created_at DESC
        """, (owner_id,))
        result = []
        for template in templates:
            result.append({
                'id': template[0],
                'template_name': template[1],
                'sql_template': template[2],
                'description': template[3] if len(template) > 3 else '',
                'created_at': template[4] if len(template) > 4 else '',
                'updated_at': template[5] if len(template) > 5 else ''
            })
        return jsonify({'success': True, 'templates': result})
    except Exception as e:
        logging.error(f"获取SQL模板失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 保存SQL模板
@app.route('/api/data_query/templates', methods=['POST'])
@login_required
def save_sql_template():
    try:
        owner_id = current_user_id_required()
        data = request.get_json()
        template_id = data.get('id')
        template_name = data.get('template_name', '').strip()
        sql_template = data.get('sql_template', '').strip()
        description = data.get('description', '').strip()
        
        if not template_name:
            return jsonify({'success': False, 'error': '模板名称不能为空'})
        
        if not sql_template:
            return jsonify({'success': False, 'error': 'SQL模板内容不能为空'})
        try:
            sql_template = _validate_readonly_select_sql(sql_template)
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)})
        
        if template_id:
            # 更新
            update_db("""UPDATE sql_query_templates SET 
                        template_name = ?, sql_template = ?, description = ?,
                        updated_at = CURRENT_TIMESTAMP WHERE owner_user_id=? AND id = ?""",
                     (template_name, sql_template, description, owner_id, template_id))
            return jsonify({'success': True, 'id': template_id})
        else:
            # 新增
            insert_db("""INSERT INTO sql_query_templates 
                        (template_name, sql_template, description, owner_user_id) 
                        VALUES (?,?,?,?)""",
                     (template_name, sql_template, description, owner_id))
            new_template = query_db(
                "SELECT id FROM sql_query_templates WHERE owner_user_id=? AND template_name = ? ORDER BY created_at DESC LIMIT 1",
                (owner_id, template_name),
                one=True,
            )
            return jsonify({'success': True, 'id': new_template[0] if new_template else None})
    except Exception as e:
        logging.error(f"保存SQL模板失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 删除SQL模板
@app.route('/api/data_query/templates/<int:template_id>', methods=['DELETE'])
@login_required
def delete_sql_template(template_id):
    try:
        owner_id = current_user_id_required()
        delete_db("DELETE FROM sql_query_templates WHERE owner_user_id=? AND id = ?", (owner_id, template_id))
        return jsonify({'success': True})
    except Exception as e:
        logging.error(f"删除SQL模板失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 执行SQL模板查询
@app.route('/api/data_query/execute_template', methods=['POST'])
@login_required
def execute_template_query():
    try:
        owner_id = current_user_id_required()
        data = request.get_json(silent=True) or {}
        template_id = data.get('template_id')
        try:
            stock_codes = _normalize_stock_codes(data.get('stock_codes', []))
            date_range = _normalize_date_range(data.get('date_range', {}))
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)})
        
        if not template_id:
            return jsonify({'success': False, 'error': '请选择SQL模板'})
        
        # 获取模板
        template = query_db("""
            SELECT id, template_name, sql_template, description
            FROM sql_query_templates WHERE owner_user_id=? AND id = ?
        """, (owner_id, template_id), one=True)
        
        if not template:
            return jsonify({'success': False, 'error': 'SQL模板不存在'})
        
        sql_template = template[2]  # sql_template
        template_name = template[1]  # template_name

        try:
            templated_sql = _apply_template_parameters(sql_template, stock_codes, date_range)
            final_sql = _limit_select_sql(_validate_readonly_select_sql(templated_sql), DATA_QUERY_MAX_ROWS)
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)})
        
        # 执行查询
        from data_fetcher import JuyuanDataFetcher
        fetcher = JuyuanDataFetcher(lazy_init_pool=True)
        
        try:
            df = fetcher.query(final_sql)
            
            if df is None or df.empty:
                return jsonify({
                    'success': True,
                    'count': 0,
                    'columns': [],
                    'data': [],
                    'sql': final_sql,
                    'template_name': template_name
                })
            
            # 转换为列表格式
            columns = df.columns.tolist()
            data = df.values.tolist()
            
            return jsonify({
                'success': True,
                'count': len(data),
                'columns': columns,
                'data': data,
                'sql': final_sql,
                'template_name': template_name
            })
        except Exception as query_error:
            logging.error(f"执行SQL模板查询失败: {query_error}", exc_info=True)
            return jsonify({
                'success': False,
                'error': f'SQL执行失败: {str(query_error)}',
                'sql': final_sql
            })
            
    except Exception as e:
        logging.error(f"执行SQL模板查询失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# ==================== 执行查询功能 ====================
# 执行多表数据查询
@app.route('/api/data_query/execute_multi', methods=['POST'])
@login_required
def execute_multi_table_query():
    try:
        owner_id = current_user_id_required()
        data = request.get_json(silent=True) or {}
        table_configs = data.get('table_configs', [])  # [{'table_id': 1, 'field_ids': [1,2,3]}, ...]
        try:
            if not isinstance(table_configs, list):
                raise ValueError("数据表配置必须是列表")
            if len(table_configs) > DATA_QUERY_MAX_TABLES:
                raise ValueError(f"最多支持{DATA_QUERY_MAX_TABLES}张表联合查询")
            stock_codes = _normalize_stock_codes(data.get('stock_codes', []))
            date_range = _normalize_date_range(data.get('date_range', {}))
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)})
        
        if not table_configs or len(table_configs) == 0:
            return jsonify({'success': False, 'error': '请至少配置一个数据表'})
        
        from data_fetcher import JuyuanDataFetcher
        fetcher = JuyuanDataFetcher(lazy_init_pool=True)
        
        all_results = []
        all_columns = []
        table_names_map = {}  # 表ID到表名的映射
        
        try:
            # 第一步：收集所有表的配置信息
            table_info_list = []
            for table_config in table_configs:
                try:
                    table_id = int(table_config.get('table_id'))
                    field_ids = _normalize_int_list(table_config.get('field_ids', []), "字段ID列表")
                except (TypeError, ValueError) as e:
                    return jsonify({'success': False, 'error': str(e)})

                if not table_id or not field_ids:
                    continue
                
                # 获取表配置
                table_config_row = query_db("""
                    SELECT id, table_name, table_display_name, description, primary_key_field, 
                           date_field, code_field, name_field, join_type, join_field, created_at, updated_at
                    FROM data_table_configs WHERE owner_user_id=? AND id = ?
                """, (owner_id, table_id), one=True)
                
                if not table_config_row:
                    continue
                
                try:
                    table_name = _safe_sql_table_name(table_config_row[1], "表名")
                    quoted_table_name = _quote_sql_table_name(table_name, "表名")
                    table_display_name = table_config_row[2]
                    date_field = _safe_optional_sql_identifier(table_config_row[5], "日期字段")
                    join_type_raw = table_config_row[8] if len(table_config_row) > 8 else None
                    join_type = _normalize_join_type(join_type_raw)
                    join_field = _safe_optional_sql_identifier(
                        table_config_row[9] if len(table_config_row) > 9 else "",
                        "关联字段名",
                    )
                except ValueError as e:
                    return jsonify({'success': False, 'error': str(e)})
                
                # 验证关联字段配置（这是关键字段，必须存在）
                if not join_field:
                    logging.error(f"表 {table_name} (ID: {table_id}) 未配置关联字段名(join_field)，无法与SecuMain关联。请检查表配置。")
                    return jsonify({
                        'success': False, 
                        'error': f'表 "{table_display_name}" 未配置关联字段名，这是与SecuMain关联的关键字段。请在表配置页面设置"关联字段名"。'
                    })
                
                # 获取字段配置
                field_configs = query_db("""SELECT field_name, field_display_name FROM data_field_configs 
                                           WHERE owner_user_id=? AND table_config_id=? AND id IN ({}) 
                                           ORDER BY order_index""".format(','.join(['?'] * len(field_ids))),
                                        tuple([owner_id, table_id] + field_ids))
                
                if not field_configs:
                    continue
                
                try:
                    field_names = [_safe_sql_identifier(f[0], "字段名") for f in field_configs]
                except ValueError as e:
                    return jsonify({'success': False, 'error': str(e)})
                if len(field_names) != len(field_ids):
                    return jsonify({'success': False, 'error': f'表 "{table_display_name}" 中存在无效或不属于该表的字段配置'})
                field_display_names = {f[0]: f[1] for f in field_configs}
                
                # 使用join_field作为关联字段（不再回退到code_field，因为join_field是必需的）
                actual_join_field = join_field
                
                table_info_list.append({
                    'table_id': table_id,
                    'table_name': table_name,
                    'quoted_table_name': quoted_table_name,
                    'table_display_name': table_display_name,
                    'table_alias': f't{len(table_info_list) + 1}',
                    'date_field': date_field,
                    'join_type': join_type,
                    'join_field': actual_join_field,
                    'field_names': field_names,
                    'field_display_names': field_display_names
                })
            
            if not table_info_list:
                return jsonify({'success': False, 'error': '没有有效的表配置'})
            
            # 第二步：如果有股票代码，先获取SecuCode到CompanyCode/InnerCode的映射
            # 重要：应用与筛选任务相同的筛选逻辑（STOCK_FILTER），确保数据口径一致
            secu_mapping = {}
            if stock_codes:
                from juyuan_config import STOCK_FILTER
                secu_query = f"""
                    SELECT DISTINCT SecuCode, CompanyCode, InnerCode 
                    FROM SecuMain 
                    WHERE SecuCode IN ({','.join(['?'] * len(stock_codes))})
                    AND ({STOCK_FILTER})
                    AND SecuCode NOT LIKE 'X%'
                """
                secu_data = fetcher.query(secu_query, tuple(stock_codes))
                if not secu_data.empty:
                    for _, row in secu_data.iterrows():
                        secu_mapping[row['SecuCode']] = {
                            'CompanyCode': row.get('CompanyCode'),
                            'InnerCode': row.get('InnerCode')
                        }
                # 记录过滤信息（仅在有股票被过滤时记录）
                if len(stock_codes) > len(secu_mapping):
                    filtered_count = len(stock_codes) - len(secu_mapping)
                    logging.debug(f"数据查询构建器：从{len(stock_codes)}只股票中过滤了{filtered_count}只不符合筛选条件的股票")
            
            # 第三步：构建多表关联SQL
            # 使用SecuMain作为中心表，通过SecuCode关联所有表
            select_fields_list = []
            from_clause = ""
            join_clauses = []
            where_conditions = []
            where_params = []
            
            # 添加SecuCode和SecuAbbr到SELECT（只添加一次）
            if stock_codes:
                select_fields_list.append("s.SecuCode as StockCode")
                select_fields_list.append("s.SecuAbbr as StockName")
                all_columns.append({'field': 'StockCode', 'display': '股票代码'})
                all_columns.append({'field': 'StockName', 'display': '股票名称'})
            
            # 为每个表构建JOIN和SELECT
            for idx, table_info in enumerate(table_info_list):
                table_alias = table_info['table_alias']
                table_name = table_info['table_name']
                quoted_table_name = table_info['quoted_table_name']
                table_display_name = table_info['table_display_name']
                join_type = table_info['join_type']
                join_field = table_info['join_field']
                date_field = table_info['date_field']
                field_names = table_info['field_names']
                field_display_names = table_info['field_display_names']
                
                # 添加字段到SELECT（带表名前缀）
                for field_name in field_names:
                    result_alias = _quote_sql_alias(f"{table_display_name}_{field_name}")
                    select_fields_list.append(f"{table_alias}.{_quote_sql_identifier(field_name)} as {result_alias}")
                    all_columns.append({
                        'field': f"{table_display_name}_{field_name}",
                        'display': f"{table_display_name}.{field_display_names[field_name]}"
                    })
                
                # 构建FROM子句（第一个表）
                if idx == 0:
                    from_clause = f"FROM {quoted_table_name} {table_alias}"
                    
                    # 第一个表直接JOIN SecuMain
                    # 使用用户配置的join_type和join_field（这是关键！）
                    if stock_codes:
                        join_field_name = _join_target_field(join_type)
                        join_clauses.append(f"INNER JOIN SecuMain s ON {table_alias}.{_quote_sql_identifier(join_field)} = s.{_quote_sql_identifier(join_field_name)}")
                        
                        # 添加WHERE条件限制SecuCode（确保唯一性）
                        secu_codes_placeholders = ','.join(['?'] * len(stock_codes))
                        where_conditions.append(f"s.SecuCode IN ({secu_codes_placeholders})")
                        where_params.extend(stock_codes)
                        
                        # 正常关联不记录日志，只在错误时记录
                    # logging.debug(f"表 {table_display_name}: 通过 {join_field} = SecuMain.{join_field_name} 关联")
                else:
                    # 后续表通过SecuMain关联（使用相同的SecuMain别名s）
                    # 使用用户配置的join_type和join_field（这是关键！）
                    join_field_name = _join_target_field(join_type)
                    # 使用LEFT JOIN处理日期粒度不一致问题（季度表 vs 日度表）
                    # 这样即使某个日期在第二张表中没有数据，也能显示第一张表的数据
                    join_clauses.append(f"LEFT JOIN {quoted_table_name} {table_alias} ON {table_alias}.{_quote_sql_identifier(join_field)} = s.{_quote_sql_identifier(join_field_name)}")
                    
                    # 正常关联不记录日志，只在错误时记录
                    # logging.debug(f"表 {table_display_name}: 通过 {join_field} = SecuMain.{join_field_name} 关联到中心表")
                
                # 添加日期范围条件（每个表独立处理）
                if date_range and date_field:
                    date_start = date_range.get('start')
                    date_end = date_range.get('end')
                    
                    if date_start:
                        where_conditions.append(f"{table_alias}.{_quote_sql_identifier(date_field)} >= ?")
                        where_params.append(date_start)
                    if date_end:
                        where_conditions.append(f"{table_alias}.{_quote_sql_identifier(date_field)} <= ?")
                        where_params.append(date_end)
                
                # 重要：处理不同表的日期粒度不一致问题
                # 如果第一张表是季度/月度数据，第二张表是日度数据
                # 使用LEFT JOIN确保即使某个日期没有数据也能关联上
                # 这已经在SQL的JOIN类型中处理（INNER JOIN改为LEFT JOIN会更好，但需要权衡）
            
            # 构建完整SQL
            select_clause = ", ".join(select_fields_list)
            join_clause = "\n".join(join_clauses)
            where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
            
            sql = f"""
                SELECT TOP {DATA_QUERY_MAX_ROWS} {select_clause}
                {from_clause}
                {join_clause}
                WHERE {where_clause}
            """
            
            # 只在调试时记录完整SQL（生产环境不记录，避免日志过大）
            # logging.debug(f"多表关联SQL: {sql[:200]}...")  # 只记录前200字符
            
            # 执行查询
            df = fetcher.query(sql, tuple(where_params) if where_params else None)
            
            if df.empty:
                # 格式化SQL以便显示（替换参数占位符为实际值）
                formatted_sql = sql
                if where_params:
                    # 按顺序替换所有?占位符
                    import re
                    param_index = 0
                    def replace_param(match):
                        nonlocal param_index
                        if param_index < len(where_params):
                            param = where_params[param_index]
                            param_index += 1
                            if isinstance(param, str):
                                # 转义单引号
                                escaped_param = param.replace("'", "''")
                                return f"'{escaped_param}'"
                            else:
                                return str(param)
                        return match.group(0)
                    formatted_sql = re.sub(r'\?', replace_param, formatted_sql)
                
                return jsonify({
                    'success': True,
                    'count': 0,
                    'table_count': len(table_info_list),
                    'data': [],
                    'columns': all_columns,
                    'sql': formatted_sql,  # 返回格式化的SQL
                    'warning': '查询结果为空，请检查筛选条件'
                })
            
            # 转换为字典列表
            for _, row in df.iterrows():
                row_dict = {}
                for col in df.columns:
                    value = row[col]
                    # 处理NaN值
                    import pandas as pd
                    if pd.isna(value):
                        value = None
                    elif isinstance(value, pd.Timestamp):
                        value = value.strftime('%Y-%m-%d')
                    row_dict[col] = value
                all_results.append(row_dict)
            
            # 过滤空行
            import pandas as pd
            filtered_results = []
            for row in all_results:
                # 检查是否有非空值（排除StockCode和StockName）
                has_data = any(
                    k not in ['StockCode', 'StockName'] and 
                    v is not None and 
                    (not isinstance(v, float) or not pd.isna(v)) 
                    for k, v in row.items()
                )
                if has_data:
                    filtered_results.append(row)
            
            # 格式化SQL以便显示（替换参数占位符为实际值）
            formatted_sql = sql
            if where_params:
                # 按顺序替换所有?占位符
                import re
                param_index = 0
                def replace_param(match):
                    nonlocal param_index
                    if param_index < len(where_params):
                        param = where_params[param_index]
                        param_index += 1
                        if isinstance(param, str):
                            # 转义单引号
                            escaped_param = param.replace("'", "''")
                            return f"'{escaped_param}'"
                        else:
                            return str(param)
                    return match.group(0)
                formatted_sql = re.sub(r'\?', replace_param, formatted_sql)
            
            return jsonify({
                'success': True,
                'count': len(filtered_results),
                'table_count': len(table_info_list),
                'data': filtered_results,
                'columns': all_columns,
                'sql': formatted_sql  # 返回格式化的SQL
            })
            
        finally:
            # 不立即清理连接池，由空闲超时机制管理（20分钟无活动后自动关闭）
            # fetcher.cleanup()  # 注释掉，让空闲超时机制管理
            pass
            
    except Exception as e:
        logging.error(f"执行多表查询失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 执行数据查询
@app.route('/api/data_query/execute', methods=['POST'])
@login_required
def execute_data_query():
    try:
        owner_id = current_user_id_required()
        data = request.get_json(silent=True) or {}
        try:
            table_id = int(data.get('table_id'))
            stock_codes = _normalize_stock_codes(data.get('stock_codes', []))  # 股票代码列表
            field_ids = _normalize_int_list(data.get('field_ids', []), "字段ID列表")  # 字段ID列表
            date_range = _normalize_date_range(data.get('date_range'))  # {'start': '2024-01-01', 'end': '2024-12-31'}
        except (TypeError, ValueError) as e:
            return jsonify({'success': False, 'error': str(e)})
        
        if not table_id:
            return jsonify({'success': False, 'error': '请选择数据表'})
        
        # 获取表配置
        # 使用明确的列名查询，避免索引错误
        # 表结构：id(0), table_name(1), table_display_name(2), description(3), 
        #         primary_key_field(4), date_field(5), code_field(6), name_field(7), 
        #         join_type(8), join_field(9), created_at(10), updated_at(11)
        table_config = query_db("""
            SELECT id, table_name, table_display_name, description, primary_key_field, 
                   date_field, code_field, name_field, join_type, join_field, created_at, updated_at
            FROM data_table_configs WHERE owner_user_id=? AND id = ?
        """, (owner_id, table_id), one=True)
        if not table_config:
            return jsonify({'success': False, 'error': '数据表配置不存在'})
        
        try:
            table_name = _safe_sql_table_name(table_config[1], "表名")  # table_name
            quoted_table_name = _quote_sql_table_name(table_name, "表名")
            code_field = _safe_optional_sql_identifier(table_config[6], "代码字段")  # code_field
            date_field = _safe_optional_sql_identifier(table_config[5], "日期字段")  # date_field
            join_type = _normalize_join_type(table_config[8] if len(table_config) > 8 else None)
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)})
        try:
            join_field = _safe_optional_sql_identifier(
                table_config[9] if len(table_config) > 9 else "",
                "关联字段名",
            )
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)})
        
        # 只在配置错误时记录详细信息
        # logging.debug(f"[数据表配置] id={table_id}, table_name={table_name}, join_type={join_type}, join_field={join_field}")
        
        # 提前验证字段名格式，避免后续SQL错误
        import re
        if date_field and isinstance(date_field, str):
            date_field = date_field.strip()
            if re.match(r'^\d{4}-\d{2}-\d{2}', date_field):
                return jsonify({'success': False, 'error': f'日期字段配置错误："{date_field}" 看起来像日期值而不是字段名。请检查数据表配置中的"日期字段"设置，应该填写字段名（如"TradingDay"）而不是日期值。'})
        if code_field and isinstance(code_field, str):
            code_field = code_field.strip()
            if re.match(r'^\d{4}-\d{2}-\d{2}', code_field):
                return jsonify({'success': False, 'error': f'代码字段配置错误："{code_field}" 看起来像日期值而不是字段名。请检查数据表配置中的"代码字段"设置。'})
        if join_field and isinstance(join_field, str):
            join_field = join_field.strip()
            if re.match(r'^\d{4}-\d{2}-\d{2}', join_field):
                return jsonify({'success': False, 'error': f'关联字段配置错误："{join_field}" 看起来像日期值而不是字段名。请检查数据表配置中的"关联字段名"设置，应该填写字段名（如"InnerCode"或"CompanyCode"）而不是日期值。'})
        
        # 获取字段配置
        if not field_ids:
            return jsonify({'success': False, 'error': '请至少选择一个字段'})
        
        field_configs = query_db("""SELECT field_name, field_display_name FROM data_field_configs 
                                   WHERE owner_user_id=? AND table_config_id=? AND id IN ({}) 
                                   ORDER BY order_index""".format(','.join(['?'] * len(field_ids))),
                                tuple([owner_id, table_id] + field_ids))
        
        if not field_configs:
            return jsonify({'success': False, 'error': '字段配置不存在'})
        
        # 构建SQL查询
        try:
            field_names = [_safe_sql_identifier(f[0], "字段名") for f in field_configs]
        except ValueError as e:
            return jsonify({'success': False, 'error': str(e)})
        if len(field_names) != len(field_ids):
            return jsonify({'success': False, 'error': '存在无效或不属于当前数据表的字段配置'})
        field_display_names = {f[0]: f[1] for f in field_configs}
        
        # 构建SELECT子句和FROM子句
        base_table_alias = 't'
        select_fields_list = [f"{base_table_alias}.{_quote_sql_identifier(field)} AS {_quote_sql_identifier(field)}" for field in field_names]
        
        # 构建FROM和JOIN子句
        from_clause = f"FROM {quoted_table_name} {base_table_alias}"
        join_clause = ""
        
        # 构建WHERE子句
        where_conditions = []
        where_params = []
        fetcher = None
        
        # 如果有股票代码，根据join_type决定关联方式
        # 重要：避免笛卡尔积的关键逻辑：
        # 1. 先查询SecuMain获取对应的CompanyCode/InnerCode，并同时获取SecuCode
        # 2. JOIN时使用严格的关联条件，并在WHERE中限制SecuCode，确保一对一关联
        # 3. 使用INNER JOIN确保只返回能匹配的数据，避免NULL值导致的笛卡尔积
        if stock_codes and (join_field or code_field):
            from data_fetcher import JuyuanDataFetcher
            fetcher = JuyuanDataFetcher(lazy_init_pool=True)
            
            # 获取关联字段名（优先使用join_field，否则使用code_field）
            actual_join_field = join_field if join_field else code_field
            
            # 验证关联字段名是否有效（必须是有效的SQL标识符，不能是日期字符串等）
            if not actual_join_field or not isinstance(actual_join_field, str):
                return jsonify({'success': False, 'error': f'关联字段名无效: join_field={join_field}, code_field={code_field}，请检查数据表配置'})
            
            actual_join_field = actual_join_field.strip()
            
            # 检查字段名格式：必须是有效的SQL标识符（字母、数字、下划线开头，不能包含日期格式）
            import re
            # 验证是否是有效的SQL标识符
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', actual_join_field):
                return jsonify({
                    'success': False, 
                    'error': f'关联字段名格式无效: "{actual_join_field}"。字段名必须是有效的SQL标识符（字母、数字、下划线，且以字母或下划线开头），不能包含日期、空格或特殊字符。请检查数据表配置中的"关联字段名"或"代码字段"设置。'
                })
            
            # 检查是否意外使用了日期字段的值（如果字段名看起来像日期格式，报错）
            date_pattern = r'^\d{4}-\d{2}-\d{2}'
            if re.match(date_pattern, actual_join_field):
                return jsonify({
                    'success': False, 
                    'error': f'关联字段名看起来像日期值而不是字段名: "{actual_join_field}"。请检查数据表配置：可能错误地将日期字段的值设置为关联字段名，应该使用字段名（如"InnerCode"、"CompanyCode"）而不是字段的值。'
                })
            
            # 只在配置错误时记录
            # logging.debug(f"[关联字段验证] actual_join_field={actual_join_field}, join_field={join_field}, code_field={code_field}")
            
            if not stock_codes:
                return jsonify({'success': False, 'error': '股票代码为空'})
            stock_placeholders = ",".join(["?"] * len(stock_codes))
            
            # 确保join_type是字符串并去除空格，转换为大写进行比较
            join_type_clean = join_type.strip().upper() if isinstance(join_type, str) else str(join_type).upper()
            logging.info(f"[JOIN类型检查] 原始join_type={join_type}, 清理后={join_type_clean}")
            
            if join_type_clean == 'COMPANYCODE':
                # 通过CompanyCode关联
                # 查询SecuMain获取CompanyCode和SecuCode的对应关系
                # 关键：同时获取SecuCode，用于在WHERE中精确限制，避免一对多导致的笛卡尔积
                # 重要：应用与筛选任务相同的筛选逻辑（STOCK_FILTER），确保数据口径一致
                from juyuan_config import STOCK_FILTER
                sql_get_secu_mapping = f"""
                SELECT DISTINCT CompanyCode, SecuCode 
                FROM SecuMain 
                WHERE SecuCode IN ({stock_placeholders}) AND SecuCategory = 1
                AND ({STOCK_FILTER})
                AND SecuCode NOT LIKE 'X%'
                """
                df_mapping = fetcher.query(sql_get_secu_mapping, tuple(stock_codes))
                if not df_mapping.empty and 'CompanyCode' in df_mapping.columns:
                    company_codes = df_mapping['CompanyCode'].unique().tolist()
                    secu_codes = df_mapping['SecuCode'].unique().tolist()
                    
                    if company_codes:
                        # 使用INNER JOIN而不是LEFT JOIN，确保只返回能匹配的数据，避免NULL导致的笛卡尔积
                        join_clause = f"""
                        INNER JOIN SecuMain s ON {base_table_alias}.{_quote_sql_identifier(actual_join_field)} = s.CompanyCode AND s.SecuCategory = 1
                        """
                        # 添加WHERE条件：同时限制CompanyCode和SecuCode
                        # 1. 限制CompanyCode确保只查询对应的公司
                        company_placeholders = ",".join(["?"] * len(company_codes))
                        where_conditions.append(f"{base_table_alias}.{_quote_sql_identifier(actual_join_field)} IN ({company_placeholders})")
                        where_params.extend(company_codes)
                        
                        # 2. 限制SecuCode确保只返回用户选择的股票代码（防止一个CompanyCode对应多个SecuCode导致的笛卡尔积）
                        secu_placeholders = ",".join(["?"] * len(secu_codes))
                        where_conditions.append(f"s.SecuCode IN ({secu_placeholders})")
                        where_params.extend(secu_codes)
                        
                        # 只在调试时记录
                        # logging.debug(f"CompanyCode关联: 找到 {len(company_codes)} 个CompanyCode, {len(secu_codes)} 个SecuCode")
                else:
                    return jsonify({'success': False, 'error': '未找到对应的CompanyCode，请检查股票代码是否正确'})
            elif join_type_clean == 'INNERCODE':
                # 通过InnerCode关联
                # 查询SecuMain获取InnerCode和SecuCode的对应关系
                # 重要：应用与筛选任务相同的筛选逻辑（STOCK_FILTER），确保数据口径一致
                from juyuan_config import STOCK_FILTER
                sql_get_secu_mapping = f"""
                SELECT DISTINCT InnerCode, SecuCode 
                FROM SecuMain 
                WHERE SecuCode IN ({stock_placeholders}) AND SecuCategory = 1
                AND ({STOCK_FILTER})
                AND SecuCode NOT LIKE 'X%'
                """
                df_mapping = fetcher.query(sql_get_secu_mapping, tuple(stock_codes))
                if not df_mapping.empty and 'InnerCode' in df_mapping.columns:
                    inner_codes = df_mapping['InnerCode'].unique().tolist()
                    secu_codes = df_mapping['SecuCode'].unique().tolist()
                    
                    if inner_codes:
                        # 使用INNER JOIN而不是LEFT JOIN，确保只返回能匹配的数据，避免NULL导致的笛卡尔积
                        join_clause = f"""
                        INNER JOIN SecuMain s ON {base_table_alias}.{_quote_sql_identifier(actual_join_field)} = s.InnerCode AND s.SecuCategory = 1
                        """
                        # 添加WHERE条件：同时限制InnerCode和SecuCode
                        # 1. 限制InnerCode确保只查询对应的股票
                        inner_placeholders = ",".join(["?"] * len(inner_codes))
                        where_conditions.append(f"{base_table_alias}.{_quote_sql_identifier(actual_join_field)} IN ({inner_placeholders})")
                        where_params.extend(inner_codes)
                        
                        # 2. 限制SecuCode确保只返回用户选择的股票代码（防止一个InnerCode对应多个SecuCode导致的笛卡尔积）
                        # 注意：InnerCode通常是唯一的，但为了安全性仍然添加此条件
                        secu_placeholders = ",".join(["?"] * len(secu_codes))
                        where_conditions.append(f"s.SecuCode IN ({secu_placeholders})")
                        where_params.extend(secu_codes)
                        
                        # 只在调试时记录
                        # logging.debug(f"InnerCode关联: 找到 {len(inner_codes)} 个InnerCode, {len(secu_codes)} 个SecuCode")
                else:
                    return jsonify({'success': False, 'error': '未找到对应的InnerCode，请检查股票代码是否正确'})
        
        # 如果成功构建了JOIN子句，则在SELECT中添加股票代码和名称字段
        # 注意：必须在这里添加，确保JOIN成功后才使用s.*
        if join_clause and stock_codes:
            select_fields_list.insert(0, f"s.SecuCode AS StockCode")
            select_fields_list.insert(1, f"s.SecuAbbr AS StockName")
        
        select_fields = ', '.join(select_fields_list)
        
        # 如果有日期范围，添加日期条件
        if date_range and date_field:
            start_date = date_range.get('start', '')
            end_date = date_range.get('end', '')
            if start_date:
                where_conditions.append(f"{base_table_alias}.{_quote_sql_identifier(date_field)} >= ?")
                where_params.append(start_date)
            if end_date:
                where_conditions.append(f"{base_table_alias}.{_quote_sql_identifier(date_field)} <= ?")
                where_params.append(end_date)
        
        # 构建完整SQL
        sql = f"SELECT TOP {DATA_QUERY_MAX_ROWS} {select_fields} {from_clause}"
        if join_clause:
            sql += join_clause
        if where_conditions:
            sql += " WHERE " + " AND ".join(where_conditions)
        
        # 只在错误时记录SQL（避免日志过大）
        # logging.debug(f"生成的SQL查询: {sql[:200]}...")  # 只记录前200字符
        
        # 执行查询
        # 如果之前没有创建fetcher（没有股票代码筛选），现在创建
        if fetcher is None:
            from data_fetcher import JuyuanDataFetcher
            fetcher = JuyuanDataFetcher(lazy_init_pool=True)
        
        try:
            df = fetcher.query(sql, tuple(where_params) if where_params else None)
            
            # 只在错误或空结果时记录
            if df.empty:
                logging.warning(f"查询结果为空: table={table_name}, stock_codes={len(stock_codes) if stock_codes else 0}只")
            # 正常查询不记录详细信息，避免日志过大
            
            # 转换为JSON格式
            result_data = []
            
            # 如果有关联SecuMain，需要添加StockCode和StockName到列信息
            result_columns = []
            if join_clause and stock_codes:
                result_columns.append({'field': 'StockCode', 'display': '股票代码'})
                result_columns.append({'field': 'StockName', 'display': '股票名称'})
            
            # 检查DataFrame是否为空
            if df.empty:
                logging.warning(f"查询结果为空！SQL: {sql}")
                return jsonify({
                    'success': True,
                    'data': [],
                    'columns': result_columns + [{'field': name, 'display': field_display_names.get(name, name)} 
                                                 for name in field_names],
                    'count': 0,
                    'sql': sql,
                    'warning': '查询结果为空，请检查筛选条件是否正确'
                })
            
            # 处理每一行数据
            actual_row_count = 0
            empty_row_count = 0
            for idx, row in df.iterrows():
                record = {}
                
                # 如果有关联SecuMain，添加股票代码和名称
                if join_clause and stock_codes:
                    record['StockCode'] = row.get('StockCode')
                    record['StockName'] = row.get('StockName')
                
                # 添加用户选择的字段
                has_non_null_data = False
                for field_name in field_names:
                    value = row.get(field_name)
                    if value is None and f"{base_table_alias}.{field_name}" in row:
                        value = row.get(f"{base_table_alias}.{field_name}")
                    # 处理NaN值
                    if pd.isna(value):
                        value = None
                    elif isinstance(value, pd.Timestamp):
                        value = value.strftime('%Y-%m-%d')
                    record[field_name] = value
                    # 检查是否有非空数据
                    if value is not None:
                        has_non_null_data = True
                
                # 检查是否有实际数据（至少有一个非空字段）
                # 如果有关联SecuMain，检查StockCode或StockName
                if join_clause and stock_codes:
                    if record.get('StockCode') or record.get('StockName'):
                        has_non_null_data = True
                
                # 只有当记录中有实际数据时才添加
                if has_non_null_data:
                    result_data.append(record)
                    actual_row_count += 1
                else:
                    empty_row_count += 1
            
            # 添加字段列信息
            result_columns.extend([{'field': name, 'display': field_display_names.get(name, name)} 
                                 for name in field_names])
            
            # 只在结果异常时记录（正常查询不记录）
            if actual_row_count == 0 and len(df) > 0:
                logging.warning(f"查询返回 {len(df)} 行但有效记录为0，可能存在数据质量问题")
            
            # 不立即清理连接池，由空闲超时机制管理（20分钟无活动后自动关闭）
            # 这样可以避免频繁创建和关闭连接，提高性能
            # fetcher.cleanup()  # 注释掉，让空闲超时机制管理
            
            return jsonify({
                'success': True,
                'data': result_data,
                'columns': result_columns,
                'count': actual_row_count,
                'sql': sql
            })
        except Exception as e:
            logging.error(f"执行查询失败: {e}", exc_info=True)
            # 不立即清理连接，由空闲超时机制管理
            # try:
            #     if 'fetcher' in locals():
            #         fetcher.cleanup()
            # except:
            #     pass
            return jsonify({'success': False, 'error': f'查询失败: {str(e)}'})
        
    except Exception as e:
        logging.error(f"执行数据查询失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

# 从文字内容识别表结构（无需OCR）
@app.route('/api/data_query/recognize_table_from_text', methods=['POST'])
@login_required
def recognize_table_from_text():
    """从文字内容识别表结构"""
    try:
        data = request.get_json()
        text = data.get('text', '').strip()
        
        if not text:
            return jsonify({'success': False, 'error': '请输入表结构文字内容'})
        
        # 构建提示词
        prompt = f"""请分析以下表结构文字内容，识别出所有字段信息，并返回JSON格式的数据。

文字内容：
{text}

请识别并返回字段信息，格式如下：
{{
    "fields": [
        {{
            "field_name": "字段名（数据库字段名）",
            "field_display_name": "显示名称",
            "field_type": "字段类型（TEXT/INTEGER/REAL/DECIMAL/DATE/DATETIME/TIMESTAMP）",
            "description": "字段描述",
            "is_sortable": true,
            "is_filterable": true,
            "order_index": 0
        }}
    ]
}}

注意事项：
- 如果文字中有多个表，请全部识别
- 字段类型请根据常见数据库类型推断（VARCHAR/TEXT -> TEXT, INT/BIGINT -> INTEGER, DECIMAL/FLOAT -> REAL, DATE -> DATE, DATETIME/TIMESTAMP -> DATETIME）
- 如果没有明确的显示名称，使用字段名
- order_index按照文字中的顺序从0开始递增
- 尽量识别所有可见的字段信息

请只返回JSON格式的数据，不要添加其他说明文字。"""
        
        # 使用纯文本格式调用当前 AI 提供者
        messages = [
            {
                "role": "user",
                "content": prompt
            }
        ]
        
        try:
            field_data = call_deepseek_json_chat(
                messages,
                temperature=0.3,
                max_tokens=4000,
                timeout=120,
                max_attempts=1,
            )
            fields = field_data.get('fields', []) if isinstance(field_data, dict) else []
            if fields:
                return jsonify({
                    'success': True,
                    'fields': fields
                })
            return jsonify({'success': False, 'error': '未识别到字段信息'})
        except Exception as e:
            logging.error(f"AI识别请求异常: {e}", exc_info=True)
            return jsonify({'success': False, 'error': f'API请求异常: {str(e)}'})
            
    except Exception as e:
        logging.error(f"识别失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': f'识别失败: {str(e)}'})

# 识别图片中的表结构（当前流程先 OCR，再交给 AI 识别）
@app.route('/api/data_query/recognize_table', methods=['POST'])
@login_required
def recognize_table_from_image():
    try:
        if 'images' not in request.files:
            return jsonify({'success': False, 'error': '请上传图片'})
        
        files = request.files.getlist('images')
        if not files or len(files) == 0:
            return jsonify({'success': False, 'error': '请至少上传一张图片'})
        
        import base64
        import io
        
        # 读取所有图片并转换为base64
        image_data_list = []
        for file in files:
            if file.filename == '':
                continue
            
            # 读取图片数据
            image_bytes = file.read()
            
            # 转换为base64
            image_base64 = base64.b64encode(image_bytes).decode('utf-8')
            
            # 根据文件扩展名判断MIME类型
            filename = file.filename.lower()
            if filename.endswith('.png'):
                mime_type = 'image/png'
            elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
                mime_type = 'image/jpeg'
            elif filename.endswith('.gif'):
                mime_type = 'image/gif'
            elif filename.endswith('.webp'):
                mime_type = 'image/webp'
            else:
                mime_type = 'image/jpeg'  # 默认
            
            image_data_list.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{image_base64}"
                }
            })
        
        if not image_data_list:
            return jsonify({'success': False, 'error': '没有有效的图片文件'})
        
        # 构建提示词
        prompt = """请仔细分析这些图片中的数据库表结构。

请识别图片中显示的数据表字段信息，包括：
1. 字段名（Field Name / Column Name）
2. 字段类型（Type / Data Type）
3. 字段描述或说明（Description / Comment）
4. 其他相关信息

请以JSON格式返回识别结果，格式如下：
{
    "fields": [
        {
            "field_name": "字段名",
            "field_display_name": "字段显示名称（如果没有则使用字段名）",
            "field_type": "字段类型（TEXT/INTEGER/REAL/DATE/DATETIME）",
            "description": "字段描述",
            "is_sortable": true,
            "is_filterable": true,
            "order_index": 0
        }
    ]
}

注意事项：
- 如果图片中有多个表，请全部识别
- 字段类型请根据常见数据库类型推断（VARCHAR/TEXT -> TEXT, INT/BIGINT -> INTEGER, DECIMAL/FLOAT -> REAL, DATE -> DATE, DATETIME/TIMESTAMP -> DATETIME）
- 如果没有明确的显示名称，使用字段名
- order_index按照图片中的顺序从0开始递增
- 尽量识别所有可见的字段信息

请只返回JSON格式的数据，不要添加其他说明文字。"""
        
        # 当前流程只发送 OCR 后的文本
        # 我们需要使用OCR提取图片中的文字，然后发送给AI
        # 如果没有OCR库，则提示用户手动输入或使用其他方式
        
        try:
            # 尝试使用PIL和pytesseract进行OCR
            from PIL import Image
            try:
                import pytesseract
                
                # 尝试自动检测 Tesseract 路径（Windows 常见安装位置）
                if os.name == 'nt':  # Windows系统
                    possible_paths = [
                        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
                        r'C:\Users\{}\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'.format(os.getenv('USERNAME', '')),
                    ]
                    # 如果环境变量中没有 tesseract，尝试设置路径
                    try:
                        pytesseract.get_tesseract_version()
                    except Exception:
                        # 遍历可能的路径
                        for path in possible_paths:
                            if os.path.exists(path):
                                pytesseract.pytesseract.tesseract_cmd = path
                                break
                        else:
                            # 如果都找不到，给用户提示
                            logging.warning("未找到 Tesseract OCR，请安装或配置路径。参考 OCR_安装说明.md")
            except ImportError:
                # 如果没有安装pytesseract，提示用户
                return jsonify({
                    'success': False,
                    'error': '当前图片识别流程需要先安装 OCR 库以提取图片文字：\n\n1. 安装 Tesseract OCR：\n   - Windows: https://github.com/UB-Mannheim/tesseract/wiki\n   - 下载中文语言包: chi_sim.traineddata\n\n2. 安装 Python 库：\n   pip install pytesseract pillow\n\n详细安装说明请参考项目根目录下的 OCR_安装说明.md 文件\n\n或者，您可以先使用"输入文字"功能，直接粘贴表结构文字。'
                })
            
            # 提取所有图片中的文字
            extracted_texts = []
            success_count = 0
            fail_count = 0
            
            # 只在开始和结束时记录汇总信息
            logging.info(f"OCR识别开始: {len(image_data_list)} 张图片")
            
            # 验证Tesseract是否可用
            try:
                tesseract_version = pytesseract.get_tesseract_version()
                # OCR版本信息只在调试时记录
                # logging.debug(f"Tesseract OCR 版本: {tesseract_version}")
            except Exception as e:
                logging.error(f"Tesseract OCR 验证失败: {e}")
                return jsonify({
                    'success': False,
                    'error': f'Tesseract OCR 未正确配置或未找到。\n\n请确保：\n1. 已安装 Tesseract OCR 引擎\n2. 已配置环境变量或路径\n3. 已下载中文语言包 (chi_sim.traineddata)\n\n错误详情: {str(e)}\n\n或者，您可以先使用"输入文字"功能，直接粘贴表结构文字。'
                })
            
            for i, img_data in enumerate(image_data_list):
                try:
                    # 从base64解码图片
                    base64_data = img_data["image_url"]["url"].split(',')[1] if ',' in img_data["image_url"]["url"] else img_data["image_url"]["url"]
                    if base64_data:
                        image_bytes = base64.b64decode(base64_data)
                        image = Image.open(io.BytesIO(image_bytes))
                        
                        # 不记录每张图片的识别过程，避免日志过多
                        # logging.debug(f"正在对图片{i+1}进行OCR识别...")
                        # 使用OCR提取文字（支持中英文）
                        text = pytesseract.image_to_string(image, lang='chi_sim+eng')
                        
                        if text.strip():
                            success_count += 1
                            # 限制提取的文字长度，避免API请求过大（最多8000字符）
                            max_text_length = 8000
                            if len(text) > max_text_length:
                                text = text[:max_text_length] + f"\n\n[文字过长，已截断，原长度: {len(text)} 字符]"
                                # 只在汇总时记录
                                # logging.debug(f"图片{i+1} OCR提取的文字过长，已截断")
                            
                            extracted_texts.append(f"\n\n=== 图片{i+1}中提取的文字 ===\n{text}")
                        else:
                            fail_count += 1
                            extracted_texts.append(f"\n\n=== 图片{i+1}未能提取到文字，请确保图片清晰 ===")
                except Exception as e:
                    fail_count += 1
                    # 只记录错误，不记录详细信息
                    logging.error(f"OCR提取图片{i+1}失败: {e}")
                    extracted_texts.append(f"\n\n=== 图片{i+1}OCR提取失败: {str(e)} ===")
            
            # 记录OCR汇总信息
            if success_count > 0 or fail_count > 0:
                logging.info(f"OCR识别完成: 成功 {success_count} 张，失败 {fail_count} 张，共 {len(image_data_list)} 张")
            
            # 构建增强的提示词
            enhanced_prompt = prompt
            if extracted_texts:
                enhanced_prompt += "\n\n以下是从图片中提取的文字信息，请根据这些信息识别表结构："
                enhanced_prompt += "".join(extracted_texts)
            else:
                return jsonify({
                    'success': False, 
                    'error': '未能从图片中提取文字，请确保图片清晰且包含表结构信息，或手动输入字段配置'
                })
            
        except ImportError as e:
            # 如果没有OCR库，返回错误提示
            return jsonify({
                'success': False,
                'error': f'当前图片识别流程需要先安装 OCR 库以提取图片文字：\n\npip install pytesseract pillow\n\n错误详情: {str(e)}'
            })
        except Exception as e:
            error_msg = str(e)
            # 检查是否是 Tesseract 未找到的错误
            if 'tesseract' in error_msg.lower() or 'not found' in error_msg.lower():
                return jsonify({
                    'success': False,
                    'error': f'Tesseract OCR 未找到或未正确配置。\n\n请确保：\n1. 已安装 Tesseract OCR 引擎\n2. 已配置环境变量或路径\n3. 已下载中文语言包 (chi_sim.traineddata)\n\n详细安装说明请参考项目根目录下的 OCR_安装说明.md 文件\n\n错误详情: {error_msg}\n\n或者，您可以先使用"输入文字"功能，直接粘贴表结构文字。'
                })
            logging.error(f"OCR处理失败: {e}", exc_info=True)
            return jsonify({
                'success': False,
                'error': f'图片处理失败: {error_msg}。\n\n请检查：\n1. 图片是否清晰\n2. OCR 库是否正确安装\n3. 中文语言包是否已下载\n\n详细安装说明请参考项目根目录下的 OCR_安装说明.md 文件\n\n或者，您可以先使用"输入文字"功能，直接粘贴表结构文字。'
            })
        
        # 使用纯文本格式
        messages = [
            {
                "role": "user",
                "content": enhanced_prompt
            }
        ]
        
        try:
            # 增加超时时间到180秒（3分钟），因为OCR提取的文字可能很长，需要更长的处理时间
            # 只在开始和结束时记录
            logging.info(f"AI表结构识别开始: 提示词长度 {len(enhanced_prompt)} 字符")
            parsed_result = call_deepseek_json_chat(
                messages,
                temperature=0.3,
                max_tokens=4000,
                timeout=180,
                max_attempts=1,
            )
            if 'fields' in parsed_result and isinstance(parsed_result['fields'], list):
                logging.info(f"AI表结构识别成功: 识别到 {len(parsed_result['fields'])} 个字段")
                return jsonify({
                    'success': True,
                    'fields': parsed_result['fields']
                })
            return jsonify({'success': False, 'error': 'API返回格式不正确，未找到fields字段'})
        except Exception as e:
            error_msg = str(e)
            logging.error(f"调用AI API失败: {error_msg}", exc_info=True)
            # 检查是否是超时相关的错误
            if 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower():
                return jsonify({
                    'success': False,
                    'error': f'API请求超时。\n\n可能的原因：\n1. OCR提取的文字过长\n2. 网络连接不稳定\n3. API服务器响应慢\n\n建议：\n1. 尝试减少上传的图片数量\n2. 使用"输入文字"功能\n3. 检查网络连接后重试\n\n错误详情: {error_msg}'
                })
            return jsonify({'success': False, 'error': f'API调用失败: {error_msg}'})
            
    except Exception as e:
        logging.error(f"识别表结构失败: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})
