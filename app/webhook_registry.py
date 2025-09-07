from typing import Callable

from celery import Task

# Registry to map a source name to its processing task
TASK_REGISTRY: dict[str, Task] = {}

# Registry to map a source name to its verification dependency
VERIFIER_REGISTRY: dict[str, Callable] = {}


def register_webhook(source: str, verifier: Callable, task: Task):
    """Registers a webhook source, its verifier, and its processing task."""
    if source in TASK_REGISTRY:
        raise ValueError(f"Source '{source}' is already registered.")

    TASK_REGISTRY[source] = task
    VERIFIER_REGISTRY[source] = verifier


def get_task(source: str) -> Task:
    task = TASK_REGISTRY.get(source)
    if not task:
        raise NotImplementedError(f"No task registered for source '{source}'.")
    return task


def get_verifier(source: str) -> Callable:
    verifier = VERIFIER_REGISTRY.get(source)
    if not verifier:
        raise NotImplementedError(f"No verifier registered for source '{source}'.")
    return verifier
