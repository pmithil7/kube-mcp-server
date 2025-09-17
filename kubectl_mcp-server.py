import os
import logging
import subprocess
import json
import configparser
import tempfile
import atexit
from fastapi import FastAPI, HTTPException, Body, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv
from fastapi_mcp import FastApiMCP

# --- Configuration ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()  # Load environment variables from .env file

# List of actions to block the MCP to perform.
DESTRUCTIVE_COMMAND_BLOCKLIST = [
    "delete",
    "drain",
    "cordon",
    "uncordon",
    "label",
    "annotate",
    "taint",
    "apply",
    "patch",
    "replace",
    "edit",
    "set",
]

TEMP_DIR_PATH = os.environ.get("MCP_TEMP_DIR", None) # Default to None to let tempfile decide if not set

# Load kubeconfig content from INI and write to a temp file
ini_file_path = '/vault/secrets/kubectl.ini'
TEMP_KUBECONFIG_FILE = None

if os.path.exists(ini_file_path):
    logger.info(f"Reading kubeconfig content from '{ini_file_path}'")
    try:
        with open(ini_file_path, 'r', encoding='utf-8') as f:
            full_content = f.read()
        
        yaml_start_index = full_content.find('apiVersion: v1')
        
        if yaml_start_index != -1:
            kubeconfig_content = full_content[yaml_start_index:]
            
            with tempfile.NamedTemporaryFile(
                mode='w', 
                delete=False, 
                suffix='.yaml', 
                encoding='utf-8',
                dir=TEMP_DIR_PATH # <-- Use the specified directory
            ) as temp_file:
                temp_file.write(kubeconfig_content)
                TEMP_KUBECONFIG_FILE = temp_file.name
                logger.info(f"Kubeconfig content written to temporary file: {TEMP_KUBECONFIG_FILE}")
            
            def cleanup_temp_file():
                if TEMP_KUBECONFIG_FILE and os.path.exists(TEMP_KUBECONFIG_FILE):
                    os.remove(TEMP_KUBECONFIG_FILE)
                    logger.info(f"Cleaned up temporary kubeconfig file: {TEMP_KUBECONFIG_FILE}")
            
            atexit.register(cleanup_temp_file)
        else:
            logger.warning(f"Found '{ini_file_path}' but could not find 'apiVersion: v1' to start parsing.")

    except Exception as e:
        logger.error(f"Failed to read or process kubeconfig file '{ini_file_path}': {e}", exc_info=True)
else:
    logger.warning(f"INI file not found at '{ini_file_path}'. Using default kubectl configuration.")


app = FastAPI(
    title="Kube MCP Server",
    description="MCP Server that handles kubernetes tasks.",
    version="1.0.0"
)

# --- Pydantic Models for Request/Response ---
class MCPEntities(BaseModel):
    namespace: Optional[str] = ""  # Default namespace keeping empty for failure scenarios
    pod_name: Optional[str] = None
    deployment_name: Optional[str] = None
    resource_type: Optional[str] = None  # pods, deployments, services, etc.
    resource_name: Optional[str] = None
    command: Optional[str] = None  # For complex kubectl commands
    args: Optional[List[str]] = []  # Additional arguments for complex commands
    replicas: Optional[int] = None  # For scaling deployments
    kube_context: Optional[str] = None # For clusteer context management
    memory_threshold_percent: Optional[int] = 80 # Default of 80%

class MCPRequest(BaseModel):
    entities: MCPEntities
    slack_user_id: str
    slack_thread_ts: Optional[str] = None

