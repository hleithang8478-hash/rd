# 大跌筛选配置
CRASH_DROP_PCT = 0.4  # 一年内跌幅阈值
STOCK_LIST_LIMIT = 5000  # 全局股票列表数量上限
MAX_TRADING_DAYS_AGO = 30  # 最大允许的行情日期滞后天数，超过此天数的股票将被排除（停牌/退市）

# 性能优化配置 - 智能配置
import os
import multiprocessing

# 获取CPU核心数
CPU_COUNT = multiprocessing.cpu_count()


def _env_int(name, default, min_value=None, max_value=None):
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value

# 智能线程配置
def get_optimal_workers():
    """根据CPU核心数和内存情况智能配置线程数"""
    base_workers = min(CPU_COUNT * 4, 64)
    
    # 如果环境变量指定了线程数，使用指定值
    if 'MAX_WORKERS' in os.environ:
        return _env_int('MAX_WORKERS', base_workers, min_value=1, max_value=512)
    
    # 如果环境变量指定了高性能模式，使用更高但有上限的配置
    if 'HIGH_PERFORMANCE' in os.environ and os.environ['HIGH_PERFORMANCE'].lower() in ['true', '1', 'yes']:
        return _env_int('HIGH_PERFORMANCE_MAX_WORKERS', min(CPU_COUNT * 8, 128), min_value=1, max_value=512)
    
    # 对于小规模测试（股票数量少），使用较少的线程数
    if STOCK_LIST_LIMIT <= 50:
        return min(CPU_COUNT * 2, 32)
    
    return base_workers

