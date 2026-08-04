# from arq import create_pool
# from arq.connections import ArqRedis, RedisSettings

# from config import config
from utilities.logger import get_logger

logger = get_logger(__name__)

# _pool: ArqRedis | None = None


class _NoOpArqPool:
    """Stand-in while Redis/Arq is disabled — enqueue_job is logged and
    skipped instead of connecting to Redis, so existing call sites
    (`pool = await get_arq_pool(); await pool.enqueue_job(...)`) don't need
    to change. Background processing (extraction/embedding/generation) will
    NOT run automatically until Redis is wired back up."""

    async def enqueue_job(self, function_name: str, *args, **kwargs):
        logger.warning(
            "Redis/Arq is disabled — skipped enqueue | function=%s args=%s", function_name, args
        )
        return None


async def get_arq_pool():
    """Redis is disabled for now — returns a no-op pool. Uncomment the real
    implementation below (and the imports above) to re-enable background jobs."""

    return _NoOpArqPool()

    # global _pool
    # if _pool is None:
    #     _pool = await create_pool(
    #         RedisSettings(host=config.redis.host, port=config.redis.port, database=config.redis.db)
    #     )
    # return _pool
