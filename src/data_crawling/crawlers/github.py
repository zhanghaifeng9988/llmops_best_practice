import json
import os
import shutil
import subprocess
import tempfile

from aws_lambda_powertools import Logger
from core.db.documents import RepositoryFileDocument

from crawlers.base import BaseCrawler

logger = Logger(service="llmops-best-practice/crawler")

MAX_FILE_BYTES = 200_000

class GithubCrawler(BaseCrawler):
    model = RepositoryFileDocument

    def __init__(self, ignore=(".git", ".toml", ".lock", ".png", ".env")) -> None:
        super().__init__()
        self._ignore = ignore
        self._ignore_dirs = (".git", "node_modules", "__pycache__", ".venv")
        self._binary_suffixes = (
            ".jpg", ".jpeg", ".gif", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
            ".ppt", ".pptx", ".zip", ".gz", ".tar", ".node", ".dwg", ".h5",
            ".bin", ".exe", ".dll", ".so", ".woff", ".woff2", ".ttf", ".ico",
            ".mp3", ".mp4",
        )

    def extract(self, link: str, **kwargs) -> None:
        logger.info(f"Starting scrapping GitHub repository: {link}")

        repo_name = link.rstrip("/").split("/")[-1].removesuffix(".git")
        local_temp = tempfile.mkdtemp()

        try:
            repo_path = os.path.join(local_temp, repo_name)
            subprocess.run(
                ["git", "clone", "--depth", "1", link, repo_path],
                check=True,
                capture_output=True,
                text=True,
            )
# os.walk 遍历仓库每个目录，内层循环逐文件过五关：
# #过滤 ignore → 大小帽 → 按文件去重 → 提取（ipynb 取 cell 源码 / 其他读全文）→ 生成一条文档。最后 bulk_insert 一次批量入库。一文件一文档
            docs = []
            updated = 0
            for root, dirs, files in os.walk(repo_path):
                dirs[:] = [d for d in dirs if d not in self._ignore_dirs]
                dir = root.replace(repo_path, "").lstrip("/")
                if dir.startswith(self._ignore):
                    continue

                for file in files:
                    if file.endswith(self._ignore) or file.lower().endswith(self._binary_suffixes):
                        continue
                    file_path = os.path.join(dir, file)
                    full_path = os.path.join(root, file)

                    if os.path.getsize(full_path) > MAX_FILE_BYTES:
                        logger.warning(f"Skipping oversized file: {file_path}")
                        continue

                    if file.endswith(".ipynb"):
                        with open(full_path, "r", errors="ignore") as f:
                            nb = json.load(f)
                        cells = []
                        for cell in nb.get("cells", []):
                            src = "".join(cell.get("source", []))
                            if src.strip():
                                cells.append(f"[{cell.get('cell_type')}]\n{src}")
                        text = "\n\n".join(cells)
                    else:
                        with open(full_path, "r", errors="ignore") as f:
                            text = f.read()
                    # find 从 Mongo 查出老文档，from_mongo 把它还原成对象——带着原来的 id（那个 UUID）。这个 id 就是老文档在库里的身份证号。
                    existing = self.model.find(repo_link=link, file_path=file_path)
                    if existing:
                        if existing.content == text: # 如果内容没变，就跳过
                            continue
                        existing.content = text
                        existing.update()
                        updated += 1
                        continue

                    docs.append(
                        self.model(
                            repo_name=repo_name,
                            repo_link=link,
                            file_path=file_path,
                            content=text,
                            owner_id=kwargs.get("user"),
                        )
                    )

            if not docs and not updated:
                logger.info(f"No new or changed files for repository: {link}")
                return
    
            if docs:
                self.model.bulk_insert(docs)

        except subprocess.CalledProcessError as e:
            logger.error(f"Git clone failed for {link}: {e.stderr}")
            raise
        finally:
            shutil.rmtree(local_temp)

        logger.info(f"Finished scrapping GitHub repository: {link}, {len(docs)} new, {updated} updated")