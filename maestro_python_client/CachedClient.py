from typing import List, Tuple
from uuid import uuid4

from maestro_python_client.Cache.Cache import Cache
from maestro_python_client.Client import Client, Task


class CachedClient(Client):
    def __init__(
        self,
        maestro_endpoint: str,
        cache: Cache,
        cached_queues: list[str] = [],
        completed_task_ttl=900,
        **kwargs,
    ) -> None:
        super().__init__(maestro_endpoint, **kwargs)
        self.__cached_queues: set[str] = set(cached_queues)
        self.__cache = cache
        self.__completed_task_ttl = completed_task_ttl

    def launch_task(
        self,
        owner: str,
        queue: str,
        task_payload: str,
        start_timeout: int,
        retries: int = 0,
        timeout: int = 900,
        executes_in: int = 0,
    ) -> str:
        ttl = (
            executes_in
            + self.__completed_task_ttl
            + (start_timeout + timeout) * (retries + 1)
        )
        task_payload = self.__cache_payload(
            queue,
            task_payload,
            ttl,
        )
        return super().launch_task(
            owner, queue, task_payload, retries, timeout, executes_in, start_timeout
        )

    def next(self, queue: str) -> Task | None:
        task = super().next(queue)
        return self.__task_from_cache(task)

    def consume(self, queue: str) -> Task | None:
        task = super().consume(queue)
        return self.__task_from_cache(task)

    def task_state(self, task_id: str) -> Task:
        task = super().task_state(task_id)
        return self.__task_from_cache(task)  # type: ignore

    def complete_task(self, task_id: str, result: str) -> None:
        task = super().task_state(task_id)

        self.__set_ttl(task.task_queue, task.payload, self.__completed_task_ttl)
        result = self.__cache_payload(
            task.task_queue, result, self.__completed_task_ttl
        )

        super().complete_task(task_id, result)

    def cancel_task(self, task_id: str) -> None:
        task = super().task_state(task_id)
        self.__set_ttl(task.task_queue, task.payload, self.__completed_task_ttl)

        super().cancel_task(task_id)

    def fail_task(self, task_id: str) -> None:
        task = super().task_state(task_id)
        self.__set_ttl(task.task_queue, task.payload, self.__completed_task_ttl)

        super().fail_task(task_id)

    def delete_task(self, task_id: str) -> None:
        task = super().task_state(task_id)
        self.__delete(task.task_queue, task.payload)
        if task.result:
            self.__delete(task.task_queue, task.result)

        super().fail_task(task_id)

    def launch_task_list(
        self,
        tasks: List[Tuple[str, str, str]],
        start_timeout: int,
        retries: int = 0,
        timeout: int = 900,
        executes_in: int = 0,
    ) -> List[str]:
        payload_ttl = (
            executes_in
            + self.__completed_task_ttl
            + (start_timeout + timeout) * (retries + 1)
        )

        for i, (owner, queue, payload) in enumerate(tasks):
            tasks[i] = (
                owner,
                queue,
                self.__cache_payload(
                    queue,
                    payload,
                    payload_ttl,
                ),
            )

        return super().launch_task_list(
            tasks, retries, timeout, executes_in, start_timeout
        )

    def __task_from_cache(self, task: Task | None) -> Task | None:
        if not task:
            return task

        task.payload = self.__payload_from_cache(task.task_queue, task.payload)

        if task.result:
            task.result = self.__payload_from_cache(task.task_queue, task.result)

        return task

    def __cache_payload(self, queue: str, payload: str, timeout: int = 0) -> str:
        if queue not in self.__cached_queues:
            return payload

        cache_key = self.__unique_key(queue)
        self.__cache.put(cache_key, payload, timeout)
        return cache_key

    def __payload_from_cache(self, queue: str, payload: str) -> str:
        if queue not in self.__cached_queues:
            return payload

        return self.__cache.get(payload)

    def __set_ttl(self, queue: str, key: str, ttl: int):
        if queue not in self.__cached_queues:
            return

        self.__cache.set_ttl(key, ttl)

    def __delete(self, queue: str, key: str):
        if queue not in self.__cached_queues:
            return

        self.__cache.delete(key)

    @staticmethod
    def __unique_key(queue_name: str) -> str:
        return f"maestro-cache-{queue_name}-{str(uuid4())}"