# --- Helper Functions ---
def run_kubectl_command(command_args: List[str], kube_context: Optional[str] = None):
    """
    Execute a kubectl command and return the results.
    
    Args:
        command_args: List of arguments to pass to kubectl
        kube_context: Optional name of the kubectl context to use

    Returns:
        Dict with command output or error message
    """

    try:
        # Build the kubectl command
        kubectl_cmd = ["kubectl"]
        
        # Add context if provided
        if kube_context:
            kubectl_cmd.extend(["--context", kube_context]) # <--- Add context flag
            
        kubectl_cmd.extend(command_args)
        
        # Log the command being executed (but mask sensitive values)
        # Consider more robust sensitive value masking if command_args can contain secrets
        safe_cmd = " ".join(kubectl_cmd)
        logger.info(f"Executing kubectl command: {safe_cmd}")
        
        # Create a copy of the current environment
        cmd_env = os.environ.copy()
        
        if TEMP_KUBECONFIG_FILE:
            cmd_env['KUBECONFIG'] = TEMP_KUBECONFIG_FILE
        
        # Execute the command with the modified environment
        result = subprocess.run(
            kubectl_cmd,
            check=True,
            capture_output=True,
            text=True,
            env=cmd_env  # <-- Pass the prepared environment kubeconfig to the subprocess
        )
        
        # Process the output
        output = result.stdout.strip()
        return {"status": "success", "output": output}
    
    except subprocess.CalledProcessError as e:
        logger.error(f"kubectl command failed with context '{kube_context}': {e.stderr}")
        return {"status": "error", "message": e.stderr.strip()}
    
    except Exception as e:
        logger.error(f"Unexpected error executing kubectl command with context '{kube_context}': {str(e)}")
        return {"status": "error", "message": f"Unexpected error: {str(e)}"}

# --- API Endpoints ---
# ...
@app.post("/mcp/get_pods")
async def get_pods(request: MCPRequest = Body(...)):
    """Get pods in the specified namespace and context"""
    entities = request.entities
    namespace = entities.namespace
    kube_context = entities.kube_context # <--- Get context from entities
    
    logger.info(f"Received get_pods request for namespace: {namespace}, context: {kube_context} from user {request.slack_user_id}")
    
    # Build and execute kubectl command
    cmd_args = ["get", "pods", "-n", namespace, "-o", "wide"]
    result = run_kubectl_command(cmd_args, kube_context=kube_context) # <--- Pass context
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail={"status": "error", "message": result["message"]})
    
    return {
        "status": "success",
        "message": f"Pods in namespace {namespace} (context: {kube_context or 'default'}):",
        "details": result["output"]
    }

