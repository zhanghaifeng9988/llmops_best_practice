import time
from abc import ABC, abstractmethod
from tempfile import mkdtemp

from core.db.documents import BaseDocument
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

# 每个爬虫都必须绑定一个文档模型 model，并且必须实现 extract(link, **kwargs) 来完成爬取。
class BaseCrawler(ABC):
    model: type[BaseDocument]  # 类属性类型注解，model 的值必须是 BaseDocument 类本身
#子类要在这里绑定“我这个爬虫产出/操作哪种文档模型”。
    @abstractmethod 
    # extract 负责“执行爬取并落库”，不返回数据
    def extract(self, link: str, **kwargs) -> None: ...


class BaseAbstractCrawler(BaseCrawler, ABC):
    def __init__(self, scroll_limit: int = 5) -> None:
        options = webdriver.ChromeOptions()

        options.add_argument("--no-sandbox")
        options.add_argument("--headless=new")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--log-level=3")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument(f"--user-data-dir={mkdtemp()}")
        options.add_argument(f"--data-path={mkdtemp()}")
        options.add_argument(f"--disk-cache-dir={mkdtemp()}")
        options.add_argument("--remote-debugging-port=9226")

        self.set_extra_driver_options(options)

        self.scroll_limit = scroll_limit
        self.driver = webdriver.Chrome(
            options=options,
        )

    def set_extra_driver_options(self, options: Options) -> None:
        pass

    def login(self) -> None:
        pass

    def scroll_page(self) -> None:
        """Scroll through the LinkedIn page based on the scroll limit."""
        current_scroll = 0
        last_height = self.driver.execute_script("return document.body.scrollHeight")
        while True:
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            time.sleep(5)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height or (
                self.scroll_limit and current_scroll >= self.scroll_limit
            ):
                break
            last_height = new_height
            current_scroll += 1