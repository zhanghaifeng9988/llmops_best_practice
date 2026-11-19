import structlog

# structlog 包装，日志自动带上文件名，知道是哪个模块在说话
def get_logger(cls: str):
    return structlog.get_logger().bind(cls=cls)