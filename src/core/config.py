from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = str(Path(__file__).parent.parent.parent)

# 告诉 pydantic："去项目根目录按 UTF-8 读 .env 来填配置，.env 里多出来的变量别报错，忽略就行"
# 优先级：环境变量 > .env 文件 > 类里写的默认值
class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR + "/.env" , env_file_encoding="utf-8", extra="ignore") 
    # MongoDB configs
    MONGO_DATABASE_HOST: str = (
        "mongodb://mongo1:30001,mongo2:30002,mongo3:30003/?replicaSet=my-replica-set"
    )
    MONGO_DATABASE_NAME: str = "twin"

    # MQ config
    RABBITMQ_DEFAULT_USERNAME: str = "guest"
    RABBITMQ_DEFAULT_PASSWORD: str = "guest"
    RABBITMQ_HOST: str = "mq"
    RABBITMQ_PORT: int = 5673

    # QdrantDB config
    QDRANT_CLOUD_URL: str = "str"
    QDRANT_DATABASE_HOST: str = "qdrant"
    QDRANT_DATABASE_PORT: int = 6333
    USE_QDRANT_CLOUD: bool = False
    QDRANT_APIKEY: str | None = None

    # OpenAI config
    OPENAI_MODEL_ID: str = "qwen3.8-flash"
    OPENAI_API_KEY: str | None = None

    # CometML config
    COMET_API_KEY: str | None = None
    COMET_WORKSPACE: str | None = None
    COMET_PROJECT: str = "llm-twin"

    # AWS Authentication
    AWS_REGION: str = " "
    AWS_ACCESS_KEY: str | None = None
    AWS_SECRET_KEY: str | None = None
    AWS_ARN_ROLE: str | None = None

    # LLM Model config
    HUGGINGFACE_ACCESS_TOKEN: str | None = None
    MODEL_ID: str = "pauliusztin/LLMTwin-Llama-3.1-8B"
    DEPLOYMENT_ENDPOINT_NAME: str = "twin"

    MAX_INPUT_TOKENS: int = 1536  # Max length of input text.
    MAX_TOTAL_TOKENS: int = 2048  # Max length of the generation (including input text).
    MAX_BATCH_TOTAL_TOKENS: int = 2048  # Limits the number of tokens that can be processed in parallel during the generation.

    # Embeddings config
    EMBEDDING_MODEL_ID: str = "BAAI/bge-base-zh-v1.5"
    EMBEDDING_MODEL_MAX_INPUT_LENGTH: int = 512
    EMBEDDING_SIZE: int = 768
    EMBEDDING_MODEL_DEVICE: str = "cpu"

    # Milvus Lite config（嵌入式，数据存本地文件，无需容器）
    MILVUS_LITE_PATH: str = ROOT_DIR + "/data/milvus_lite.db"

    def patch_localhost(self) -> None:
        self.MONGO_DATABASE_HOST = "mongodb://localhost:30001,localhost:30002,localhost:30003/?replicaSet=my-replica-set"
        self.QDRANT_DATABASE_HOST = "localhost"
        self.RABBITMQ_HOST = "localhost"


settings = AppSettings()