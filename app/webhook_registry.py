from celery import Task

# Registry to map a source name to its processing task
TASK_REGISTRY: dict[str, Task] = {}


def register_webhook(source: str, task: Task):
    """Registers a webhook source and its processing task."""
    if source in TASK_REGISTRY:
        raise ValueError(f"Source '{source}' is already registered.")

    TASK_REGISTRY[source] = task


def get_task(source: str) -> Task:
    task = TASK_REGISTRY.get(source)
    if not task:
        raise NotImplementedError(f"No task registered for source '{source}'.")
    return task
