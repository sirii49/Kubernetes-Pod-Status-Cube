from datetime import datetime, timezone
import os

from flask import Flask, jsonify, render_template, request
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from kubernetes.config.config_exception import ConfigException

from database import (
    init_db,
    record_snapshot,
    get_history,
    get_alerts,
    acknowledge_alerts,
)

app = Flask(__name__, template_folder="../templates", static_folder="../static")
init_db()

# Render's public demo uses sample data and does not require a live Kubernetes cluster.
DEMO_MODE = os.getenv("DEMO_MODE", "false").strip().lower() in {"1", "true", "yes"}


def demo_pods():
    """Return clearly simulated pod records for the hosted demonstration."""
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "name": "demo-web-7c9f8d6b5f-a1b2c",
            "namespace": "pod-cube-demo",
            "status": "Running",
            "display_state": "running",
            "color": "GREEN",
            "detail": "All containers ready",
            "ready": 1,
            "container_total": 1,
            "restarts": 0,
            "ip": "10.244.0.12",
            "node": "minikube-demo",
            "created": now,
            "conditions": [{"type": "Ready", "status": "True", "reason": "", "message": "Pod is ready (simulated)"}],
            "containers": [{"name": "nginx", "ready": True, "restart_count": 0, "state": "running"}],
        },
        {
            "name": "demo-web-7c9f8d6b5f-d3e4f",
            "namespace": "pod-cube-demo",
            "status": "Running",
            "display_state": "running",
            "color": "GREEN",
            "detail": "All containers ready",
            "ready": 1,
            "container_total": 1,
            "restarts": 1,
            "ip": "10.244.0.13",
            "node": "minikube-demo",
            "created": now,
            "conditions": [{"type": "Ready", "status": "True", "reason": "", "message": "Pod is ready (simulated)"}],
            "containers": [{"name": "nginx", "ready": True, "restart_count": 1, "state": "running"}],
        },
        {
            "name": "demo-api-6d8b7c9f4-p5q6r",
            "namespace": "pod-cube-demo",
            "status": "Pending",
            "display_state": "pending",
            "color": "GREY",
            "detail": "Pod is waiting for scheduling",
            "ready": 0,
            "container_total": 1,
            "restarts": 0,
            "ip": "—",
            "node": "—",
            "created": now,
            "conditions": [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable", "message": "Waiting for available capacity (simulated)"}],
            "containers": [{"name": "api", "ready": False, "restart_count": 0, "state": "waiting: ContainerCreating"}],
        },
        {
            "name": "demo-worker-5f6d7c8b9-x7y8z",
            "namespace": "pod-cube-demo",
            "status": "CrashLoopBackOff",
            "display_state": "crash",
            "color": "RED",
            "detail": "CrashLoopBackOff",
            "ready": 0,
            "container_total": 1,
            "restarts": 5,
            "ip": "10.244.0.15",
            "node": "minikube-demo",
            "created": now,
            "conditions": [{"type": "Ready", "status": "False", "reason": "ContainersNotReady", "message": "Container is restarting (simulated)"}],
            "containers": [{"name": "worker", "ready": False, "restart_count": 5, "state": "waiting: CrashLoopBackOff"}],
        },
    ]


def demo_deployments():
    return [
        {"name": "demo-web", "namespace": "pod-cube-demo", "desired": 2, "updated": 2, "available": 2, "ready": 2, "rollout": "Complete"},
        {"name": "demo-api", "namespace": "pod-cube-demo", "desired": 1, "updated": 0, "available": 0, "ready": 0, "rollout": "In progress"},
    ]


def demo_events():
    now = datetime.now(timezone.utc).isoformat()
    return [
        {"type": "Normal", "reason": "Scheduled", "message": "Successfully assigned pod to minikube-demo (simulated)", "object": "demo-web-7c9f8d6b5f-a1b2c", "namespace": "pod-cube-demo", "time": now},
        {"type": "Warning", "reason": "BackOff", "message": "Back-off restarting failed container (simulated)", "object": "demo-worker-5f6d7c8b9-x7y8z", "namespace": "pod-cube-demo", "time": now},
    ]


def load_clients():
    """Use in-cluster credentials on Kubernetes; otherwise use local kubeconfig."""
    try:
        config.load_incluster_config()
    except ConfigException:
        config.load_kube_config()
    return client.CoreV1Api(), client.AppsV1Api()


def selector_string(selector):
    if not selector:
        return ""
    parts = []
    for key, value in (selector.match_labels or {}).items():
        parts.append(f"{key}={value}")
    for expr in selector.match_expressions or []:
        values = ",".join(expr.values or [])
        if expr.operator == "In":
            parts.append(f"{expr.key} in ({values})")
        elif expr.operator == "NotIn":
            parts.append(f"{expr.key} notin ({values})")
        elif expr.operator == "Exists":
            parts.append(expr.key)
        elif expr.operator == "DoesNotExist":
            parts.append("!" + expr.key)
    return ",".join(parts)