@app.post("/mcp/get_failing_pods")
async def get_failing_pods(request: MCPRequest = Body(...)):
    entities = request.entities
    namespace = entities.namespace
    kube_context = entities.kube_context
    
    logger.info(f"Received get_failing_pods request for namespace: {namespace}, context: {kube_context} from user {request.slack_user_id}")
    
    cmd_args = ["get", "pods", "-n", namespace, "-o", "json"]
    result = run_kubectl_command(cmd_args, kube_context=kube_context)
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail={"status": "error", "message": result["message"]})
    
    try:
        pods_data = json.loads(result["output"])
        problematic_pods_info = []

        for pod in pods_data.get("items", []):
            pod_metadata = pod.get("metadata", {})
            pod_name = pod_metadata.get("name", "")
            owner_references = pod_metadata.get("ownerReferences", [])
            # Check if the pod is part of a Job (CronJobs create Jobs)
            is_job_related_pod = any(ref.get("kind") == "Job" for ref in owner_references)

            pod_status_obj = pod.get("status", {})
            phase = pod_status_obj.get("phase", "") # e.g., Pending, Running, Succeeded, Failed, Unknown

            is_problematic = False
            reason_for_problem = ""

            # Rule 1: Pod phase itself indicates a failure
            if phase == "Failed":
                is_problematic = True
                reason_for_problem = "Pod phase is 'Failed'."
            elif phase == "Unknown":
                is_problematic = True
                reason_for_problem = "Pod phase is 'Unknown'."
            elif phase == "Pending" and not pod_status_obj.get("containerStatuses"):
                 # Pending for too long without container statuses can be an issue (e.g. unschedulable)
                 # For simplicity, we'll rely on container status checks for more specific pending issues for now
                 # but you could add a time-based check here if desired.
                 pass


            # Rule 2: Check container statuses for more granular issues
            # This is important for Running pods with problems, or Pending pods stuck.
            container_statuses = pod_status_obj.get("containerStatuses", [])
            for container in container_statuses:
                container_name = container.get("name", "")
                container_ready = container.get("ready", False)
                restart_count = container.get("restartCount", 0)
                container_state = container.get("state", {})

                if "waiting" in container_state:
                    wait_reason = container_state["waiting"].get("reason", "")
                    if wait_reason and wait_reason not in ["PodInitializing", "ContainerCreating"]: # These are normal startup states
                        # Specific critical waiting reasons
                        if wait_reason in ["CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError", "StartError", "SetupFailed"]:
                            is_problematic = True
                            reason_for_problem = f"Container '{container_name}' is waiting: {wait_reason}."
                
                elif "terminated" in container_state:
                    term_state = container_state["terminated"]
                    term_reason = term_state.get("reason", "")
                    term_exit_code = term_state.get("exitCode", -1)

                    # A container that terminated with non-zero exit code is a problem,
                    # UNLESS it's a Job pod that has Succeeded overall (handled by pod phase check)
                    if term_exit_code != 0:
                        is_problematic = True
                        reason_for_problem = f"Container '{container_name}' terminated with exit code {term_exit_code} (reason: {term_reason or 'Error'})."
                    elif term_reason == "Completed" and is_job_related_pod and phase == "Succeeded":
                         # This is a successfully completed container within a successfully completed Job pod. Not an issue.
                         # We want to avoid flagging this by subsequent checks.
                         # If we already decided the pod is NOT problematic based on Succeeded phase for a Job,
                         # we should ensure this container doesn't re-flag it.
                         if not is_problematic: # only if pod is not already marked problematic by phase
                            pass # It's fine
                    elif term_reason and term_reason not in ["Completed", "OOMKilled"]: # OOMKilled can be problematic but also an expected outcome for some jobs.
                                                                                # Let's flag other non-Completed reasons.
                        is_problematic = True
                        reason_for_problem = f"Container '{container_name}' terminated with reason: {term_reason}."


                # Rule 3: For pods in 'Running' phase, if a container is not ready.
                # (This should ideally not override a "Completed" Job pod's successful container)
                if phase == "Running" and not container_ready:
                    # If already marked problematic by a more specific reason, keep that.
                    if not is_problematic:
                        is_problematic = True
                        reason_for_problem = f"Container '{container_name}' is not ready."
                    if restart_count > 3: # Arbitrary threshold, could indicate a subtler CrashLoop
                        # Append restart info if not already captured by CrashLoopBackOff
                        if "CrashLoopBackOff" not in reason_for_problem:
                           reason_for_problem += f" It has restarted {restart_count} times."
                        is_problematic = True # Ensure it's marked

            # If the pod is Job-related and has Succeeded or Completed, it's not problematic for this function's purpose
            if is_job_related_pod and (phase == "Succeeded" or phase == "Completed"):
                # Check if any container *actually* failed with non-zero exit code
                # If all containers completed with exit code 0, then it's truly not problematic.
                all_job_containers_completed_successfully = True
                if not container_statuses: # No containers ran, can happen for misconfigured jobs
                    all_job_containers_completed_successfully = False

                for cs in container_statuses:
                    if "terminated" in cs.get("state", {}):
                        if cs["state"]["terminated"].get("exitCode", -1) != 0:
                            all_job_containers_completed_successfully = False
                            # Update reason if it's a job pod that Succeeded but had a failed container
                            phase = cs["state"]["terminated"].get("reason", phase) # more specific reason
                            reason_for_problem = f"Container '{cs.get('name','')}' in Job pod terminated with exit code {cs['state']['terminated'].get('exitCode', -1)}."
                            break # One failed container is enough to mark it problematic
                    else: # If any container is not terminated in a Succeeded/Completed job pod (should not happen)
                        all_job_containers_completed_successfully = False
                        reason_for_problem = f"Container '{cs.get('name','')}' in Job pod is not in a terminated state despite pod '{phase}'."
                        break
                
                if all_job_containers_completed_successfully:
                    is_problematic = False # Override previous flags if it's a truly successful job.
                else:
                    is_problematic = True # Ensure it's marked if job containers didn't all succeed


            if is_problematic:
                problematic_pods_info.append({
                    "name": pod_name,
                    "namespace": namespace, # Already have this from entities
                    "status_phase": phase,
                    "reason": reason_for_problem.strip()
                })
        
        if problematic_pods_info:
            pods_str = "\n".join([f"• *{pod['name']}* (Phase: {pod['status_phase']}): {pod['reason']}" for pod in problematic_pods_info])
            message = f"Found {len(problematic_pods_info)} problematic pods in namespace '{namespace}' (context: {kube_context or 'default'}):\n{pods_str}"
        else:
            message = f"No problematic pods found in namespace '{namespace}' (context: {kube_context or 'default'}."
        
        return {
            "status": "success",
            "message": message,
            "details": {"problematic_pods_count": len(problematic_pods_info)}
        }
    
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse kubectl output for failing pods (context: {kube_context}): {result.get('output', '')[:500]} - Error: {e}")
        raise HTTPException(status_code=500, detail={"status": "error", "message": "Failed to parse kubectl output"})
    except Exception as e:
        logger.error(f"Unexpected error in get_failing_pods (context: {kube_context}): {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail={"status": "error", "message": f"An unexpected error occurred while processing pods: {str(e)}"})


@app.post("/mcp/describe_pod")
async def describe_pod(request: MCPRequest = Body(...)):
    entities = request.entities
    namespace = entities.namespace
    pod_name = entities.pod_name
    kube_context = entities.kube_context # <--- Get context

    if not pod_name:
        raise HTTPException(status_code=400, detail={"status": "error", "message": "Pod name is required, Please mention pod name in the request."})
    
    if not namespace:
        raise HTTPException(status_code=400, detail={"status": "error", "message": "Namespace is required, Please mention namespace for the pod in the request."})

    logger.info(f"Received describe_pod request for pod: {pod_name} in namespace: {namespace}, context: {kube_context}")
    
    cmd_args = ["describe", "pod", pod_name, "-n", namespace]
    result = run_kubectl_command(cmd_args, kube_context=kube_context) # <--- Pass context
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail={"status": "error", "message": result["message"]})
    
    return {
        "status": "success",
        "message": f"Details for pod {pod_name} in namespace {namespace} (context: {kube_context or 'default'}):",
        "details": result["output"]
    }

