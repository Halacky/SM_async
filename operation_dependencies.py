"""
Управление зависимостями операций
"""
from typing import Dict, List, Set
from models import OperationType
import logging


logger = logging.getLogger(__name__)


class OperationDependencyGraph:
    """
    Граф зависимостей операций
    
    Пример:
    - TRANSFORM зависит от VALIDATE
    - ENRICH зависит от TRANSFORM
    - ANALYZE зависит от ENRICH
    - EXPORT зависит от ANALYZE
    """
    
    # Определяем зависимости: операция -> список операций от которых она зависит
    _dependencies: Dict[str, List[str]] = {
        OperationType.VALIDATE.value: [],  # Не зависит ни от чего
        OperationType.TRANSFORM.value: [OperationType.VALIDATE.value],
        OperationType.ENRICH.value: [OperationType.TRANSFORM.value],
        OperationType.ANALYZE.value: [OperationType.ENRICH.value],
        OperationType.EXPORT.value: [OperationType.ANALYZE.value],
    }
    
    @classmethod
    def get_dependencies(cls, operation: str) -> List[str]:
        """
        Получает прямые зависимости операции
        
        Args:
            operation: Название операции
            
        Returns:
            Список операций от которых зависит данная операция
        """
        return cls._dependencies.get(operation, [])
    
    @classmethod
    def get_all_dependencies(cls, operation: str) -> List[str]:
        """
        Получает все зависимости операции (включая транзитивные)
        
        Args:
            operation: Название операции
            
        Returns:
            Список всех операций от которых зависит данная операция (в порядке выполнения)
        """
        visited = set()
        result = []
        
        def dfs(op: str):
            if op in visited:
                return
            visited.add(op)
            
            # Сначала обрабатываем зависимости
            for dep in cls._dependencies.get(op, []):
                dfs(dep)
            
            # Затем добавляем саму операцию
            result.append(op)
        
        dfs(operation)
        
        # Убираем саму операцию из результата (оставляем только зависимости)
        if operation in result:
            result.remove(operation)
        
        return result
    
    @classmethod
    def resolve_execution_order(cls, operations: List[str]) -> List[str]:
        """
        Определяет правильный порядок выполнения операций с учетом зависимостей
        
        Args:
            operations: Список запрошенных операций
            
        Returns:
            Упорядоченный список операций для выполнения (включая зависимости)
        """
        # Собираем все операции включая зависимости
        all_operations = set()
        
        for op in operations:
            # Добавляем саму операцию
            all_operations.add(op)
            # Добавляем все её зависимости
            all_operations.update(cls.get_all_dependencies(op))
        
        # Топологическая сортировка
        sorted_ops = cls._topological_sort(list(all_operations))
        
        logger.info(f"Resolved execution order for {operations}: {sorted_ops}")
        
        return sorted_ops
    
    @classmethod
    def _topological_sort(cls, operations: List[str]) -> List[str]:
        """
        Топологическая сортировка операций
        
        Args:
            operations: Список операций для сортировки
            
        Returns:
            Отсортированный список
        """
        # Подсчитываем входящие рёбра
        in_degree = {op: 0 for op in operations}
        
        for op in operations:
            for dep in cls._dependencies.get(op, []):
                if dep in in_degree:
                    in_degree[op] += 1
        
        # Очередь операций без зависимостей
        queue = [op for op in operations if in_degree[op] == 0]
        result = []
        
        while queue:
            # Берём операцию без зависимостей
            current = queue.pop(0)
            result.append(current)
            
            # Для всех операций, которые зависят от текущей
            for op in operations:
                if current in cls._dependencies.get(op, []):
                    in_degree[op] -= 1
                    if in_degree[op] == 0:
                        queue.append(op)
        
        return result
    
    @classmethod
    def get_dependent_operations(cls, operation: str) -> List[str]:
        """
        Получает операции, которые зависят от данной
        
        Args:
            operation: Название операции
            
        Returns:
            Список операций, которые зависят от данной
        """
        dependents = []
        
        for op, deps in cls._dependencies.items():
            if operation in deps:
                dependents.append(op)
        
        return dependents
    
    @classmethod
    def get_all_dependent_operations(cls, operation: str) -> List[str]:
        """
        Получает все операции, которые прямо или косвенно зависят от данной
        
        Args:
            operation: Название операции
            
        Returns:
            Список всех зависимых операций
        """
        visited = set()
        result = []
        
        def dfs(op: str):
            for dependent in cls.get_dependent_operations(op):
                if dependent not in visited:
                    visited.add(dependent)
                    result.append(dependent)
                    dfs(dependent)
        
        dfs(operation)
        return result
    
    @classmethod
    def check_missing_dependencies(
        cls,
        operation: str,
        completed_operations: Dict[str, bool]
    ) -> List[str]:
        """
        Проверяет какие зависимости операции отсутствуют
        
        Args:
            operation: Название операции
            completed_operations: Словарь завершённых операций
            
        Returns:
            Список отсутствующих зависимостей
        """
        dependencies = cls.get_all_dependencies(operation)
        missing = []
        
        for dep in dependencies:
            if not completed_operations.get(dep, {}).get("completed", False):
                missing.append(dep)
        
        return missing
    
    @classmethod
    def validate_dependencies(cls) -> bool:
        """
        Проверяет граф зависимостей на циклы
        
        Returns:
            True если граф валиден (нет циклов)
        """
        visited = set()
        rec_stack = set()
        
        def has_cycle(op: str) -> bool:
            visited.add(op)
            rec_stack.add(op)
            
            for dep in cls._dependencies.get(op, []):
                if dep not in visited:
                    if has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    return True
            
            rec_stack.remove(op)
            return False
        
        for op in cls._dependencies.keys():
            if op not in visited:
                if has_cycle(op):
                    logger.error(f"Cycle detected in dependency graph at operation: {op}")
                    return False
        
        return True


# Валидация графа зависимостей при импорте
if not OperationDependencyGraph.validate_dependencies():
    raise ValueError("Invalid operation dependency graph: cycles detected!")