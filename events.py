import json, time 
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

LOG_PATH = Path("agent_log.jsonl")

class ErrorKind(str, Enum):
    UNKOWN_TOOL = "unknown_tool"
    BAD_ARGUMENTS = "bad_arguments"
    EXCEPTION = "exception"

class FileEventType(str, Enum):
    MOVE = "file_moved"
    HASH = "create_hash"
    DELETE = "file_deleted"
    CREATE = "file_created"

@dataclass(kw_only=True)
class Event:
    event: str
    run_id: str
    step: int | None = None

@dataclass(kw_only=True)
class ToolError(Event):
    event: str = "run_tool_error"
    tool: str 
    error_kind: ErrorKind
    error_message: str 
    def __post_init__(self):
        self.error_kind = ErrorKind(self.error_kind)

@dataclass(kw_only=True)
class RunStart(Event):
    event: str = "run_start"
    model: str 
    task_id: str
    
@dataclass(kw_only=True)
class ModelCall(Event):
    event: str = "model_call"
    model: str 
    stop_reason: str
    message_id: str
    input_tokens: int
    output_tokens: int 

@dataclass(kw_only=True)
class RunEnd(Event):
    event: str = "run_end"
    stop_reason: str
    final_text: str | None = None


@dataclass(kw_only=True)
class ToolUse(Event):
    event: str = "tool_use"
    tool: str 
    tool_use_id: str
    args: str
    output_length: int
    step: int | None = None
    is_error: bool
    duration_ms: float
    output_text: str

@dataclass(kw_only=True)
class RunTestFailure(Event):
    event: str = "run_test_failure"
    error: str
    return_code: int
    timeout: float | None = None

@dataclass(kw_only=True)
class TaskCheck(Event):
    event: str = "task_check"
    task_id: str
    check_type: str
    passed : bool
    detail: str 

@dataclass(kw_only=True)
class FileEvent(Event):
    event: str = "file_event"
    task_id: str
    event_type: FileEventType
    hash: str
    filename: str
    path: str
    def __post_init__(self):
        self.event_type = FileEventType(self.event_type)

@dataclass(kw_only=True)
class SetupError(Event):
    event: str = "setup_error"
    task_id: str
    detail: str

def log(e: Event):
    row = asdict(e)
    row["t"] = time.time()
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")
