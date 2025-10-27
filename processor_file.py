"""
Процессор для обработки объектов
"""
from typing import List, Optional, Callable
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from models import ProcessingObject, ProcessState
from state_machine import ObjectStateMachine
from operations import OperationFactory
from s3_service import S3Service


logger = logging.getLogger(__name__)


class ObjectProcessor:
    """Процессор для выполнения операций над объектами"""
    
    def __init__(self, session: AsyncSession, s3_service: S3Service):
        """
        Инициализация процессора
        
        Args:
            session: Сессия базы данных
            s3_service: Сервис для работы с S3
        """
        self.session = session
        self.s3_service = s3_service
        self.operation_factory = OperationFactory()
    
    async def process_object(
        self,
        obj_id: str,
        operations: List[str],
        progress_callback: Optional[Callable] = None
    ):
        """
        Обрабатывает объект, выполняя указанные операции
        
        Args:
            obj_id: ID объекта
            operations: Список операций для выполнения
            progress_callback: Callback для отправки обновлений прогресса
        """
        # Получаем объект из БД
        result = await self.session.execute(
            select(ProcessingObject).where(ProcessingObject.id == obj_id)
        )
        obj = result.scalar_one_or_none()
        
        if not obj:
            logger.error(f"Object {obj_id} not found")
            return
        
        logger.info(f"Starting processing for object {obj.identifier} (ID: {obj_id})")
        
        # Создаем state machine с текущим состоянием
        state_machine = ObjectStateMachine(initial_state=obj.state.value)
        
        try:
            # Переводим в состояние PROCESSING
            if state_machine.can_transition('start_processing'):
                state_machine.start_processing()
                obj.state = ProcessState.PROCESSING
                await self.session.commit()
                logger.info(f"Object {obj.identifier} moved to PROCESSING state")
            else:
                logger.warning(f"Cannot start processing for object {obj.identifier} in state {obj.state}")
                return
            
            # Выполняем операции последовательно
            total_operations = len(operations)
            
            for idx, operation_type in enumerate(operations):
                logger.info(f"Processing operation {operation_type} ({idx + 1}/{total_operations}) for {obj.identifier}")
                
                # Обновляем прогресс
                obj.current_operation = operation_type
                obj.progress = {
                    "current": idx + 1,
                    "total": total_operations,
                    "message": f"Executing {operation_type}"
                }
                await self.session.commit()
                
                # Отправляем обновление прогресса через callback
                if progress_callback:
                    await progress_callback(obj.to_dict())
                
                # Проверяем, не выполнена ли уже операция
                operations_status = obj.operations_status or {}
                if operations_status.get(operation_type, {}).get("completed"):
                    logger.info(f"Operation {operation_type} already completed for {obj.identifier}, skipping")
                    continue
                
                # Создаем и выполняем операцию
                try:
                    operation = self.operation_factory.create_operation(
                        operation_type,
                        self.s3_service
                    )
                    
                    result = await operation.execute(obj.to_dict(), obj.identifier)
                    
                    # Сохраняем результат операции
                    operations_status[operation_type] = result
                    obj.operations_status = operations_status
                    
                    # Обновляем ссылки на артефакты в S3
                    s3_artifacts = obj.s3_artifacts or {}
                    s3_artifacts[operation_type] = result.get("s3_url")
                    obj.s3_artifacts = s3_artifacts
                    
                    await self.session.commit()
                    
                    logger.info(f"Operation {operation_type} completed successfully for {obj.identifier}")
                    
                except Exception as op_error:
                    logger.error(f"Error executing operation {operation_type} for {obj.identifier}: {op_error}")
                    raise
            
            # Все операции завершены успешно
            if state_machine.can_transition('complete'):
                state_machine.complete()
                obj.state = ProcessState.COMPLETED
                obj.current_operation = None
                obj.progress = {
                    "current": total_operations,
                    "total": total_operations,
                    "message": "All operations completed successfully"
                }
                await self.session.commit()
                
                if progress_callback:
                    await progress_callback(obj.to_dict())
                
                logger.info(f"Successfully processed object {obj.identifier} with {total_operations} operations")
        
        except Exception as e:
            logger.error(f"Error processing object {obj.identifier}: {e}", exc_info=True)
            
            # Переводим в состояние FAILED
            if state_machine.can_transition('fail'):
                state_machine.fail()
                obj.state = ProcessState.FAILED
                obj.error_message = str(e)
                await self.session.commit()
                
                if progress_callback:
                    await progress_callback(obj.to_dict())
                
                logger.error(f"Object {obj.identifier} moved to FAILED state")
    
    async def get_object_status(self, obj_id: str) -> Optional[dict]:
        """
        Получает текущий статус обработки объекта
        
        Args:
            obj_id: ID объекта
            
        Returns:
            Статус объекта или None если не найден
        """
        result = await self.session.execute(
            select(ProcessingObject).where(ProcessingObject.id == obj_id)
        )
        obj = result.scalar_one_or_none()
        
        if obj:
            return obj.to_dict()
        
        return None