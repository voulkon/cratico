from loguru import logger


def log_task_start(task_name, **kwargs):
    logger.info(f"Starting {task_name} with args: {kwargs}")
