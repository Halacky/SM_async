# Updated operation_dependencies.py with English comments
"""
Operation dependencies management
"""
from typing import Dict, List, Set
from models import OperationType
import logging


logger = logging.getLogger(__name__)


class OperationDependencyGraph:
    """
    Operation dependencies graph
    
    Example:
    - TRANSFORM depends on VALIDATE
    - ENRICH depends on TRANSFORM
    - ANALYZE depends on ENRICH
    - EXPORT depends on ANALYZE
    """
    
    # Define dependencies: operation -> list of operations it depends on
    _dependencies: Dict[str, List[str]] = {
        OperationType.VALIDATE.value: [],  # Doesn't depend on anything
        OperationType.TRANSFORM.value: [OperationType.VALIDATE.value],
        OperationType.ENRICH.value: [OperationType.TRANSFORM.value],
        OperationType.ANALYZE.value: [OperationType.ENRICH.value],
        OperationType.EXPORT.value: [OperationType.ANALYZE.value],
    }
    
    @classmethod
    def get_dependencies(cls, operation: str) -> List[str]:
        """
        Get direct operation dependencies
        
        Args:
            operation: Operation name
            
        Returns:
            List of operations this operation depends on
        """
        return cls._dependencies.get(operation, [])
    
    @classmethod
    def get_all_dependencies(cls, operation: str) -> List[str]:
        """
        Get all operation dependencies (including transitive)
        
        Args:
            operation: Operation name
            
        Returns:
            List of all operations this operation depends on (in execution order)
        """
        visited = set()
        result = []
        
        def dfs(op: str):
            if op in visited:
                return
            visited.add(op)
            
            # Process dependencies first
            for dep in cls._dependencies.get(op, []):
                dfs(dep)
            
            # Then add the operation itself
            result.append(op)
        
        dfs(operation)
        
        # Remove the operation itself from result (keep only dependencies)
        if operation in result:
            result.remove(operation)
        
        return result
    
    @classmethod
    def resolve_execution_order(cls, operations: List[str]) -> List[str]:
        """
        Determine correct operation execution order considering dependencies
        
        Args:
            operations: List of requested operations
            
        Returns:
            Ordered list of operations to execute (including dependencies)
        """
        # Collect all operations including dependencies
        all_operations = set()
        
        for op in operations:
            # Add the operation itself
            all_operations.add(op)
            # Add all its dependencies
            all_operations.update(cls.get_all_dependencies(op))
        
        # Topological sort
        sorted_ops = cls._topological_sort(list(all_operations))
        
        logger.info(f"Resolved execution order for {operations}: {sorted_ops}")
        
        return sorted_ops
    
    @classmethod
    def _topological_sort(cls, operations: List[str]) -> List[str]:
        """
        Topological sort of operations
        
        Args:
            operations: List of operations to sort
            
        Returns:
            Sorted list
        """
        # Count incoming edges
        in_degree = {op: 0 for op in operations}
        
        for op in operations:
            for dep in cls._dependencies.get(op, []):
                if dep in in_degree:
                    in_degree[op] += 1
        
        # Queue of operations without dependencies
        queue = [op for op in operations if in_degree[op] == 0]
        result = []
        
        while queue:
            # Take operation without dependencies
            current = queue.pop(0)
            result.append(current)
            
            # For all operations that depend on current
            for op in operations:
                if current in cls._dependencies.get(op, []):
                    in_degree[op] -= 1
                    if in_degree[op] == 0:
                        queue.append(op)
        
        return result
    
    @classmethod
    def get_dependent_operations(cls, operation: str) -> List[str]:
        """
        Get operations that depend on this operation
        
        Args:
            operation: Operation name
            
        Returns:
            List of operations that depend on this operation
        """
        dependents = []
        
        for op, deps in cls._dependencies.items():
            if operation in deps:
                dependents.append(op)
        
        return dependents
    
    @classmethod
    def get_all_dependent_operations(cls, operation: str) -> List[str]:
        """
        Get all operations that directly or indirectly depend on this operation
        
        Args:
            operation: Operation name
            
        Returns:
            List of all dependent operations
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
        Check which operation dependencies are missing
        
        Args:
            operation: Operation name
            completed_operations: Dictionary of completed operations
            
        Returns:
            List of missing dependencies
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
        Validate dependency graph for cycles
        
        Returns:
            True if graph is valid (no cycles)
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


# Validate dependency graph on import
if not OperationDependencyGraph.validate_dependencies():
    raise ValueError("Invalid operation dependency graph: cycles detected!")