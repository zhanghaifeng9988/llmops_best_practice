# 使用GithubCrawler，获取本地仓库数据
# 使用举例：PYTHONPATH=src:src/data_crawling uv run python scripts/ingest_local_repo.py \
#  "/mnt/d/Program Files/Notepad++/personnal-study-notes1/personal-study-notes"
import sys

from core.db.documents import UserDocument
from data_crawling.crawlers.github import GithubCrawler

repo_path = sys.argv[1]
user = UserDocument.find(first_name="zhang", last_name="haifeng")
if user is None:
    raise SystemExit("user not found in twin.users")

GithubCrawler().extract(repo_path, user=str(user.id))
print("ingest done")