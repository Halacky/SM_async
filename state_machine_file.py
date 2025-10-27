"""
State Machine для управления состояниями объекта
"""
from transitions import Machine
from models import ProcessState
import logging


logger = logging.getLogger(__name__)


class ObjectStateMachine:
    """
    State machine для управления жизненным циклом объекта
    
    Граф переходов:
    PENDING → QUEUED → PROCESSING → COMPLETED
                ↓           ↓
            CANCELLED   FAILED
                          ↓
                       QUEUED (retry)
    """
    
    # Все возможные состояния
    states = [state.value for state in ProcessState]
    
    # Конфигурация переходов
    transitions_config = [
        # Из PENDING в QUEUED
        {
            'trigger': 'queue',
            'source': ProcessState.PENDING.value,
            'dest': ProcessState.QUEUED.value,
            'before': 'on_queue'
        },
        
        # Из QUEUED в PROCESSING
        {
            'trigger': 'start_processing',
            'source': ProcessState.QUEUED.value,
            'dest': ProcessState.PROCESSING.value,
            'before': 'on_start_processing'
        },
        
        # Из PROCESSING в COMPLETED
        {
            'trigger': 'complete',
            'source': ProcessState.PROCESSING.value,
            'dest': ProcessState.COMPLETED.value,
            'before': 'on_complete'
        },
        
        # Из PROCESSING или QUEUED в FAILED
        {
            'trigger': 'fail',
            'source': [ProcessState.PROCESSING.value, ProcessState.QUEUED.value],
            'dest': ProcessState.FAILED.value,
            'before': 'on_fail'
        },
        
        # Из PENDING, QUEUED или PROCESSING в CANCELLED
        {
            'trigger': 'cancel',
            'source': [
                ProcessState.PENDING.value,
                ProcessState.QUEUED.value,
                ProcessState.PROCESSING.value
            ],
            'dest': ProcessState.CANCELLED.value,
            'before': 'on_cancel'
        },
        
        # Из FAILED в QUEUED (retry)
        {
            'trigger': 'retry',
            'source': ProcessState.FAILED.value,
            'dest': ProcessState.QUEUED.value,
            'before': 'on_retry'
        },
    ]
    
    def __init__(self, initial_state: str = ProcessState.PENDING.value):
        """
        Инициализация state machine
        
        Args:
            initial_state: Начальное состояние
        """
        self.machine = Machine(
            model=self,
            states=ObjectStateMachine.states,
            transitions=ObjectStateMachine.transitions_config,
            initial=initial_state,
            auto_transitions=False,
            send_event=True
        )
        logger.debug(f"State machine initialized with state: {initial_state}")
    
    def get_current_state(self) -> str:
        """Возвращает текущее состояние"""
        return self.state
    
    def can_transition(self, trigger: str) -> bool:
        """
        Проверяет, возможен ли переход
        
        Args:
            trigger: Название триггера
            
        Returns:
            True если переход возможен
        """
        try:
            available_triggers = self.machine.get_triggers(self.state)
            return trigger in available_triggers
        except Exception as e:
            logger.error(f"Error checking transition: {e}")
            return False
    
    def get_available_transitions(self) -> list:
        """Возвращает список доступных переходов"""
        try:
            return self.machine.get_triggers(self.state)
        except:
            return []
    
    # Callbacks для логирования переходов
    
    def on_queue(self, event):
        """Callback при переходе в QUEUED"""
        logger.info(f"State transition: {event.transition.source} → QUEUED")
    
    def on_start_processing(self, event):
        """Callback при переходе в PROCESSING"""
        logger.info(f"State transition: {event.transition.source} → PROCESSING")
    
    def on_complete(self, event):
        """Callback при переходе в COMPLETED"""
        logger.info(f"State transition: {event.transition.source} → COMPLETED")
    
    def on_fail(self, event):
        """Callback при переходе в FAILED"""
        logger.warning(f"State transition: {event.transition.source} → FAILED")
    
    def on_cancel(self, event):
        """Callback при переходе в CANCELLED"""
        logger.info(f"State transition: {event.transition.source} → CANCELLED")
    
    def on_retry(self, event):
        """Callback при retry"""
        logger.info(f"State transition: FAILED → QUEUED (retry)")