@app.post("/mcp/get_pod_logs")
async def get_pod_logs(request: MCPRequest = Body(...)):
    entities = request.entities
    namespace = entities.namespace
    pod_name = entities.pod_name
    kube_context = entities.kube_context # <--- Get context
    if not pod_name:
        raise HTTPException(status_code=400, detail={"status": "error", "message": "Pod name is required, Please mention pod name in the request."})
    
    if not namespace:
        raise HTTPException(status_code=400, detail={"status": "error", "message": "Namespace is required, Please mention namespace for the pod in the request."})
    
    logger.info(f"Received get_pod_logs request for pod: {pod_name} in namespace: {namespace}, context: {kube_context}")
    log_lines="50"  # Default number of log lines to fetch, can be made configurable
    cmd_args = ["logs", pod_name, "-n", namespace, "--all-containers", "--tail", log_lines] # Consider making --tail configurable
    result = run_kubectl_command(cmd_args, kube_context=kube_context) # <--- Pass context
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail={"status": "error", "message": result["message"]})
    
    return {
        "status": "success",
        "message": f"Logs for pod {pod_name} in namespace {namespace} (context: {kube_context or 'default'}, last {log_lines} lines):",
        "details": result["output"]
    }

@app.post("/mcp/get_deployments")
async def get_deployments(request: MCPRequest = Body(...)):
    entities = request.entities
    namespace = entities.namespace
    kube_context = entities.kube_context # <--- Get context
    
    logger.info(f"Received get_deployments request for namespace: {namespace}, context: {kube_context}")
    
    cmd_args = ["get", "deployments", "-n", namespace]
    result = run_kubectl_command(cmd_args, kube_context=kube_context) # <--- Pass context
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail={"status": "error", "message": result["message"]})
    
    return {
        "status": "success",
        "message": f"Deployments in namespace {namespace} (context: {kube_context or 'default'}):",
        "details": result["output"]
    }

