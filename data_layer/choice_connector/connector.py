"""
东方财富 Choice 数据接口连接器
支持：登录/退出、截面数据、序列数据、专题报表、资讯订阅
注意：需在中国大陆IP环境运行（阿里云上海ECS），海外IP受限
"""

import time
import logging
import pandas as pd
from typing import Optional, Union
from pathlib import Path

logger = logging.getLogger(__name__)


class ChoiceConnector:
    """
    Choice数据接口封装

    使用方法：
        conn = ChoiceConnector()
        conn.login(username='xxx', password='xxx')

        # 获取截面数据
        df = conn.get_css('600893.SH', ['NETPROFIT', 'CONTRACTLIABILITY'], '20241231')

        # 获取序列数据
        df = conn.get_csd('600893.SH', ['NETPROFIT', 'CONTRACTLIABILITY'],
                          '2020-01-01', '2024-12-31')

        conn.logout()
    """

    def __init__(self):
        self._c = None
        self._logged_in = False
        self._import_emquant()

    def _import_emquant(self):
        """动态导入EmQuantAPI，避免未安装时报错"""
        try:
            import EmQuantAPI as c
            self._c = c
            logger.info("[Choice] EmQuantAPI导入成功")
        except ImportError:
            logger.warning(
                "[Choice] EmQuantAPI未安装，请先运行:\n"
                "  python installEmQuantAPI.py\n"
                "  或参考: https://quantapi.eastmoney.com/"
            )

    # ------------------------------------------------------------------
    # 登录 / 退出
    # ------------------------------------------------------------------

    def login(
        self,
        username: str = "",
        password: str = "",
        force: bool = True,
    ) -> bool:
        """
        登录Choice接口
        - 有账密则账密登录
        - 无账密则使用本地userInfo令牌
        """
        if not self._c:
            logger.error("[Choice] EmQuantAPI未导入，无法登录")
            return False

        options_parts = []
        if username and password:
            options_parts.append(f"UserName={username}")
            options_parts.append(f"PassWord={password}")
        if force:
            options_parts.append("ForceLogin=1")

        options = ",".join(options_parts)

        result = self._c.start(options) if options else self._c.start()

        if result.ErrorCode != 0:
            logger.error(f"[Choice] 登录失败: {result.ErrorMsg}")
            return False

        self._logged_in = True
        logger.info("[Choice] 登录成功")
        return True

    def logout(self):
        """退出登录"""
        if self._c and self._logged_in:
            self._c.stop()
            self._logged_in = False
            logger.info("[Choice] 已退出")

    def _check_login(self) -> bool:
        if not self._logged_in:
            logger.error("[Choice] 未登录，请先调用login()")
            return False
        return True

    # ------------------------------------------------------------------
    # 截面数据 css
    # ------------------------------------------------------------------

    def get_css(
        self,
        codes: Union[str, list],
        indicators: Union[str, list],
        end_date: str = "",
        extra_options: str = "",
    ) -> Optional[pd.DataFrame]:
        """
        获取截面数据（某一时间点的多指标快照）

        参数：
            codes       : 股票代码，如 '600893.SH' 或 ['600893.SH','601021.SH']
            indicators  : 指标列表，如 ['NETPROFIT','CONTRACTLIABILITY']
            end_date    : 截止日期，如 '20241231'
            extra_options: 附加参数字符串

        返回：pandas DataFrame，index为股票代码
        """
        if not self._check_login():
            return None

        codes_str      = ",".join(codes) if isinstance(codes, list) else codes
        indicators_str = ",".join(indicators) if isinstance(indicators, list) else indicators

        options_parts = ["Ispandas=1"]
        if end_date:
            options_parts.append(f"enddate={end_date}")
        if extra_options:
            options_parts.append(extra_options)
        options = ",".join(options_parts)

        try:
            data = self._c.css(codes_str, indicators_str, options)
            if not isinstance(data, pd.DataFrame):
                # 非pandas返回时检查ErrorCode
                if hasattr(data, 'ErrorCode') and data.ErrorCode != 0:
                    logger.error(f"[css] 错误: {data.ErrorMsg}")
                    return None
            logger.info(f"[css] 获取成功: {codes_str} | {indicators_str}")
            return data
        except Exception as e:
            logger.error(f"[css] 异常: {e}")
            return None

    # ------------------------------------------------------------------
    # 序列数据 csd
    # ------------------------------------------------------------------

    def get_csd(
        self,
        codes: Union[str, list],
        indicators: Union[str, list],
        start_date: str,
        end_date: str,
        period: str = "1",       # 1日 2周 3月 4年
        adjust: str = "1",       # 1不复权 2后复权 3前复权
        extra_options: str = "",
    ) -> Optional[pd.DataFrame]:
        """
        获取序列数据（时间区间内的历史数据）

        参数：
            codes      : 股票代码
            indicators : 指标列表
            start_date : 开始日期，如 '2020-01-01'
            end_date   : 结束日期，如 '2024-12-31'
            period     : 日期周期 1=日 2=周 3=月 4=年
            adjust     : 复权方式 1=不复权 2=后复权 3=前复权

        返回：pandas DataFrame
        """
        if not self._check_login():
            return None

        codes_str      = ",".join(codes) if isinstance(codes, list) else codes
        indicators_str = ",".join(indicators) if isinstance(indicators, list) else indicators

        options_parts = [
            "Ispandas=1",
            f"Period={period}",
            f"AdjustFlag={adjust}",
        ]
        if extra_options:
            options_parts.append(extra_options)
        options = ",".join(options_parts)

        try:
            data = self._c.csd(codes_str, indicators_str, start_date, end_date, options)
            if not isinstance(data, pd.DataFrame):
                if hasattr(data, 'ErrorCode') and data.ErrorCode != 0:
                    logger.error(f"[csd] 错误: {data.ErrorMsg}")
                    return None
            logger.info(f"[csd] 获取成功: {codes_str} {start_date}~{end_date}")
            return data
        except Exception as e:
            logger.error(f"[csd] 异常: {e}")
            return None

    # ------------------------------------------------------------------
    # 专题报表 ctr
    # ------------------------------------------------------------------

    def get_ctr(
        self,
        report_name: str,
        indicators: str = "",
        options: str = "",
    ) -> Optional[pd.DataFrame]:
        """
        获取专题报表数据

        常用报表名称：
            INDEXCOMPOSITION    指数成分
            NORTHHOLDTOP        北向增持排行（需权限）
            SOUTHNORTHHOLDTOP   南北向机构持股排行
            CAPITALTRANSFER     市场资金流向

        示例：
            conn.get_ctr("INDEXCOMPOSITION",
                         options="IndexCode=000300.SH,EndDate=2024-12-31")
        """
        if not self._check_login():
            return None

        # 追加pandas输出
        sep = "," if options else ""
        full_options = options + sep + "Ispandas=1"

        try:
            data = self._c.ctr(report_name, indicators, full_options)
            if not isinstance(data, pd.DataFrame):
                if hasattr(data, 'ErrorCode') and data.ErrorCode != 0:
                    logger.error(f"[ctr] 错误: {data.ErrorMsg}")
                    return None
            logger.info(f"[ctr] 获取成功: {report_name}")
            return data
        except Exception as e:
            logger.error(f"[ctr] 异常: {e}")
            return None

    # ------------------------------------------------------------------
    # 条件选股 cps
    # ------------------------------------------------------------------

    def screen_stocks(
        self,
        sector: str = "B_001004",       # 默认全部A股
        param_defs: str = "",            # 如 "s1,CONTRACTLIABILITYRATE"
        conditions: str = "",            # 如 "[s1] > 30"
        top_options: str = "",           # 如 "top=max([s1],50)"
    ) -> Optional[list]:
        """
        条件选股

        示例：筛选合同负债增长>30%且净利润为负的股票
            conn.screen_stocks(
                param_defs="s1,CONTRACTLIABILITYRATE;s2,NETPROFITRATE",
                conditions="[s1] > 30 and [s2] < 0",
                top_options="top=max([s1],50)"
            )
        """
        if not self._check_login():
            return None

        try:
            data = self._c.cps(sector, param_defs, conditions, top_options)
            if data.ErrorCode != 0:
                logger.error(f"[cps] 错误: {data.ErrorMsg}")
                return None
            logger.info(f"[cps] 选股完成，共{len(data.Data)}个标的")
            return data.Data
        except Exception as e:
            logger.error(f"[cps] 异常: {e}")
            return None

    # ------------------------------------------------------------------
    # 资讯订阅 cnq
    # ------------------------------------------------------------------

    def subscribe_news(
        self,
        codes: Union[str, list],
        content_types: str = "report,tradeinfo",
        callback=None,
    ):
        """
        订阅实时公告和重大事项

        content_types可选：
            companynews   公司资讯
            industrynews  行业资讯
            report        公告
            regularreport 定期公告
            tradeinfo     重大事项

        示例：
            def on_news(data):
                print(data.Data)

            conn.subscribe_news('600893.SH', 'report,tradeinfo', on_news)
        """
        if not self._check_login():
            return None

        codes_str = ",".join(codes) if isinstance(codes, list) else codes

        def default_callback(quantdata):
            for code in quantdata.Data:
                for item in quantdata.Data[code]:
                    logger.info(f"[资讯] {code}: {item}")

        cb = callback or default_callback

        try:
            result = self._c.cnq(codes_str, content_types, "", cb)
            if result.ErrorCode != 0:
                logger.error(f"[cnq] 订阅失败: {result.ErrorMsg}")
                return None
            logger.info(f"[cnq] 已订阅 {codes_str} | {content_types}")
            return result.SerialID
        except Exception as e:
            logger.error(f"[cnq] 异常: {e}")
            return None

    def unsubscribe_news(self, serial_id: int = 0):
        """取消资讯订阅，serial_id=0取消全部"""
        if self._c:
            self._c.cnqcancel(serial_id)
            logger.info(f"[cnq] 已取消订阅 serial_id={serial_id}")

    # ------------------------------------------------------------------
    # 上下文管理器支持
    # ------------------------------------------------------------------

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.logout()