def get_optimal_batch_size():
    """根据线程数智能配置批处理大小（极限优化：更小的批次以提高并行度）"""
    workers = get_optimal_workers()
    
    # 极限优化策略：使用更小的批次大小，以产生更多批次，提高并行度
    # 对于IO密集型任务，更小的批次可以大幅提高并发度
    # 批次大小 = 线程数 * 2（而不是*4），产生更多批次
    if STOCK_LIST_LIMIT <= 50:
        return max(workers // 2, 30)  # 小规模测试也使用较小的批次以提高并行度
    
    # 批处理大小 = 线程数 * 2，产生更多批次，最大化并行度
    return max(workers * 2, 50)  # 至少50，确保有足够的批次

MAX_WORKERS = get_optimal_workers()  # 智能配置线程数
BATCH_SIZE = get_optimal_batch_size()   # 智能配置批处理大小
CHUNK_SIZE = 50    # 数据块大小

# 数据库连接池配置
def get_optimal_pool_size():
    """智能配置连接池大小"""
    if 'DB_POOL_SIZE' in os.environ:
        return _env_int('DB_POOL_SIZE', min(max(MAX_WORKERS * 2, 8), 128), min_value=1, max_value=512)
    base_pool_size = max(MAX_WORKERS * 2, 8)
    
    # 对于单股票测试，确保有足够的连接
    if STOCK_LIST_LIMIT <= 1:
        return min(base_pool_size, 16)
    
    return min(base_pool_size, 128)

DB_POOL_SIZE = get_optimal_pool_size()  # 智能配置连接池大小
DB_TIMEOUT = 60  # 增加连接超时时间，避免快速超时

# 性能优化参数
MAX_RETRIES = 3  # 最大重试次数
RETRY_DELAY = 2  # 重试间隔（秒）
BATCH_TIMEOUT = 300  # 批处理超时时间（秒）
QUERY_TIMEOUT = 120  # 单次查询超时时间（秒）

# 线程控制参数
THREAD_STARTUP_DELAY = 0.1  # 线程启动延迟（秒），避免同时启动所有线程
MAX_CONCURRENT_BATCHES = _env_int('MAX_CONCURRENT_BATCHES', 64, min_value=1, max_value=512)

# 相关性分析配置
CORRELATION_MAX_WORKERS = get_optimal_workers()  # 相关性分析使用与主配置相同的线程数
CORRELATION_BATCH_SIZE = BATCH_SIZE  # 相关性分析使用与主配置相同的批处理大小

# 业绩预期和动量指标配置
EXPECTATION_ENABLED = False  # 暂时禁用业绩预期分析（执行速度优化）
MOMENTUM_ENABLED = True     # 是否启用动量指标分析
EXPECTATION_WEIGHT = 0.15   # 业绩预期在综合评分中的权重
MOMENTUM_WEIGHT = 0.15      # 动量指标在综合评分中的权重

# 数据库配置（用于index_correlation_analysis.py）
DB_CONFIG = {
    'host': os.getenv('JUYUAN_DB_SERVER', '172.16.105.192'),
    'user': os.getenv('JUYUAN_DB_USER', 'readonly'),
    'password': os.getenv('JUYUAN_DB_PASSWORD', ''),
    'database': os.getenv('JUYUAN_DB_NAME', 'JYDB'),
    'port': int(os.getenv('JUYUAN_DB_PORT', '1433')),
    'charset': 'utf8'
}

# 字段映射（英文到中文）
FIELD_MAPPING = {
    # 基础信息
    '股票代码': '股票代码',
    'SecuCode': '证券代码',
    'CompanyCode': '公司代码',
    'InnerCode': '内部代码',
    '股票简称': '股票简称',
    'SecuAbbr': '股票简称',
    
    # 行业信息
    '一级行业': '一级行业',
    '二级行业': '二级行业',
    '三级行业': '三级行业',
    'FirstIndustryName': '一级行业',
    'SecondIndustryName': '二级行业',
    'ThirdIndustryName': '三级行业',
    
    # 日期信息
    '报告期': '报告期',
    '行情日期': '行情日期',
    'EndDate': '报告期',
    'TradingDay': '交易日期',
    
    # 盈利能力指标
    'ROETTM': '净资产收益率TTM',
    'ROICTTM': '投入资本回报率TTM',
    'NetProfitRatioTTM': '销售净利率TTM',
    'NPToTORTTM': '净利润/营业收入TTM',
    'OperatingRevenueCashCover': '营业收入现金含量',
    'NetProfitCashCover': '净利润现金含量',
    'MainProfitProportion': '主营业务比率',
    
    # 费用控制指标
    'OperatingExpenseRateTTM': '销售费用/营业收入TTM',
    'AdminiExpenseRateTTM': '管理费用/营业收入TTM',
    'FinancialExpenseRateTTM': '财务费用/营业收入TTM',
    
    # 偿债能力指标
    'SuperQuickRatio': '超速动比率',
    'NOCFToCurrentLiability': '经营活动现金流量净额/流动负债',
    'NetAssetLiabilityRatio': '净资产负债率',
    'InteBearDebtToTL': '带息负债率',
    
    # 成长能力指标
    'OperatingRevenueGrowRate': '营业收入同比增长',
    'TORGrowRate': '营业收入同比增长率',
    'TotalOperatingRevenuePS': '每股营业收入',
    'NetOperateCashFlowYOY': '经营活动现金流量净额同比增长',
    'OperCashPSGrowRate': '每股经营活动现金流量净额TTM',
    
    # 分红指标
    'DividendPS': '股息股利',
    'DividendPaidRatio': '股利支付率',
    'DividendTTM': '股息TTM',
    
    # 规模指标
    'TotalAssets': '总资产',
    'TotalEquity': '股东权益',
    'OperatingRevenue': '营业收入',
    'NetProfit': '净利润',
    'OperatingCashFlow': '经营现金流',
    
    # 行情数据
    '收盘价': '收盘价',
    '成交量': '成交量',
    'ClosePrice': '收盘价',
    'Volume': '成交量',
    
    # 大跌信息
    '最大跌幅': '最大跌幅',
    '跌幅开始日期': '跌幅开始日期',
    '跌幅结束日期': '跌幅结束日期',
    '当前价格': '当前价格',
    
    # 趋势分析字段
    '指标分类': '指标分类',
    '指标名称': '指标名称',
    '5年CAGR(%)': '5年复合增长率(%)',
    '趋势斜率': '趋势斜率',
    '趋势标签': '趋势标签',
    '起始值': '起始值',
    '当前值': '当前值',
    '变化幅度(%)': '变化幅度(%)',
    
    # 历史数据字段
    '近5年数据': '近5年数据',
    '年份': '年份',
    
    # 分位数字段（动态生成）
    '_当前值': '-当前值',
    '_分位数': '-分位数',
} 
