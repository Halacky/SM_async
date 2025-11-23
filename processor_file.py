# Updated processor.py with English comments
"""
Processor for object processing
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
    """Processor for executing operations on objects"""
    
    def __init__(self, session: AsyncSession, s3_service: S3Service):
        """
        Initialize processor
        
        Args:
            session: Database session
            s3_service: S3 service
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
        Processes object by executing specified operations
        
        Args:
            obj_id: Object ID
            operations: List of operations to execute
            progress_callback: Callback for progress updates
        """
        # Get object from database
        result = await self.session.execute(
            select(ProcessingObject).where(ProcessingObject.id == obj_id)
        )
        obj = result.scalar_one_or_none()
        
        if not obj:
            logger.error(f"Object {obj_id} not found")
            return
        
        logger.info(f"Starting processing for object {obj.identifier} (ID: {obj_id})")
        
        # Create state machine with current state
        state_machine = ObjectStateMachine(initial_state=obj.state.value)
        
        try:
            # Transition to PROCESSING state
            if state_machine.can_transition('start_processing'):
                state_machine.start_processing()
                obj.state = ProcessState.PROCESSING
                await self.session.commit()
                logger.info(f"Object {obj.identifier} moved to PROCESSING state")
            else:
                logger.warning(f"Cannot start processing for object {obj.identifier} in state {obj.state}")
                return
            
            # Execute operations sequentially
            total_operations = len(operations)
            
            for idx, operation_type in enumerate(operations):
                logger.info(f"Processing operation {operation_type} ({idx + 1}/{total_operations}) for {obj.identifier}")
                
                # Update progress
                obj.current_operation = operation_type
                obj.progress = {
                    "current": idx + 1,
                    "total": total_operations,
                    "message": f"Executing {operation_type}"
                }
                await self.session.commit()
                
                # Send progress update via callback
                if progress_callback:
                    await progress_callback(obj.to_dict())
                
                # Check if operation is already completed
                operations_status = obj.operations_status or {}
                if operations_status.get(operation_type, {}).get("completed"):
                    logger.info(f"Operation {operation_type} already completed for {obj.identifier}, skipping")
                    continue
                
                # Create and execute operation
                try:
                    operation = self.operation_factory.create_operation(
                        operation_type,
                        self.s3_service
                    )
                    
                    result = await operation.execute(obj.to_dict(), obj.identifier)
                    
                    # Save operation result
                    operations_status[operation_type] = result
                    obj.operations_status = operations_status
                    
                    # Update S3 artifact links
                    s3_artifacts = obj.s3_artifacts or {}
                    s3_artifacts[operation_type] = result.get("s3_url")
                    obj.s3_artifacts = s3_artifacts
                    
                    await self.session.commit()
                    
                    logger.info(f"Operation {operation_type} completed successfully for {obj.identifier}")
                    
                except Exception as op_error:
                    logger.error(f"Error executing operation {operation_type} for {obj.identifier}: {op_error}")
                    raise
            
            # All operations completed successfully
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
            
            # Transition to FAILED state
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
        Gets current object processing status
        
        Args:
            obj_id: Object ID
            
        Returns:
            Object status or None if not found
        """
        result = await self.session.execute(
            select(ProcessingObject).where(ProcessingObject.id == obj_id)
        )
        obj = result.scalar_one_or_none()
        
        if obj:
            return obj.to_dict()
        
        return None