@app.post("/mcp/restart_deployment")
async def restart_deployment(request: MCPRequest = Body(...)):
    entities = request.entities
    namespace = entities.namespace
    deployment_name = entities.deployment_name
    kube_context = entities.kube_context # <--- Get context

    if not deployment_name:
        raise HTTPException(status_code=400, detail={"status": "error", "message": "Deployment name is required"})
    
    logger.info(f"Received restart_deployment request for deployment: {deployment_name} in namespace: {namespace}, context: {kube_context}")
    
    cmd_args = ["rollout", "restart", "deployment", deployment_name, "-n", namespace]
    result = run_kubectl_command(cmd_args, kube_context=kube_context) # <--- Pass context
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail={"status": "error", "message": result["message"]})
    
    return {
        "status": "success",
        "message": f"Deployment {deployment_name} in namespace {namespace} (context: {kube_context or 'default'}) restarted",
        "details": result["output"]
    }

@app.post("/mcp/execute_kubectl")
async def execute_kubectl(request: MCPRequest = Body(...)):
    entities = request.entities
    namespace = entities.namespace # Namespace might be part of the command itself
    command = entities.command
    args = entities.args or []
    kube_context = entities.kube_context # <--- Get context
    
    if not command:
        raise HTTPException(status_code=400, detail={"status": "error", "message": "Command is required"})

    # Safeguard Check
    full_command_str = (command + " " + " ".join(args)).lower()
    for blocked_keyword in DESTRUCTIVE_COMMAND_BLOCKLIST:
        # Check if a blocked keyword appears as a whole word
        if f" {blocked_keyword} " in f" {full_command_str} " or full_command_str.startswith(f"{blocked_keyword} "):
            logger.warning(
                f"BLOCKED destructive command from user {request.slack_user_id}. "
                f"Attempted to run: '{full_command_str}'"
            )
            raise HTTPException(
                status_code=403, # 403 Forbidden
                detail={
                    "status": "error",
                    "message": "This action is prohibited for security reasons. The attempt has been logged."
                }
            )

    # Build the command arguments
    cmd_args = command.split() + args
    # Add namespace if it's provided and not already in the command string/args
    # This logic might need refinement if command can be very complex
    if namespace and "-n" not in cmd_args and "--namespace" not in cmd_args:
        # Check if the command is namespace-scoped before adding -n
        # For simplicity here, we add it if namespace is given.
        # A more robust solution would check if the resource type in 'command' is namespaced.
        cmd_args.extend(["-n", namespace]) 
    
    logger.info(f"Received execute_kubectl request with command: {' '.join(cmd_args)}, context: {kube_context}")
    
    result = run_kubectl_command(cmd_args, kube_context=kube_context) # <--- Pass context
    
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail={"status": "error", "message": result["message"]})
    
    return {
        "status": "success",
        "message": f"Kubectl command executed successfully (context: {kube_context or 'default'})",
        "details": result["output"]
    }

