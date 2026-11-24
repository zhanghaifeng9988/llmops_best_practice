import os
import shutil
import subprocess
import tempfile

from aws_lambda_powertools import Logger
from core.db.documents import RepositoryDocument

from crawlers.base import BaseCrawler

logger = Logger(service="llmops-best-practice/crawler")


# class GithubCrawler(BaseCrawler):
#     model = RepositoryDocument

#     def __init__(self, ignore=(".git", ".toml", ".lock", ".png")) -> None:
#         super().__init__()
#         self._ignore = ignore

#     def extract(self, link: str, **kwargs) -> None:
#         logger.info(f"Starting scrapping GitHub repository: {link}")

#         repo_name = link.rstrip("/").split("/")[-1]

#         local_temp = tempfile.mkdtemp()

#         try:
#             os.chdir(local_temp)
#             subprocess.run(["git", "clone", link])

#             repo_path = os.path.join(local_temp, os.listdir(local_temp)[0])

#             tree = {}
#             for root, dirs, files in os.walk(repo_path):
#                 dir = root.replace(repo_path, "").lstrip("/")
#                 if dir.startswith(self._ignore):
#                     continue

#                 for file in files:
#                     if file.endswith(self._ignore):
#                         continue
#                     file_path = os.path.join(dir, file)
#                     with open(os.path.join(root, file), "r", errors="ignore") as f:
#                         tree[file_path] = f.read()

#             instance = self.model(
#                 name=repo_name, link=link, content=tree, owner_id=kwargs.get("user")
#             )
#             instance.save()

#         except Exception:
#             raise
#         finally:
#             shutil.rmtree(local_temp)

#         logger.info(f"Finished scrapping GitHub repository: {link}")
# ... existing code ...
class GithubCrawler(BaseCrawler):
    model = RepositoryDocument

    def __init__(self, ignore=(".git", ".toml", ".lock", ".png", ".env")) -> None:
        super().__init__()
        self._ignore = ignore

    def extract(self, link: str, **kwargs) -> None:
        old_model = self.model.find(link=link)
        if old_model is not None:
            logger.info(f"Repository already exists in the database: {link}")
            return

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

            tree = {}
            for root, dirs, files in os.walk(repo_path):
                dir = root.replace(repo_path, "").lstrip("/")
                if dir.startswith(self._ignore):
                    continue

                for file in files:
                    if file.endswith(self._ignore):
                        continue
                    file_path = os.path.join(dir, file)
                    with open(os.path.join(root, file), "r", errors="ignore") as f:
                        tree[file_path] = f.read()

            if not tree:
                logger.warning(f"No extractable files in repository: {link}")
                return

            instance = self.model(
                name=repo_name, link=link, content=tree, owner_id=kwargs.get("user")
            )
            instance.save()

        except subprocess.CalledProcessError as e:
            logger.error(f"Git clone failed for {link}: {e.stderr}")
            raise
        finally:
            shutil.rmtree(local_temp)

        logger.info(f"Finished scrapping GitHub repository: {link}")