def deployment_rollouts(apps):
    """Return selectors for deployments whose rollout is still progressing."""
    result = []
    deployments = apps.list_deployment_for_all_namespaces().items
    for dep in deployments:
        spec = dep.spec
        status = dep.status
        desired = spec.replicas or 0
        updated = status.updated_replicas or 0
        available = status.available_replicas or 0
        progressing = updated < desired or available < desired
        for condition in (status.conditions or []):
            if condition.type == "Progressing" and condition.status == "True" and condition.reason == "NewReplicaSetCreated":
                progressing = True
        if progressing and spec.selector:
            result.append({
                "namespace": dep.metadata.namespace,
                "selector": selector_string(spec.selector),
                "name": dep.metadata.name,
            })
    return result


def classify_pod(pod, rollouts):
    """Classify actual Pod/container states; failures take priority."""
    namespace = pod.metadata.namespace
    reasons = []
    statuses_all = (pod.status.container_statuses or []) + (pod.status.init_container_statuses or [])
    for status in statuses_all:
        waiting = status.state.waiting if status.state else None
        terminated = status.state.terminated if status.state else None
        if waiting and waiting.reason:
            reasons.append(waiting.reason)
        if terminated and terminated.reason:
            reasons.append(terminated.reason)

    red_reasons = {
        "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
        "CreateContainerConfigError", "RunContainerError",
    }
    if pod.status.phase == "Failed" or any(reason in red_reasons for reason in reasons):
        return "crash", "RED", ", ".join(reasons) or "Pod failed"

    labels = pod.metadata.labels or {}
    for rollout in rollouts:
        if rollout["namespace"] != namespace or not rollout["selector"]:
            continue
        matches = True
        for item in rollout["selector"].split(","):
            if " in " in item or " notin " in item or item.startswith("!"):
                continue
            if "=" in item:
                key, value = item.split("=", 1)
                if labels.get(key) != value:
                    matches = False
                    break
        if matches:
            return "updating", "YELLOW", f"Deployment rollout: {rollout['name']}"

    container_statuses = pod.status.container_statuses or []
    all_ready = bool(container_statuses) and all(status.ready for status in container_statuses)
    if pod.status.phase == "Running" and all_ready:
        return "running", "GREEN", "All containers ready"
    if pod.status.phase == "Succeeded":
        return "completed", "BLUE", "Pod completed successfully"
    if pod.status.phase == "Running":
        return "not-ready", "GREY", "Running, but one or more containers are not ready"
    return "pending", "GREY", pod.status.phase or "Unknown"


def pod_to_dict(pod, rollouts):
    state, color, detail = classify_pod(pod, rollouts)
    statuses = pod.status.container_statuses or []
    return {
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "status": pod.status.phase or "Unknown",
        "display_state": state,
        "color": color,
        "detail": detail,
        "ready": sum(1 for status in statuses if status.ready),
        "container_total": len(statuses),
        "restarts": sum(status.restart_count or 0 for status in statuses),
        "ip": pod.status.pod_ip or "—",
        "node": pod.spec.node_name or "—",
        "created": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None,
        "conditions": [
            {"type": condition.type, "status": condition.status, "reason": condition.reason or "", "message": condition.message or ""}
            for condition in (pod.status.conditions or [])
        ],
        "containers": [
            {
                "name": status.name,
                "ready": status.ready,
                "restart_count": status.restart_count,
                "state": ("waiting: " + (status.state.waiting.reason or "unknown")) if status.state and status.state.waiting
                else ("terminated: " + (status.state.terminated.reason or "unknown")) if status.state and status.state.terminated
                else "running",
            }
            for status in statuses
        ],
    }


def collect_cluster_data(namespace=None):
    core, apps = load_clients()
    rollouts = deployment_rollouts(apps)
    pod_list = core.list_namespaced_pod(namespace) if namespace else core.list_pod_for_all_namespaces()
    pods = [pod_to_dict(pod, rollouts) for pod in pod_list.items]
    deployments_raw = apps.list_namespaced_deployment(namespace) if namespace else apps.list_deployment_for_all_namespaces()
    deployments = []
    for deployment in deployments_raw.items:
        status = deployment.status
        desired = deployment.spec.replicas or 0
        updated = status.updated_replicas or 0
        available = status.available_replicas or 0
        deployments.append({
            "name": deployment.metadata.name,
            "namespace": deployment.metadata.namespace,
            "desired": desired,
            "updated": updated,
            "available": available,
            "ready": status.ready_replicas or 0,
            "rollout": "In progress" if updated < desired or available < desired else "Complete",
        })
    return core, apps, pods, deployments


def get_pods_for_request(namespace=None):
    if DEMO_MODE:
        pods = demo_pods()
        return [pod for pod in pods if not namespace or pod["namespace"] == namespace]
    return collect_cluster_data(namespace)[2]


def get_deployments_for_request(namespace=None):
    if DEMO_MODE:
        deployments = demo_deployments()
        return [deployment for deployment in deployments if not namespace or deployment["namespace"] == namespace]
    return collect_cluster_data(namespace)[3]


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "mode": "demo" if DEMO_MODE else "kubernetes"})