@app.post("/mcp/get_unhealthy_nodes")
async def get_unhealthy_nodes(request: MCPRequest = Body(...)):
    """
    Identifies and returns nodes that are not in a 'Ready' state or have pressure conditions.
    """
    entities = request.entities
    kube_context = entities.kube_context
    logger.info(f"Received get_unhealthy_nodes request for context: {kube_context}")

    cmd_args = ["get", "nodes", "-o", "json"]
    result = run_kubectl_command(cmd_args, kube_context=kube_context)

    if result["status"] == "error":
        raise HTTPException(status_code=500, detail={"status": "error", "message": result["message"]})

    try:
        nodes_data = json.loads(result["output"])
        unhealthy_nodes = []

        for node in nodes_data.get("items", []):
            node_name = node["metadata"]["name"]
            conditions = node["status"]["conditions"]
            is_unhealthy = False
            reason = ""

            # Find the 'Ready' condition
            ready_condition = next((c for c in conditions if c["type"] == "Ready"), None)

            if not ready_condition or ready_condition["status"] != "True":
                is_unhealthy = True
                reason = f"Node is not ready. Status: {ready_condition['status'] if ready_condition else 'Unknown'}, Reason: {ready_condition['reason'] if ready_condition else 'Unknown'}"
            else:
                # Check for other pressure conditions
                for cond in conditions:
                    if cond["type"] != "Ready" and cond["status"] == "True":
                        is_unhealthy = True
                        reason = f"Node has active pressure condition: {cond['type']}"
                        break # One reason is enough

            if is_unhealthy:
                unhealthy_nodes.append({"name": node_name, "reason": reason})

        if not unhealthy_nodes:
            message = f"All nodes are healthy in context '{kube_context or 'default'}'."
        else:
            details_str = "\n".join([f"- *{node['name']}*: {node['reason']}" for node in unhealthy_nodes])
            message = f"Found {len(unhealthy_nodes)} unhealthy node(s) in context '{kube_context or 'default'}':\n{details_str}"

        return {"status": "success", "message": message, "details": unhealthy_nodes}

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Error parsing node data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"status": "error", "message": f"Failed to parse node data: {str(e)}"})


