# Updated state_machine.py with English comments
"""
State Machine for object state management
"""
from transitions import Machine
from models import ProcessState
import logging


logger = logging.getLogger(__name__)


class ObjectStateMachine:
    """
    State machine for managing object lifecycle
    
    Transition graph:
    PENDING → QUEUED → PROCESSING → COMPLETED
                ↓           ↓
            CANCELLED   FAILED
                          ↓
                       QUEUED (retry)
    """
    
    # All possible states
    states = [state.value for state in ProcessState]
    
    # Transition configuration
    transitions_config = [
        # From PENDING to QUEUED
        {
            'trigger': 'queue',
            'source': ProcessState.PENDING.value,
            'dest': ProcessState.QUEUED.value,
            'before': 'on_queue'
        },
        
        # From QUEUED to PROCESSING
        {
            'trigger': 'start_processing',
            'source': ProcessState.QUEUED.value,
            'dest': ProcessState.PROCESSING.value,
            'before': 'on_start_processing'
        },
        
        # From PROCESSING to COMPLETED
        {
            'trigger': 'complete',
            'source': ProcessState.PROCESSING.value,
            'dest': ProcessState.COMPLETED.value,
            'before': 'on_complete'
        },
        
        # From PROCESSING or QUEUED to FAILED
        {
            'trigger': 'fail',
            'source': [ProcessState.PROCESSING.value, ProcessState.QUEUED.value],
            'dest': ProcessState.FAILED.value,
            'before': 'on_fail'
        },
        
        # From PENDING, QUEUED or PROCESSING to CANCELLED
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
        
        # From FAILED to QUEUED (retry)
        {
            'trigger': 'retry',
            'source': ProcessState.FAILED.value,
            'dest': ProcessState.QUEUED.value,
            'before': 'on_retry'
        },
    ]
    
    def __init__(self, initial_state: str = ProcessState.PENDING.value):
        """
        Initialize state machine
        
        Args:
            initial_state: Initial state
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
        """Get current state"""
        return self.state
    
    def can_transition(self, trigger: str) -> bool:
        """
        Check if transition is possible
        
        Args:
            trigger: Trigger name
            
        Returns:
            True if transition is possible
        """
        try:
            available_triggers = self.machine.get_triggers(self.state)
            return trigger in available_triggers
        except Exception as e:
            logger.error(f"Error checking transition: {e}")
            return False
    
    def get_available_transitions(self) -> list:
        """Get list of available transitions"""
        try:
            return self.machine.get_triggers(self.state)
        except:
            return []
    
    # Callbacks for transition logging
    
    def on_queue(self, event):
        """Callback when transitioning to QUEUED"""
        logger.info(f"State transition: {event.transition.source} → QUEUED")
    
    def on_start_processing(self, event):
        """Callback when transitioning to PROCESSING"""
        logger.info(f"State transition: {event.transition.source} → PROCESSING")
    
    def on_complete(self, event):
        """Callback when transitioning to COMPLETED"""
        logger.info(f"State transition: {event.transition.source} → COMPLETED")
    
    def on_fail(self, event):
        """Callback when transitioning to FAILED"""
        logger.warning(f"State transition: {event.transition.source} → FAILED")
    
    def on_cancel(self, event):
        """Callback when transitioning to CANCELLED"""
        logger.info(f"State transition: {event.transition.source} → CANCELLED")
    
    def on_retry(self, event):
        """Callback on retry"""
        logger.info(f"State transition: FAILED → QUEUED (retry)")