@app.get("/api/cluster")
def cluster():
    """Render health check and overview data; demo mode never contacts Kubernetes."""
    try:
        if DEMO_MODE:
            pods = demo_pods()
            deployments = demo_deployments()
            return jsonify({
                "connected": True,
                "demo_mode": True,
                "cluster": "Demo Kubernetes (Simulated)",
                "node_count": 1,
                "pod_count": len(pods),
                "running": sum(pod["display_state"] == "running" for pod in pods),
                "crashed": sum(pod["display_state"] == "crash" for pod in pods),
                "updating": sum(pod["display_state"] == "updating" for pod in pods),
                "pods": pods,
                "deployments": deployments,
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
            })

        core, _, pods, deployments = collect_cluster_data()
        nodes = core.list_node().items
        return jsonify({
            "connected": True,
            "demo_mode": False,
            "cluster": "Kubernetes",
            "node_count": len(nodes),
            "pod_count": len(pods),
            "running": sum(pod["display_state"] == "running" for pod in pods),
            "crashed": sum(pod["display_state"] == "crash" for pod in pods),
            "updating": sum(pod["display_state"] == "updating" for pod in pods),
            "pods": pods,
            "deployments": deployments,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        })
    except (ConfigException, ApiException, OSError) as exc:
        app.logger.warning("Kubernetes connection failed: %s", exc)
        return jsonify({"connected": False, "error": str(exc), "hint": "Check the Kubernetes connection and kubeconfig."}), 503
    except Exception as exc:
        app.logger.exception("Unexpected monitoring error")
        return jsonify({"connected": False, "error": str(exc)}), 500


@app.get("/api/pods")
def pods_endpoint():
    try:
        namespace = request.args.get("namespace") or None
        return jsonify(get_pods_for_request(namespace))
    except Exception as exc:
        app.logger.exception("Could not list pods")
        return jsonify({"error": str(exc)}), 503


@app.get("/api/pods/<namespace>/<pod_name>")
def pod_detail(namespace, pod_name):
    if DEMO_MODE:
        pod = next((item for item in demo_pods() if item["namespace"] == namespace and item["name"] == pod_name), None)
        if pod is None:
            return jsonify({"error": "Pod not found"}), 404
        return jsonify(pod)
    try:
        core, apps = load_clients()
        pod = core.read_namespaced_pod(pod_name, namespace)
        return jsonify(pod_to_dict(pod, deployment_rollouts(apps)))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 404


@app.get("/api/deployments")
def deployments_endpoint():
    try:
        namespace = request.args.get("namespace") or None
        return jsonify(get_deployments_for_request(namespace))
    except Exception as exc:
        app.logger.exception("Could not list deployments")
        return jsonify({"error": str(exc)}), 503


@app.get("/api/namespaces")
def namespaces_endpoint():
    if DEMO_MODE:
        return jsonify(["pod-cube-demo"])
    try:
        core, _ = load_clients()
        return jsonify([item.metadata.name for item in core.list_namespace().items])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.get("/api/events")
def events_endpoint():
    namespace = request.args.get("namespace") or None
    if DEMO_MODE:
        events = demo_events()
        return jsonify([event for event in events if not namespace or event["namespace"] == namespace])
    try:
        core, _ = load_clients()
        event_list = core.list_namespaced_event(namespace) if namespace else core.list_event_for_all_namespaces()
        items = sorted(
            event_list.items,
            key=lambda event: event.last_timestamp or event.event_time or event.metadata.creation_timestamp or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return jsonify([
            {
                "type": event.type or "Normal",
                "reason": event.reason or "",
                "message": event.message or "",
                "object": event.involved_object.name or "",
                "namespace": event.metadata.namespace or "",
                "time": (event.last_timestamp or event.event_time or event.metadata.creation_timestamp).isoformat()
                if (event.last_timestamp or event.event_time or event.metadata.creation_timestamp) else None,
            }
            for event in items[:100]
        ])
    except Exception as exc:
        return jsonify({"error": str(exc)}), 503


@app.get("/api/history")
def history_endpoint():
    try:
        limit = int(request.args.get("limit", 100))
        limit = max(1, min(limit, 500))
    except (TypeError, ValueError):
        limit = 100
    return jsonify(get_history(limit=limit))


@app.get("/api/alerts")
def alerts_endpoint():
    return jsonify(get_alerts())


@app.post("/api/alerts/acknowledge")
def acknowledge_endpoint():
    acknowledge_alerts()
    return jsonify({"ok": True})


@app.post("/api/monitor")
def monitor_endpoint():
    """Save a monitoring snapshot from either demo data or a live cluster."""
    try:
        pods = demo_pods() if DEMO_MODE else collect_cluster_data()[2]
        record_snapshot(pods)
        return jsonify({"saved": True, "count": len(pods), "demo_mode": DEMO_MODE})
    except Exception as exc:
        app.logger.exception("Could not record monitoring snapshot")
        return jsonify({"saved": False, "error": str(exc)}), 503


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