@app.post("/mcp/get_nodes_by_memory")
async def get_nodes_by_memory(request: MCPRequest = Body(...)):
    """
    Finds nodes where memory usage is above a given percentage threshold.
    """
    entities = request.entities
    kube_context = entities.kube_context
    threshold = entities.memory_threshold_percent
    logger.info(f"Received request for nodes with memory usage > {threshold}% in context: {kube_context}")

    # Step 1: Get node metrics using 'kubectl top nodes'
    cmd_args = ["top", "nodes", "--no-headers"]
    metrics_result = run_kubectl_command(cmd_args, kube_context=kube_context)

    if metrics_result["status"] == "error":
        # Check if metrics-server is not installed
        if "metrics-server" in metrics_result["message"]:
            msg = "The 'kubectl top' command failed. Please ensure the Kubernetes Metrics Server is installed and running in your cluster."
            raise HTTPException(status_code=501, detail={"status": "error", "message": msg})
        raise HTTPException(status_code=500, detail={"status": "error", "message": metrics_result["message"]})

    # Step 2: Get node capacity using 'kubectl get nodes'
    cmd_args = ["get", "nodes", "-o", "json"]
    capacity_result = run_kubectl_command(cmd_args, kube_context=kube_context)
    if capacity_result["status"] == "error":
        raise HTTPException(status_code=500, detail={"status": "error", "message": capacity_result["message"]})

    try:
        nodes_capacity_data = json.loads(capacity_result["output"])
        node_capacities = {}
        for node in nodes_capacity_data.get("items", []):
            node_name = node["metadata"]["name"]
            mem_capacity_str = node["status"]["capacity"]["memory"]
            if mem_capacity_str.endswith("Ki"):
                mem_capacity_kb = int(mem_capacity_str[:-2])
            elif mem_capacity_str.endswith("Mi"):
                mem_capacity_kb = int(mem_capacity_str[:-2]) * 1024
            elif mem_capacity_str.endswith("Gi"):
                mem_capacity_kb = int(mem_capacity_str[:-2]) * 1024 * 1024
            else:
                mem_capacity_kb = int(mem_capacity_str) / 1024 # Assuming bytes if no unit
            node_capacities[node_name] = mem_capacity_kb

        high_memory_nodes = []
        metrics_lines = metrics_result["output"].strip().split('\n')
        for line in metrics_lines:
            parts = line.split()
            node_name = parts[0]
            # Memory usage from 'top' command is also in Mi, so we convert to KB
            # Add a check to ensure the line is well-formed
            if len(parts) < 4:
                continue

            node_name = parts[0]
            mem_usage_str = parts[3]

            # Handle different units (Mi or Ki) for memory usage
            if mem_usage_str.endswith("Mi"):
                mem_usage_kb = int(mem_usage_str[:-2]) * 1024
            elif mem_usage_str.endswith("Ki"):
                mem_usage_kb = int(mem_usage_str[:-2])
            else:
                # Skip if the format is unexpected
                logger.warning(f"Could not parse memory usage '{mem_usage_str}' for node {node_name}")
                continue

            if node_name in node_capacities:
                capacity_kb = node_capacities[node_name]
                usage_percent = (mem_usage_kb / capacity_kb) * 100
                if usage_percent > threshold:
                    high_memory_nodes.append({
                        "name": node_name,
                        "memory_usage_percent": f"{usage_percent:.2f}%",
                        "memory_usage": f"{mem_usage_kb / (1024*1024):.2f}Gi",
                        "memory_capacity": f"{capacity_kb / (1024*1024):.2f}Gi"
                    })

        if not high_memory_nodes:
            message = f"No nodes found with memory usage above {threshold}% in context '{kube_context or 'default'}'."
        else:
            details_str = "\n".join([f"- *{node['name']}*: {node['memory_usage_percent']} used ({node['memory_usage']} / {node['memory_capacity']})" for node in high_memory_nodes])
            message = f"Found {len(high_memory_nodes)} node(s) with memory usage above {threshold}%:\n{details_str}"

        return {"status": "success", "message": message, "details": high_memory_nodes}

    except (json.JSONDecodeError, KeyError, ValueError, IndexError) as e:
        logger.error(f"Error processing node metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail={"status": "error", "message": f"Failed to process node metrics: {str(e)}"})


@app.post("/mcp/troubleshoot_pod")
async def troubleshoot_pod(request: MCPRequest = Body(...)):
    """
    Gathers diagnostic information for a pod by internally calling the
    describe_pod and get_pod_logs functions.
    """
    entities = request.entities
    if not entities.pod_name or not entities.namespace:
        raise HTTPException(status_code=400, detail={"status": "error", "message": "Pod name and namespace are required."})

    logger.info(f"Received troubleshoot request for pod '{entities.pod_name}' in namespace '{entities.namespace}'")

    try:
        # Step 1: Directly call the describe_pod function and await its result
        describe_response = await describe_pod(request)
        describe_output = describe_response["details"]
    except HTTPException as e:
        # If describe_pod fails, we can't continue.
        logger.error(f"Troubleshoot failed at describe stage: {e.detail}")
        raise e # Re-raise the exception to send the error to the client

    # Step 2: Directly call the get_pod_logs function and await its result
    logs_response = await get_pod_logs(request)
    # The get_pod_logs function returns a 'details' key for both success and error cases
    logs_output = logs_response["details"]

    # Step 3: Combine the results from the function calls into a single report
    combined_details = f"""
### Pod Description for '{entities.pod_name}' ###
---
{describe_output}

### Recent Logs for '{entities.pod_name}' (last 100 lines) ###
---
{logs_output}
"""
    return {
        "status": "success",
        "message": f"Collected troubleshooting data for pod '{entities.pod_name}'.",
        "details": combined_details.strip()
    }


mcp = FastApiMCP(
    app,
    name="Kube MCP Server",
    description="MCP Server that handles kubernetes tasks.",
)

mcp.mount()

# To run the server:
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
