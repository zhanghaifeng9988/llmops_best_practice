from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.typing import LambdaContext
from core import lib
from core.db.documents import UserDocument
from crawlers import CustomArticleCrawler, GithubCrawler
from dispatcher import CrawlerDispatcher

logger = Logger(service="llmops_best_practice/crawlers")

_dispatcher = CrawlerDispatcher()
_dispatcher.register("medium", CustomArticleCrawler)
#_dispatcher.register("linkedin", CustomArticleCrawler)
_dispatcher.register("github", GithubCrawler)


def handler(event, context: LambdaContext | None = None) -> dict[str, Any]:
    first_name, last_name = lib.split_user_full_name(event.get("user"))
# users表中，新建用户，查询已有用户，并返回用户的 "_id"
    user_id = UserDocument.get_or_create(first_name=first_name, last_name=last_name)

    link = event.get("link")
    # 根据link，获取对应的爬虫实例
    crawler = _dispatcher.get_crawler(link)

    try:
        crawler.extract(link=link, user=user_id)

        return {"statusCode": 200, "body": "Link processed successfully"}
    except Exception as e:
        return {"statusCode": 500, "body": f"An error occurred: {str(e)}"}


if __name__ == "__main__":
    event = {
        "user": "zhang haifeng",
        "link": "https://github.com/zhanghaifeng9988/llmops_best_practice.git",
    }
    handler(event, None)