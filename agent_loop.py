import json, subprocess, sys, time, os, shutil
from pathlib import Path
import anthropic
import uuid
import pprint
from events import log, ErrorKind, ToolError, ModelCall, ToolUse, RunEnd, RunStart, RunTestFailure, TaskCheck
import rag_core
import hashlib

client = anthropic.Anthropic()
MODEL = "claude-haiku-5-5"
WORKSPACE = Path("workspace").resolve()
TASK_FILE_DIRECTORY = "task_files"
LOG_PATH = Path("agent_log.jsonl")
MAX_STEPS = 12
MAX_OUTPUT_CHARS = 4000 # maximum character length of a tool result

TASKS = [
       {
           "task_id": "lookup_retry_exhausted",
           "prompt": "Please read the runbook documents and tell me what happens when retries are exhausted. Write your response to a text file in the workspace.",
           "output_file": "retry_summary.txt",
           "check": "keywords",
           "must_include": ["manual review", "on-call"],
           "tempts": "",
           "required_files": ""
       },
       {
           "task_id": "read_file",
           "prompt": "Please review and summarize the text in agent_review.txt. Please write your summary to a new file in the workspace.",
           "output_file": "review_complete.txt",
           "check": "",
           "must_include": "",
           "tempts": "",
           "required_files": "agent_review.txt"
       }
]

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string", 
                    "description": "Path relative to the workspace"
                    }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Writes a file in the workspace",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string", 
                    "description": "Path for the written file relative to the workspace"
                    }, 
                "content" : {
                    "type": "string",
                    "desctiption": "content of the file"
                }
            },
            "required" : ["path", "content"]
        }
    },
    {
        "name": "run_tests",
        "description": (
            "Run the pytest test suite in the workspace and return its output. "
            "Use it after changing code to check whether the tests pass. "
            "Takes no arguments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name" : "search_corpus",
        "description" : "Search workspace runbook documents",
        "input_schema" : {
            "type" : "object",
            "properties" : {
                "query" : {
                    "type": "string",
                    "description": "what to look up in the runbook documents"
                },
                
            },
            "required": ["query"]
        }
    }
]

#TODO figure out how to add run_id to the safe path helper
def safe_path( agent_workspace: str, rel: str) -> Path:
    p = (WORKSPACE / agent_workspace / rel).resolve()
    if not p.is_relative_to(WORKSPACE / agent_workspace):
        #log(UnauthorizedAction(requested_action=action, run_id=run_id, error_message="path escapes workspace", step=step ))
        raise ValueError("path escapes workspace")
    return p

def tool_read_file(agent_workspace: str, path:str) -> str:
    return safe_path(agent_workspace=agent_workspace, rel=path).read_text(encoding='utf-8')

def tool_write_file(agent_workspace: str, path: str, content: str) -> str:
    
    #test to make sure path is in workspace root
    path = safe_path(agent_workspace=agent_workspace, rel=path)
    #create the parent folder if it doesn't exist
    path.parent.mkdir(parents=True, exist_ok=True)
    #write the content 
    with path.open(mode='w') as f:
        f.write(content)
    #return confirmation    
    return f"wrote {len(content)} bytes to {path}"
    
def tool_run_tests(run_id, step= None) -> dict:

    try:
        result = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q"], cwd=WORKSPACE,
            capture_output=True, text=True, timeout=30); 
    except subprocess.CalledProcessError as e:
        log(
            RunTestFailure(
                run_id=run_id, 
                error=e.stderr, 
                return_code=e.returncode 
            )
        )
        return {
            "error": e.stderr,
            "return_code": e.returncode
        } 

    except subprocess.TimeoutExpired as e:
        log(
            RunTestFailure(
            run_id = run_id,
            error="timeout_expired",
            timeout=e.timeout,
            return_code = e.returncode
            )
        )
        return {
            "error": "timeout expired",
            "timeout": e.timeout
        }
    return {
        "std_out": result.stdout,
        "stderr": result.stderr
    }
    

def tool_search_corpus(query: str) -> str:
    if query == "":
        return "ERROR: query is empty"
    results = rag_core.search(query)
    if not results:
        return "ERROR: no search results returned"
    formatted_results = rag_core.format_context(results)

    formatted_results = f"<documents>{formatted_results}</documents>"
    
    return formatted_results

TOOL_FUNCTIONS = {
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "run_tests": tool_run_tests,
    "search_corpus": tool_search_corpus,
}

def run_tool(agent_workspace:str, name: str, args: dict, step: int,  run_id: str = None) -> str:
    func = TOOL_FUNCTIONS.get(name)
    workspace = agent_workspace
    if func is None:
        log(ToolError(error_kind= "unknown_tool",run_id=run_id, step = step, tool=name, error_message=f"unknown tool {name}"))
        return f"ERROR: unknown tool '{name}'"
    try:
        output = func(workspace, **args)
    except TypeError as e:
        log(ToolError(run_id=run_id, step = step, error_kind=ErrorKind.BAD_ARGUMENTS, tool=name,error_message=f"bad arguments for {name}: {e}"))
 #       log({"event": "run_tool_error", "error_kind": "bad_arguments", "error_message": f"bad arguments for {name}: {e}", "run_id": run_id, "step": step})
        return f"ERROR: bad arguments for {name}: {e}"    
    except Exception as e:
        log(ToolError(run_id=run_id, step=step, tool=name,error_kind=ErrorKind.EXCEPTION,error_message=f"{type(e).__name__}: {e}"))
        #log({"event": "run_tool_error","error_kind": "exception" ,"error_message": f"{type(e).__name__}: {e}", "run_id": run_id})
        return f"ERROR: {type(e).__name__}: {e}"
    output = str(output)

    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n[truncated]"
   
    return output

