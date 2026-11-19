import re

from aws_lambda_powertools import Logger
from crawlers.base import BaseCrawler
from crawlers.custom_article import CustomArticleCrawler

logger = Logger(service="llmops_best_practice/crawler")

# 爬虫分发器：根据 URL 决定用哪个爬虫类去抓取，并返回爬虫实例。整体是「注册表 + 正则匹配」的模式。
# 注册时存类、分发时实例化、调用时多态
class CrawlerDispatcher:
    def __init__(self) -> None:
        self._crawlers = {} # 初始化一个空字典，用来存「URL 正则 → 爬虫类」的映射。

    def register(self, domain: str, crawler: type[BaseCrawler]) -> None:
        self._crawlers[r"https://(www\.)?{}.com/*".format(re.escape(domain))] = crawler

# 
    def get_crawler(self, url: str) -> BaseCrawler:
        for pattern, crawler in self._crawlers.items():
            if re.match(pattern, url):
                return crawler()
        else:
            logger.warning(
                f"No crawler found for {url}. Defaulting to CustomArticleCrawler."
            )

            return CustomArticleCrawler()