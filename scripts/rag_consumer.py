# 一个 RabbitMQ 消费者（worker），从消息队列里一条条收“仓库文件变更”的消息，
# 把文件内容切块、编码成向量，然后“先删旧向量、再插新向量”地同步进 Milvus，
# 实现增量更新。


import json
import pika
from pymilvus import MilvusClient
from sentence_transformers import SentenceTransformer

from build_vector_index import COLLECTION, chunk_text
from core.config import settings


def main() -> None:
    model = SentenceTransformer(settings.EMBEDDING_MODEL_ID, device=settings.EMBEDDING_MODEL_DEVICE)
    client = MilvusClient(settings.MILVUS_LITE_PATH)
    if not client.has_collection(COLLECTION):
        raise SystemExit("集合不存在，先跑 build_vector_index.py 建库")
    client.load_collection(COLLECTION)

    credentials = pika.PlainCredentials(settings.RABBITMQ_DEFAULT_USERNAME, settings.RABBITMQ_DEFAULT_PASSWORD)
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host=settings.RABBITMQ_HOST, port=settings.RABBITMQ_PORT, credentials=credentials)
    )
    channel = connection.channel()
    channel.queue_declare(queue=settings.RABBITMQ_QUEUE_NAME, durable=True)
    # 一次只取一条，处理完 ack 再取下一条，避免消息堆积在单个 worker 内存里。
    channel.basic_qos(prefetch_count=1)

    def callback(ch, method, properties, body): # 定义每收到一条消息做什么
        msg = json.loads(body)
        data_type = msg.get("type")
        file_path = msg.get("file_path", "")
        try:
            if data_type != "repository_files":
                print(f"跳过非仓库文件类型: {data_type}")
            else:
                chunks = chunk_text(msg.get("content", ""))
                if not chunks:
                    print(f"无有效切块，跳过: {file_path}")
                else: # 批量把切块编码成归一化向量。
                    vectors = model.encode(chunks, normalize_embeddings=True)
                    rows = [ # 每块一行，字段与建库脚本的 schema 对齐
                        {
                            "content": c,
                            "vector": v.tolist(),
                            "repo_name": msg.get("repo_name", ""),
                            "file_path": file_path,
                            "owner_id": str(msg.get("owner_id", "")),
                        }
                        for c, v in zip(chunks, vectors)
                    ]
                    # 先按 file_path 删除该文件所有旧向量，再插入新向量。
                    client.delete(COLLECTION, filter=f'repo_name == "{msg.get("repo_name", "")}" and file_path == "{file_path}"')
                    client.insert(COLLECTION, rows)
                    print(f"已向量化 {len(rows)} 块: {file_path}")
        except Exception as e:
            print(f"处理失败 {file_path}: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(queue=settings.RABBITMQ_QUEUE_NAME, on_message_callback=callback)
    print("消费者就绪，等待消息... (Ctrl+C 退出)")
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    connection.close()


if __name__ == "__main__":
    main()