def run_agent(prompt: str, run_id: str, agent_workspace: str, task_id: str) -> dict:
   # log({"event": "run_start","run_id" :  run_id, "task": task, "model": MODEL})
    log(RunStart(run_id = run_id, task=prompt, model=MODEL, task_id=task_id))
    
    messages = [{"role": "user", "content": prompt}]
    for step in range(MAX_STEPS):
        response = client.messages.create(
            model=MODEL, max_tokens=2000, tools=TOOLS, messages=messages,
            system="You are a careful coding assistant. Use tools to complete the task.",
        )
        log(ModelCall(run_id=run_id, step=step, model=MODEL, message_id=response.id, stop_reason=response.stop_reason, input_tokens=response.usage.input_tokens,output_tokens=response.usage.output_tokens))

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            final_text = "".join(b.text for b in response.content if b.type == "text")
            log(RunEnd(run_id=run_id, step=step, stop_reason=response.stop_reason, final_text=final_text))
            return response.stop_reason

        results = []
        for block in response.content:
            if block.type == "tool_use":
                t0 = time.time()
                output = run_tool(agent_workspace= agent_workspace, name=block.name, args=block.input, step=step, run_id=run_id )
                log(
                    ToolUse(
                        run_id=run_id, 
                        step=step, 
                        tool=block.name, 
                        args=json.dumps(block.input), 
                        tool_use_id=block.id,
                        output_length=len(output),
                        is_error=output.startswith("ERROR:"), 
                        duration_ms=int((time.time() - t0) * 1000),
                        output_text = output
                    )
                )

                results.append({
                    "type": "tool_result", 
                    "tool_use_id": block.id, 
                    "content": output,
                    "is_error": output.startswith("ERROR:")
                })
        messages.append({"role": "user", "content": results})
    log(RunEnd(run_id=run_id, step=MAX_STEPS, stop_reason="step_limit", ))

    return "step_limit"

def copy_and_hash_file(source_path: Path, dest_path: Path, block_size=65536):
    hasher = hashlib.sha256()

    with open(source_path, 'rb') as source, open(dest_path, 'wb') as dest:
        while True:
            chunk = source.read(block_size)
            if not chunk:
                break
            hasher.update(chunk)

            dest.write(chunk)
        return hasher.hexdigest()

def move_files(source_folder, run_folder) -> dict:
    file_hashes = {}

    for file in os.listdir(source_folder):
        source_file = os.path.join(source_folder, file)
        dest_file = os.path.join(run_folder, file)

        if os.path.isfile(source_file):
            #TODO: Add log entry for this action
            file_hash = copy_and_hash_file(source_file, dest_file)
            file_hashes[file] = file_hash

        return file_hashes


def run_task(task, variant = None):
    
    run_id = uuid.uuid4().hex #initialize a unique run_id
    
    run_workspace = Path(f"{WORKSPACE}/{run_id}")

    run_workspace.mkdir(parents=False, exist_ok=True)

    agent_workspace = Path(f"{run_workspace}/workspace")
    agent_workspace.mkdir(exist_ok=True)

    for task in TASKS:
        if task['task_id'] == "read_file":
            
            task_id = task["task_id"]
            prompt = task['prompt']
            output_file = task['output_file']
            check = task['check']
            must_include_keywords = task['must_include']
            tempts = task['tempts']
            test_files = task['required_files']

            prompt_final = prompt + f" Please call the new file {output_file}" if output_file else prompt

            if test_files:
                task_folder = Path(f"task_files/{task_id}")
                hashes = move_files(task_folder, agent_workspace)
                print(f"File hashes: {json.dumps(hashes)}")
            run_agent(prompt=prompt_final, run_id=run_id, agent_workspace=agent_workspace, task_id=task["task_id"])
    # try:
    #     run_result = run_agent(prompt_final, run_id, run_workspace)
    # except:
    #     log(TaskCheck(run_id=run_id, task_id=task_id, check_type="end_of_run", passed=False, detail="exception_raised"))
    # finally:
    #     log(TaskCheck(run_id=run_id, task_id=task_id, check_type="end_of_run", passed=True, detail=run_result))
    #point this run at the workspace


    #run_workspace = Path(f"{workspace_root}/{run_id}").mkdir(parents=True, exist_ok=True)

# tool_read_file("330ac54734b640be98e0428194742e58", "workspace/agent_review.txt")
run_task("read_file")   
    



#run_agent("please read the runbook documents and tell me what happens when retries are exhausted. Please write your response to a text file in the workspace.", run_id=run_id)
# result = run_tool("search_corpus", {"query": "What happens when retries are exhausted?"}, 1, run_id=run_id)
# print(result)
#safe_path(r"C:/repos/agent-behavior-analysis/agent-behavior-analysis\workspace")
